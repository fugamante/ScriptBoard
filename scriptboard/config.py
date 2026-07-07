"""Project configuration for ScriptBoard."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


CONFIG_NAME = "ScriptBoard_Config.json"

DEFAULT_TITLE = "Untitled Screenplay"
DEFAULT_STYLE = (
    "Visual continuity guardrail: keep every panel in the same restrained live-action "
    "film style, with a consistent 35mm documentary-drama look, naturalistic camera "
    "height, practical-location lighting, muted natural color grade, realistic human "
    "proportions, and emotionally specific faces. Maintain recurring character "
    "continuity across panels: consistent apparent age, facial structure, hair, and "
    "wardrobe logic unless this exact script passage visibly changes them. Avoid "
    "painterly, comic-book, anime, fantasy, glossy advertising, 3D render, or heavily "
    "stylized looks. Format guardrail: use the same horizontal 3:2 landscape "
    "storyboard frame for every panel, matching a 1536x1024 composition; do not use "
    "portrait, square, poster, collage, split-screen, or vertical framing. No text overlays"
)
DEFAULT_BOARD_INTRO = (
    "Ordered from the current storyboard image jobs. Generated panels appear as "
    "production frames; pending panels remain in place so the full screenplay "
    "sequence stays visible."
)
DEFAULT_ANNOTATION_PLACEHOLDER = "Example: keep wardrobe continuity, but make the key prop clearly visible."
DEFAULT_SAFETY_REPLACEMENTS: list[dict[str, str]] = []
DEFAULT_SAFETY_NOTES: list[dict[str, str]] = []


@dataclass
class SourceConfig:
    extensions: list[str] = field(default_factory=lambda: [".fdx", ".txt", ".md"])
    stem_prefixes: list[str] = field(default_factory=lambda: ["Draft"])
    stem_contains: list[str] = field(default_factory=lambda: ["Scene"])
    priority: list[str] = field(default_factory=lambda: [".fdx", ".txt", ".md"])


@dataclass
class OutputConfig:
    prompts_md: str = "Storyboard_Prompts.md"
    prompts_json: str = "Storyboard_Prompts.json"
    image_jobs: str = "Storyboard_Image_Jobs.json"
    panel_catalog: str = "Storyboard_Panel_Catalog.md"
    board_html: str = "Storyboard_Board.html"
    images_dir: str = "Storyboard_Images"
    erased_panels: str = "Storyboard_Erased_Panels.json"


@dataclass
class BoardConfig:
    html_title: str = "Storyboard Board"
    brand: str = "Storyboard Board"
    heading: str = "Untitled Screenplay\nStoryboard"
    intro: str = DEFAULT_BOARD_INTRO
    annotation_placeholder: str = DEFAULT_ANNOTATION_PLACEHOLDER


@dataclass
class SafetyConfig:
    replacements: list[dict[str, str]] = field(default_factory=lambda: deepcopy(DEFAULT_SAFETY_REPLACEMENTS))
    notes: list[dict[str, str]] = field(default_factory=lambda: deepcopy(DEFAULT_SAFETY_NOTES))


@dataclass
class ScriptBoardConfig:
    title: str = DEFAULT_TITLE
    visual_style: str = DEFAULT_STYLE
    source_policy: str = "draft_screenplay_only"
    sources: SourceConfig = field(default_factory=SourceConfig)
    outputs: OutputConfig = field(default_factory=OutputConfig)
    board: BoardConfig = field(default_factory=BoardConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)


def _merge_dataclass(instance: Any, values: dict[str, Any]) -> None:
    for key, value in values.items():
        if not hasattr(instance, key):
            continue
        current = getattr(instance, key)
        if hasattr(current, "__dataclass_fields__") and isinstance(value, dict):
            _merge_dataclass(current, value)
        else:
            setattr(instance, key, value)


def _normalize_config(config: ScriptBoardConfig) -> None:
    config.board.heading = config.board.heading.replace("\\n", "\n")


def load_config(path: Path | None = None, *, base_dir: Path | None = None) -> ScriptBoardConfig:
    config = ScriptBoardConfig()
    config_path = path
    if config_path is None and base_dir is not None:
        candidate = base_dir / CONFIG_NAME
        config_path = candidate if candidate.exists() else None
    if config_path is None:
        _normalize_config(config)
        return config
    config_path = config_path.expanduser()
    if not config_path.exists():
        raise FileNotFoundError(f"ScriptBoard config does not exist: {config_path}")
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"ScriptBoard config must be a JSON object: {config_path}")
    _merge_dataclass(config, data)
    _normalize_config(config)
    return config


def regex_flags(value: str | None) -> int:
    flags = 0
    if not value:
        return flags
    if "i" in value.lower():
        flags |= re.IGNORECASE
    return flags
