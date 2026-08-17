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

For normal local CLI use, install ScriptBoard into a virtual environment from
the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

Then run:

```bash
scriptboard --help
```

A normal local install copies the package into the virtual environment. It is
the most reliable option for operator runs; reinstall after source changes:

```bash
python -m pip install --force-reinstall .
```

For active development, editable mode is still supported:

```bash
python -m pip install -e .
```

On macOS with Python 3.14, an editable install can fail with
`ModuleNotFoundError: No module named 'scriptboard'` if the virtual
environment's editable `.pth` file is marked hidden. First clear that flag:

```bash
chflags -R nohidden .venv
hash -r
scriptboard --help
```

If the editable command still fails, use the normal local install path:

```bash
python -m pip install --force-reinstall .
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

For moderation-blocked jobs, keep revised prompts in an ignored local revision
file outside this reusable repository. Review the exact job with the revision
metadata first:

```bash
scriptboard revisions scaffold --job-id <job-id> --revisions Storyboard_Prompt_Revisions.json
scriptboard revisions validate --job-id <job-id> --revisions Storyboard_Prompt_Revisions.json --strict
scriptboard plan --job-id <job-id> --retry-failed --revisions Storyboard_Prompt_Revisions.json
```

A revision is usable only when its status is `ready` and its
`source_prompt_hash` matches the current job `prompt_hash`. `revisions scaffold`
creates or updates the ignored JSON entry from the current ledger hash; pass
`--revised-prompt-file <path>` and `--status ready` only after writing a
human-reviewed prompt to a local text file. Revision helper, plan, and dry-run
output show revision status and hashes, but never print the original prompt,
revised prompt, or screenplay passage. When approved, target the exact job:

```bash
scriptboard generate --dry-run --job-id <job-id> --retry-failed --revisions Storyboard_Prompt_Revisions.json
scriptboard generate --provider openai --job-id <job-id> --retry-failed --revisions Storyboard_Prompt_Revisions.json
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
scriptboard revisions
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

Run the install smoke check:

```bash
python3 scripts/install_smoke.py
```

The smoke check creates a temporary virtual environment, installs this checkout
with the normal local install path, and verifies `scriptboard --help` plus
`python -m scriptboard --help` from outside the repository root. It removes
`OPENAI_API_KEY` and `PYTHONPATH` from the child process environment and does
not call image providers.

## Engineering Assurance

ScriptBoard uses a lightweight, combined engineering-control profile. The
project evaluates the IEEE 730, 828, 829, 830, 1016, 1012, and 1058 control
families without claiming certification or formal compliance:

- `docs/assurance/ieee-applicability.md` records the profile decision, control
  owners, acceptance evidence, freshness, and escalation triggers.
- `docs/assurance/engineering-plan.md` is the combined requirements, design,
  configuration, test/V&V, quality, and project-management plan.

Live provider use receives stricter privacy controls than the base profile.
Hosted, unattended, bulk, or multi-user operation requires reassessment before
release or use.

## Privacy Boundary

This repository should contain only reusable tooling and synthetic fixtures.
Screenplay drafts, private generated images, project research, and project
story bibles belong in the screenplay project that consumes ScriptBoard. Local
prompt revision files such as `Storyboard_Prompt_Revisions.json` are ignored
because they may contain private revised prompts.
