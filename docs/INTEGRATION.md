# Integration Notes

ScriptBoard is intended to be developed as a standalone tool while screenplay
projects keep their own drafts and generated artifacts.

Recommended integration patterns:

- Install ScriptBoard into a virtual environment for routine operator use:
  `python -m pip install /path/to/ScriptBoard`. Reinstall after source changes
  with `python -m pip install --force-reinstall /path/to/ScriptBoard`.
- Run `python /path/to/ScriptBoard/scripts/install_smoke.py` after packaging
  or setup changes to verify a temporary normal install and CLI help from
  outside the repository root.
- Use editable mode only when actively developing ScriptBoard:
  `python -m pip install -e /path/to/ScriptBoard`.
- On macOS with Python 3.14, editable installs can fail at runtime if the
  virtual environment's editable `.pth` file is marked hidden. If
  `scriptboard --help` reports a missing `scriptboard` module, run
  `chflags -R nohidden .venv`, clear the shell command cache with `hash -r`,
  and retry. If it still fails, switch back to the normal local install path.
- Keep generated storyboard files inside each screenplay project folder.
- Add project-specific `ScriptBoard_Config.json` files for title, visual style,
  board copy, safety substitutions, source priority, and artifact names.
- Use `scriptboard generate --provider openai` as the primary image-generation
  path once `OPENAI_API_KEY` is available. Use `--provider fake` for local
  validation without credentials or network access.
- Review pending image jobs with `scriptboard plan` and prefer exact
  `scriptboard generate --job-id <job-id>` runs for real provider work.
- Keep moderation-blocked prompt revisions in an ignored project-local JSON
  file, then pass it explicitly with `--revisions`. Mark an entry `ready` only
  after human review; ScriptBoard rejects draft, empty, or stale-hash entries.
- Use `scriptboard revisions scaffold --job-id <job-id> --revisions <path>` to
  create an ignored draft entry from the current ledger hash, and
  `scriptboard revisions validate --revisions <path> --strict` before retrying
  real generation.
- Treat `Storyboard_Prompt_Revisions*.json` as private operator state; it may
  contain revised prompt text and belongs outside published artifacts.
- Keep any legacy wrapper scripts in the screenplay project as thin entrypoints
  that call the installed package or `python3 -m scriptboard`.

Do not copy private screenplay text, generated images, research notes, or story
bibles into this repository.
