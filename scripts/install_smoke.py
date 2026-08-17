"""Validate ScriptBoard installation in a temporary virtual environment."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def console_script(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "scriptboard.exe"
    return venv_dir / "bin" / "scriptboard"


def smoke_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)
    env.pop("PYTHONPATH", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run(command: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    if result.returncode:
        print(f"Command failed: {' '.join(command)}", file=sys.stderr)
        if result.stdout:
            print("stdout:", file=sys.stderr)
            print(result.stdout, file=sys.stderr)
        if result.stderr:
            print("stderr:", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    return result


def parse_args(argv: list[str]) -> argparse.Namespace:
    default_repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Install ScriptBoard into an isolated venv and verify CLI entrypoints.",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=default_repo,
        help="ScriptBoard repository path to install. Defaults to this checkout.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used to create the temporary virtual environment.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    repo = args.repo.expanduser().resolve()
    pyproject = repo / "pyproject.toml"
    if not pyproject.exists():
        print(f"Missing pyproject.toml at {pyproject}", file=sys.stderr)
        return 2

    env = smoke_env()
    with tempfile.TemporaryDirectory(prefix="scriptboard-install-smoke-") as tmp:
        tmp_dir = Path(tmp)
        venv_dir = tmp_dir / "venv"
        outside_repo = tmp_dir / "outside-repo"
        outside_repo.mkdir()

        run([args.python, "-m", "venv", str(venv_dir)], cwd=tmp_dir, env=env)
        py = venv_python(venv_dir)
        scriptboard = console_script(venv_dir)

        run([str(py), "-m", "pip", "install", str(repo)], cwd=outside_repo, env=env)
        console_help = run([str(scriptboard), "--help"], cwd=outside_repo, env=env)
        module_help = run([str(py), "-m", "scriptboard", "--help"], cwd=outside_repo, env=env)

    if "ScriptBoard screenplay storyboard tools." not in console_help.stdout:
        print("Console entrypoint help did not include the expected description.", file=sys.stderr)
        return 1
    if "ScriptBoard screenplay storyboard tools." not in module_help.stdout:
        print("python -m scriptboard help did not include the expected description.", file=sys.stderr)
        return 1

    print("install_smoke_ok")
    print(f"python={args.python}")
    print("entrypoints=scriptboard,python -m scriptboard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
