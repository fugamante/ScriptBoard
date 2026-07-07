#!/usr/bin/env python3
"""Build storyboard prompts from local screenplay drafts."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from scriptboard.config import ScriptBoardConfig, load_config, regex_flags

SCENE_HEADING_RE = re.compile(
    r"^(?P<head>(?:INT|EXT|INT\./EXT|EXT\./INT|INT/EXT|EXT/INT)\.?\s+.+|"
    r"INTERCUT\s+-\s+.+)$",
    re.IGNORECASE | re.MULTILINE,
)
CHARACTER_CUE_RE = re.compile(r"^[A-Z][A-Z0-9 '\-.]{1,34}$", re.MULTILINE)
TRANSITION_RE = re.compile(r"^(FADE|CUT TO|DISSOLVE|BACK TO|INTERCUT WITH|FLASH(?:ES|BACKS)?)", re.IGNORECASE)
FLASH_START_RE = re.compile(r"^FLASH(?:ES|BACKS)?(?:\s+-\s+(?P<context>.+))?:$", re.IGNORECASE)
FLASH_END_RE = re.compile(r"^(BACK TO|CUT TO|FADE TO|DISSOLVE)", re.IGNORECASE)

@dataclass
class DraftScene:
    number: int
    heading: str
    source: str
    body: str
    characters: list[str]
    beats: list[str]


@dataclass
class PromptFrame:
    id: str
    label: str
    script_passage: str
    prompt: str


@dataclass
class PromptPack:
    id: str
    title: str
    location: str
    frames: list[PromptFrame]


FDPAR_RE = re.compile(r'<Paragraph Type="([^"]+)"[^>]*>(.*?)</Paragraph>', re.S)
FDTEXT_RE = re.compile(r"<Text[^>]*>(.*?)</Text>", re.S)


def render_fdx_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    paragraphs: list[str] = []
    for paragraph_type, body in FDPAR_RE.findall(raw):
        text = html.unescape("".join(FDTEXT_RE.findall(body)))
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        if paragraph_type == "Scene Heading":
            paragraphs.append(text.upper())
        elif paragraph_type == "Character":
            paragraphs.append(text.upper())
        else:
            paragraphs.append(text)
    return "\n\n".join(paragraphs).strip() + "\n"


def read_text(path: Path) -> str:
    if path.suffix.lower() == ".fdx":
        return render_fdx_text(path)
    return path.read_text(encoding="utf-8", errors="replace")


def clean_line(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("`", "")).strip(" -\n\t")


def slug(value: str, limit: int = 56) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return value[:limit].strip("_") or "untitled"


def stable_hash(value: str, length: int = 10) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def prompt_safe_passage(value: str, config: ScriptBoardConfig | None = None) -> str:
    config = config or ScriptBoardConfig()
    for item in config.safety.replacements:
        pattern = item.get("pattern")
        replacement = item.get("replacement", "")
        if not pattern:
            continue
        value = re.sub(pattern, replacement, value, flags=regex_flags(item.get("flags")))
    return value


def minor_safety_note(beat: str, config: ScriptBoardConfig | None = None) -> str:
    config = config or ScriptBoardConfig()
    lower = beat.lower()
    notes: list[str] = []
    for item in config.safety.notes:
        needle = item.get("contains", "").lower()
        note = item.get("note", "")
        if needle and note and needle in lower:
            notes.append(note)
    return " ".join(notes)


def concise_prompt(scene_heading: str, beat: str, style: str, config: ScriptBoardConfig | None = None) -> str:
    safe_passage = prompt_safe_passage(beat, config)
    flashback_instruction = (
        "This is a flashback memory; do not place it in the present-time location unless the passage itself says so. "
        if beat.startswith("FLASHBACK")
        else ""
    )
    safety_note = minor_safety_note(beat, config)
    return (
        "Storyboard frame. "
        f"Scene heading: {scene_heading}. "
        f"Visible moment: {safe_passage}. "
        f"{flashback_instruction}"
        f"{safety_note}"
        "Use only visible or strongly implied details from this moment. "
        f"{style}."
    )


def first_sentences(text: str, limit: int = 2) -> str:
    text = clean_line(re.sub(r"\[[^\]]*\]", "", text))
    parts = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(parts[:limit]).strip()


def is_character_cue(line: str) -> bool:
    return bool(CHARACTER_CUE_RE.fullmatch(line)) and not TRANSITION_RE.match(line)


VISUAL_TERMS = {
    "apartment",
    "baby",
    "back",
    "bed",
    "belly",
    "binder",
    "blood",
    "box",
    "car",
    "ceiling",
    "clock",
    "coffee",
    "desk",
    "door",
    "eyes",
    "face",
    "file",
    "hand",
    "light",
    "monitor",
    "office",
    "paper",
    "photo",
    "printer",
    "room",
    "street",
    "wheel",
}

EMOTIONAL_TERMS = {
    "afraid",
    "breaks",
    "breathing",
    "empty",
    "fear",
    "motionless",
    "panic",
    "silent",
    "stares",
    "terror",
    "trembling",
    "wild",
}


def action_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    previous_was_cue = False
    in_flash = False
    current_in_flash = False
    flash_context = ""

    def append_current() -> None:
        if not current:
            return
        block = " ".join(current)
        if current_in_flash:
            label = f"FLASHBACK IN {flash_context}: " if flash_context else "FLASHBACK: "
            block = f"{label}{block}"
        blocks.append(block)

    for raw in text.splitlines():
        line = clean_line(raw)
        if not line:
            if current:
                append_current()
                current = []
                current_in_flash = False
            previous_was_cue = False
            continue
        flash_match = FLASH_START_RE.match(line)
        if flash_match:
            if current:
                append_current()
                current = []
            in_flash = True
            flash_context = clean_line(flash_match.group("context") or "").upper()
            current_in_flash = False
            continue
        if in_flash and FLASH_END_RE.match(line):
            if current:
                append_current()
                current = []
            in_flash = False
            flash_context = ""
            current_in_flash = False
            continue
        if TRANSITION_RE.match(line):
            continue
        if is_character_cue(line):
            if current:
                append_current()
                current = []
                current_in_flash = False
            previous_was_cue = True
            continue
        if previous_was_cue:
            previous_was_cue = False
            continue
        if not current:
            current_in_flash = in_flash
        current.append(line)
    if current:
        append_current()
    return [block for block in blocks if len(block) >= 12]


def visual_score(block: str) -> int:
    lower = block.lower()
    score = 0
    score += sum(2 for term in VISUAL_TERMS if term in lower)
    score += sum(2 for term in EMOTIONAL_TERMS if term in lower)
    if "sarah" in lower or "sunny" in lower:
        score += 2
    if len(block) <= 90 and any(term in lower for term in VISUAL_TERMS):
        score += 3
    if re.match(r"^(a|an|the|she|he|sarah|sunny)\b", lower):
        score += 1
    return score


def forced_visual_blocks(text: str) -> set[str]:
    forced: set[str] = set()
    in_flash = False
    flash_context = ""
    for raw in text.splitlines():
        line = clean_line(raw)
        if not line:
            continue
        flash_match = FLASH_START_RE.match(line)
        if flash_match:
            in_flash = True
            flash_context = clean_line(flash_match.group("context") or "").upper()
            continue
        if in_flash and FLASH_END_RE.match(line):
            in_flash = False
            flash_context = ""
            continue
        if in_flash and not is_character_cue(line) and len(line) >= 12:
            label = f"FLASHBACK IN {flash_context}: " if flash_context else "FLASHBACK: "
            forced.add(f"{label}{line}")
    return forced


def select_story_beats(text: str, limit: int = 12) -> list[str]:
    blocks = action_blocks(text)
    if len(blocks) <= limit:
        return blocks
    scored = sorted(
        enumerate(blocks),
        key=lambda item: (visual_score(item[1]), -item[0]),
        reverse=True,
    )
    forced = forced_visual_blocks(text)
    selected_indexes = {0, len(blocks) - 1}
    selected_indexes.update(index for index, block in enumerate(blocks) if block in forced)
    for index, _block in scored:
        selected_indexes.add(index)
        if len(selected_indexes) >= limit:
            break
    return [blocks[index] for index in sorted(selected_indexes)]


def characters(text: str) -> list[str]:
    names: set[str] = set()
    ignored = {
        "FADE IN",
        "FADE TO",
        "CUT TO",
        "CUT TO BLACK",
        "BACK TO DELIVERY ROOM",
        "INTERCUT WITH",
        "FLASHES",
        "FLASHBACKS",
        "MOMENTS LATER",
    }
    for match in CHARACTER_CUE_RE.finditer(text):
        raw_name = match.group(0).strip()
        if raw_name.endswith((".", "!", "?")):
            continue
        name = clean_line(match.group(0).title())
        if raw_name in ignored:
            continue
        if len(name.split()) <= 4:
            names.add(name)
    return sorted(names)


def parse_draft_scenes(paths: Iterable[Path]) -> list[DraftScene]:
    scenes: list[DraftScene] = []
    for path in paths:
        text = read_text(path)
        matches = list(SCENE_HEADING_RE.finditer(text))
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            body = text[start:end].strip()
            if len(body) < 80:
                continue
            scenes.append(
                DraftScene(
                    number=len(scenes) + 1,
                    heading=clean_line(match.group("head")).upper(),
                    source=path.name,
                    body=body,
                    characters=characters(body),
                    beats=select_story_beats(body),
                )
            )
    return scenes


def draft_prompt_pack(scene: DraftScene, style: str, config: ScriptBoardConfig | None = None) -> PromptPack:
    frames = []
    scene_id = f"scene_{scene.number:03d}_{slug(scene.heading)}"
    for index, beat in enumerate(scene.beats, start=1):
        frame_type = "Opening Panel" if index == 1 else "Final Panel" if index == len(scene.beats) else f"Panel {index}"
        frame_id = f"{scene_id}_panel_{index:03d}_{stable_hash(beat)}"
        frames.append(
            PromptFrame(
                frame_id,
                frame_type,
                beat,
                concise_prompt(scene.heading, beat, style, config),
            )
        )
    return PromptPack(scene_id, scene.heading, scene.heading, frames)


def markdown(scenes: list[DraftScene], packs: list[PromptPack], config: ScriptBoardConfig | None = None) -> str:
    config = config or ScriptBoardConfig()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Storyboard Prompts: {config.title}",
        "",
        f"Generated: {stamp}",
        "",
        "## Use",
        "",
        "- These prompts follow drafted screenplay text only.",
        "- Copy one prompt at a time into your image generation tool.",
        "- Each prompt includes the script passage it represents.",
        "- Do not use the story bible or beat sheet to add material that is not on the current screenplay page.",
        "",
        "## Source Summary",
        "",
        f"- Draft screenplay scenes found: {len(scenes)}",
        f"- Storyboard panels generated: {sum(len(pack.frames) for pack in packs)}",
        "",
        "## Draft Storyboard Prompt Packs",
        "",
    ]
    for pack in packs:
        lines.extend([f"### {pack.title}", ""])
        if pack.location:
            lines.append(f"Location: {pack.location}")
            lines.append("")
        for frame in pack.frames:
            lines.extend([f"#### {frame.label}", "", frame.prompt, ""])
    return "\n".join(lines).rstrip() + "\n"


def output_json(scenes: list[DraftScene], packs: list[PromptPack], config: ScriptBoardConfig | None = None) -> str:
    config = config or ScriptBoardConfig()
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_policy": config.source_policy,
        "title": config.title,
        "style": config.visual_style,
        "draft_scenes": [asdict(scene) for scene in scenes],
        "prompt_packs": [asdict(pack) for pack in packs],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def candidate_files(input_dir: Path, config: ScriptBoardConfig | None = None) -> list[Path]:
    config = config or ScriptBoardConfig()
    extensions = {suffix.lower() for suffix in config.sources.extensions}
    candidates = sorted(
        path
        for path in input_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() in extensions
        and path.name not in {config.outputs.prompts_md, config.outputs.prompts_json}
        and path.name != "README_storyboard_automation.md"
    )
    filtered = [
        path
        for path in candidates
        if any(path.name.startswith(prefix) for prefix in config.sources.stem_prefixes)
        or any(value in path.stem for value in config.sources.stem_contains)
    ]
    preferred: dict[str, Path] = {}
    suffix_rank = {suffix.lower(): index for index, suffix in enumerate(config.sources.priority)}
    for path in filtered:
        current = preferred.get(path.stem)
        current_rank = suffix_rank.get(path.suffix.lower(), len(suffix_rank))
        old_rank = suffix_rank.get(current.suffix.lower(), len(suffix_rank)) if current else len(suffix_rank)
        if current is None or current_rank < old_rank:
            preferred[path.stem] = path
    return sorted(preferred.values())


def build(input_dir: Path, md_path: Path, json_path: Path, config: ScriptBoardConfig | None = None) -> None:
    config = config or ScriptBoardConfig()
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")
    draft_paths = candidate_files(input_dir, config)
    scenes = parse_draft_scenes(draft_paths)
    packs = [draft_prompt_pack(scene, config.visual_style, config) for scene in scenes]
    md_path.write_text(markdown(scenes, packs, config), encoding="utf-8")
    json_path.write_text(output_json(scenes, packs, config), encoding="utf-8")
    print(f"Wrote {md_path}", file=sys.stderr)
    print(f"Wrote {json_path}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path.cwd(), help="Folder containing screenplay drafts.")
    parser.add_argument("--config", type=Path, help="Optional ScriptBoard_Config.json path.")
    parser.add_argument("--output", type=Path, help="Markdown output file.")
    parser.add_argument("--json", type=Path, help="JSON output file.")
    args = parser.parse_args()
    input_dir = args.input.expanduser().resolve()
    config = load_config(args.config, base_dir=input_dir)
    md_path = (args.output or Path(config.outputs.prompts_md)).expanduser()
    json_path = (args.json or Path(config.outputs.prompts_json)).expanduser()
    if not md_path.is_absolute():
        md_path = input_dir / md_path
    if not json_path.is_absolute():
        json_path = input_dir / json_path
    build(input_dir, md_path, json_path, config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
