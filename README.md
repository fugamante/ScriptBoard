# ScriptBoard

ScriptBoard turns screenplay drafts into storyboard prompt packs, resumable
image-job ledgers, panel catalogs, and a local HTML review board.

The current implementation supports:

- Final Draft `.fdx` draft extraction
- plain text and markdown draft inputs
- scene detection and visual beat selection
- configurable prompt style and project metadata
- resumable image-job JSON generation
- panel catalog generation with basic validation warnings
- local HTML storyboard board rendering
- optional Safari/ChatGPT image-generation inspection and fallback helpers

## Install

For local development:

```bash
python3 -m pip install -e .
```

Then run:

```bash
scriptboard --help
```

Without installation, the same CLI is available from the repository root:

```bash
python3 -m scriptboard --help
```

## Basic Workflow

From a screenplay project folder containing `Draft_*.fdx`, `Draft_*.txt`, or
similarly named scene files:

```bash
scriptboard build
scriptboard jobs
scriptboard board
```

Default outputs are written beside the source draft files:

- `Storyboard_Prompts.md`
- `Storyboard_Prompts.json`
- `Storyboard_Image_Jobs.json`
- `Storyboard_Panel_Catalog.md`
- `Storyboard_Board.html`
- `Storyboard_Images/`

## Project Configuration

ScriptBoard looks for `ScriptBoard_Config.json` in the active screenplay
project folder. If absent, generic defaults are used.

Minimal example:

```json
{
  "title": "Example Screenplay",
  "visual_style": "Use restrained live-action film stills with consistent character continuity.",
  "board": {
    "heading": "Example Screenplay\nStoryboard"
  }
}
```

Config areas:

- `title` and `visual_style` for generated prompt packs
- `board` copy, including HTML title, sidebar brand, heading, intro, and
  annotation placeholder
- `safety.replacements` and `safety.notes` for project-specific prompt-safety
  rewrites
- `sources` for input extensions, filename matching, and source-format priority
- `outputs` for prompt, job, catalog, board, image-folder, and erased-panel
  filenames

## Commands

```bash
scriptboard build
scriptboard jobs
scriptboard board
scriptboard cleanup
scriptboard inspect-visible-images
```

`inspect-visible-images` depends on a local Safari session and is intended as an
optional bridge for workflows that use ChatGPT image generation manually.

## Development

Run tests:

```bash
python3 -m unittest
```

Run a syntax check:

```bash
python3 -m py_compile scriptboard/*.py storyboard_tool/*.py
```

## Privacy Boundary

This repository should contain only reusable tooling and synthetic fixtures.
Screenplay drafts, private generated images, project research, and project
story bibles belong in the screenplay project that consumes ScriptBoard.
