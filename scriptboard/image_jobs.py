#!/usr/bin/env python3
"""Build resumable storyboard image jobs from Storyboard_Prompts.json."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from scriptboard.board import build as build_board
from scriptboard.config import load_config


def slug(value: str, limit: int = 56) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return value[:limit].strip("_") or "untitled"


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def normalize_passage(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def is_weak_passage(value: str) -> bool:
    normalized = normalize_passage(value)
    if not normalized:
        return True
    if re.fullmatch(r"[A-Z][A-Z0-9 '\-.]{1,34}(?:\s*\([A-Z0-9 '\-.]+\))?", normalized):
        return True
    if re.fullmatch(r"\([A-Za-z0-9 '\-.]+\)", normalized):
        return True
    return False


def job_is_done(job: dict) -> bool:
    image_path = Path(str(job.get("image_path") or ""))
    return job.get("status") == "done" and image_path.exists()


def read_existing(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {job["id"]: job for job in data.get("jobs", [])}


def read_removed(path: Path) -> set[str]:
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        item["job_id"]
        for item in data.get("erased_panels", [])
        if item.get("job_id")
    }


def build_jobs(prompts_path: Path, images_dir: Path, jobs_path: Path, removed_path: Path | None = None) -> dict:
    prompts = json.loads(prompts_path.read_text(encoding="utf-8"))
    existing = read_existing(jobs_path)
    removed = read_removed(removed_path) if removed_path else set()
    jobs = []
    images_dir.mkdir(parents=True, exist_ok=True)

    for scene_index, pack in enumerate(prompts.get("prompt_packs", []), start=1):
        scene_id = pack.get("id") or f"scene_{scene_index:03d}_{slug(pack.get('title', 'scene'))}"
        scene_dir = images_dir / scene_id
        scene_dir.mkdir(parents=True, exist_ok=True)
        for panel_index, frame in enumerate(pack.get("frames", []), start=1):
            frame_id = frame.get("id") or f"{scene_id}_panel_{panel_index:03d}_{prompt_hash(frame['prompt'])[:10]}"
            if frame_id in removed:
                continue
            filename = f"panel_{panel_index:03d}_{slug(frame.get('label', 'panel'), 24)}.png"
            image_path = scene_dir / filename
            old = existing.get(frame_id, {})
            current_hash = prompt_hash(frame["prompt"])
            status = old.get("status", "pending")
            if image_path.exists():
                status = "done"
            elif old.get("prompt_hash") != current_hash:
                status = "pending"
            jobs.append(
                {
                    "id": frame_id,
                    "status": status,
                    "scene_id": scene_id,
                    "scene_title": pack.get("title", ""),
                    "panel_index": panel_index,
                    "panel_label": frame.get("label", ""),
                    "script_passage": frame.get("script_passage", ""),
                    "prompt": frame["prompt"],
                    "prompt_hash": current_hash,
                    "image_path": str(image_path),
                    "updated_at": old.get("updated_at"),
                    "notes": old.get("notes", ""),
                }
            )

    pending = sum(1 for job in jobs if job["status"] != "done")
    done = sum(1 for job in jobs if job["status"] == "done")
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": str(prompts_path),
        "images_dir": str(images_dir),
        "summary": {"total": len(jobs), "pending": pending, "done": done},
        "jobs": jobs,
    }


def catalog_warnings(jobs: list[dict]) -> dict[str, list[str]]:
    passages = [normalize_passage(str(job.get("script_passage") or "")) for job in jobs]
    counts = Counter(passage for passage in passages if passage)
    warnings: dict[str, list[str]] = {}
    for job in jobs:
        job_id = str(job.get("id") or "")
        passage = normalize_passage(str(job.get("script_passage") or ""))
        items: list[str] = []
        if counts.get(passage, 0) > 1:
            items.append("duplicate script segment")
        if is_weak_passage(passage):
            items.append("weak visual basis")
        if job.get("status") == "done" and not Path(str(job.get("image_path") or "")).exists():
            items.append("marked done but image file is missing")
        if items:
            warnings[job_id] = items
    return warnings


def build_catalog(payload: dict, catalog_path: Path) -> str:
    jobs = list(payload.get("jobs", []))
    warnings = catalog_warnings(jobs)
    total = len(jobs)
    done = sum(1 for job in jobs if job_is_done(job))
    pending = total - done
    duplicate_count = sum(1 for items in warnings.values() if "duplicate script segment" in items)
    weak_count = sum(1 for items in warnings.values() if "weak visual basis" in items)
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# Storyboard Panel Catalog",
        "",
        f"Generated: {generated}",
        "",
        "## Summary",
        "",
        f"- Total panels: {total}",
        f"- Generated and assigned: {done}",
        f"- Pending image generation: {pending}",
        f"- Duplicate script-segment warnings: {duplicate_count}",
        f"- Weak visual-basis warnings: {weak_count}",
        "",
        "## Validation Rules",
        "",
        "- Every panel must carry the exact screenplay segment used as the prompt basis.",
        "- A generated panel is assigned only when its job is `done` and its image file exists.",
        "- Duplicate script segments and cue-only script segments are flagged for review.",
        "",
        "## Panel Assignments",
        "",
    ]
    current_scene = ""
    for job in jobs:
        scene_id = str(job.get("scene_id") or "")
        scene_title = str(job.get("scene_title") or scene_id)
        if scene_id != current_scene:
            current_scene = scene_id
            lines.extend([f"### {scene_title}", ""])
        panel_index = int(job.get("panel_index") or 0)
        label = str(job.get("panel_label") or f"Panel {panel_index}")
        status = "generated" if job_is_done(job) else "pending"
        image_path = str(job.get("output_path") or job.get("image_path") or "")
        script_passage = str(job.get("script_passage") or "").strip()
        job_warnings = warnings.get(str(job.get("id") or ""), [])
        lines.extend(
            [
                f"#### Panel {panel_index:03d}: {label}",
                "",
                f"- Status: {status}",
                f"- Job ID: `{job.get('id', '')}`",
                f"- Image path: `{image_path}`" if image_path else "- Image path: pending",
                f"- Warnings: {', '.join(job_warnings)}" if job_warnings else "- Warnings: none",
                "- Script segment:",
                "",
                "```text",
                script_passage,
                "```",
                "",
            ]
        )
    catalog_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return str(catalog_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Optional ScriptBoard_Config.json path.")
    parser.add_argument("--prompts", type=Path)
    parser.add_argument("--images-dir", type=Path)
    parser.add_argument("--jobs", type=Path)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--board", type=Path)
    parser.add_argument("--removed", type=Path)
    parser.add_argument("--no-board", action="store_true", help="Skip rebuilding the local storyboard board HTML.")
    args = parser.parse_args()

    cwd = Path.cwd()
    config = load_config(args.config, base_dir=cwd)
    prompts_path = (args.prompts or Path(config.outputs.prompts_json)).expanduser()
    images_dir = (args.images_dir or Path(config.outputs.images_dir)).expanduser()
    jobs_path = (args.jobs or Path(config.outputs.image_jobs)).expanduser()
    if not prompts_path.is_absolute():
        prompts_path = cwd / prompts_path
    if not images_dir.is_absolute():
        images_dir = cwd / images_dir
    if not jobs_path.is_absolute():
        jobs_path = cwd / jobs_path
    removed_path = (args.removed or Path(config.outputs.erased_panels)).expanduser()
    if not removed_path.is_absolute():
        removed_path = cwd / removed_path
    board_path = (args.board or Path(config.outputs.board_html)).expanduser()
    if not board_path.is_absolute():
        board_path = jobs_path.parent / board_path
    catalog_path = (args.catalog or Path(config.outputs.panel_catalog)).expanduser()
    if not catalog_path.is_absolute():
        catalog_path = jobs_path.parent / catalog_path

    payload = build_jobs(prompts_path, images_dir, jobs_path, removed_path)
    jobs_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"Wrote {jobs_path} ({payload['summary']['pending']} pending, {payload['summary']['done']} done)",
        file=sys.stderr,
    )
    build_catalog(payload, catalog_path)
    print(f"Wrote {catalog_path}", file=sys.stderr)
    if not args.no_board:
        build_board(jobs_path, board_path, config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
