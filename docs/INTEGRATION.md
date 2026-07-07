# Integration Notes

ScriptBoard is intended to be developed as a standalone tool while screenplay
projects keep their own drafts and generated artifacts.

Recommended integration patterns:

- Install ScriptBoard in editable mode during active development:
  `python3 -m pip install -e /path/to/ScriptBoard`
- Keep generated storyboard files inside each screenplay project folder.
- Add project-specific `ScriptBoard_Config.json` files for title, visual style,
  board copy, safety substitutions, source priority, and artifact names.
- Keep any legacy wrapper scripts in the screenplay project as thin entrypoints
  that call the installed package or `python3 -m scriptboard`.

Do not copy private screenplay text, generated images, research notes, or story
bibles into this repository.
