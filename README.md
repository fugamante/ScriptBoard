# ScriptBoard

ScriptBoard turns screenplay drafts into storyboard prompt packs, resumable
image-job ledgers, panel catalogs, and a local HTML review board.

The current implementation supports:

- Final Draft `.fdx` draft extraction
- plain text and markdown draft inputs
- scene detection and visual beat selection
- configurable prompt style and project metadata
- resumable image-job JSON generation
- provider-neutral image generation with OpenAI Image API support
- panel catalog generation with basic validation warnings
- local HTML storyboard board rendering
- optional Safari/ChatGPT inspection and legacy fallback helpers

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
scriptboard plan --limit 5
scriptboard generate --provider openai --limit 1
scriptboard board
```

Default outputs are written beside the source draft files:

- `Storyboard_Prompts.md`
- `Storyboard_Prompts.json`
- `Storyboard_Image_Jobs.json`
- `Storyboard_Panel_Catalog.md`
- `Storyboard_Board.html`
- `Storyboard_Images/`

`scriptboard generate` reads `Storyboard_Image_Jobs.json`, generates pending
jobs through the selected provider, writes local image files, and records
provider metadata plus a SHA-256 checksum in the job ledger. The default
provider is `openai` and reads credentials from `OPENAI_API_KEY`; no API key is
written to repository files. Use `--provider fake` for deterministic local tests
without network access or credentials.

Review pending jobs before a real run:

```bash
scriptboard plan --limit 5
```

After reviewing the non-sensitive job metadata, target one exact job. Use
`generate --dry-run` to verify the mutating command's selection without writing
the ledger or image files:

```bash
scriptboard generate --dry-run --job-id <job-id>
scriptboard generate --provider openai --job-id <job-id>
```

Failed jobs are hidden from the default pending review. Inspect them explicitly
and retry only when intended:

```bash
scriptboard plan --status failed
scriptboard generate --job-id <job-id> --retry-failed
```

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
scriptboard plan
scriptboard generate
scriptboard board
scriptboard cleanup
scriptboard inspect-visible-images
```

`generate` is the primary provider-backed image path. `inspect-visible-images`
depends on a local Safari session and is retained only as an optional legacy
bridge for workflows that use ChatGPT image generation manually.

See `docs/IMAGE_PROVIDERS.md` for the provider contract, durable job metadata
schema, OpenAI API path, fake-provider test path, and future provider lanes.

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
