"""Run ScriptBoard's credential-free release readiness checks."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys


EXPECTED_HELP_TEXT = "ScriptBoard screenplay storyboard tools."
IGNORED_LOCAL_PATHS = (
    ".env.local",
    ".venv",
    "Storyboard_Image_Jobs.json",
    "Storyboard_Images/",
    "Storyboard_Prompt_Revisions.json",
)
PRIVATE_PATH_PARTS = (
    "The" "_Invisible_Engine",
    "Screenplay" "_Change_Log",
)
TRACKED_PRIVATE_PATH_RE = re.compile(
    rf"(^|/)({'|'.join(PRIVATE_PATH_PARTS)}|\.env(?:$|[./])|\.venv(?:$|/))"
    r"|"
    r"\.(png|jpg|jpeg|webp|gif|bmp|tif|tiff|psd|pdf|fdx)$",
    re.IGNORECASE,
)
PRIVATE_TEXT_PARTS = (
    "Johnny" "Bot",
    "Moes" "Tank",
    "/" "Users/",
    "ScriptBoard " "2",
    "The" "_Invisible_Engine",
    "Screenplay" "_Change_Log",
    "scene" "_016",
    "school" "_drop",
    "sk" "-proj-",
    r"sk-[A-Za-z0-9_-]{32,}",
    r"OPENAI_API_KEY[[:space:]]*=[[:space:]]*sk",
    "X-Amz" "-Signature",
    "AWS" "AccessKeyId",
    "signature" "=",
)
PRIVATE_TEXT_RE = "|".join(PRIVATE_TEXT_PARTS)


def release_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)
    env.pop("PYTHONPATH", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    allowed_returncodes: set[int] | None = None,
) -> subprocess.CompletedProcess[str]:
    allowed = allowed_returncodes or {0}
    result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    if result.returncode not in allowed:
        print(f"Command failed: {' '.join(command)}", file=sys.stderr)
        if result.stdout:
            print("stdout:", file=sys.stderr)
            print(result.stdout, file=sys.stderr)
        if result.stderr:
            print("stderr:", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    return result


def compile_targets(repo: Path) -> list[str]:
    targets: list[str] = []
    for pattern in (
        "scriptboard/*.py",
        "storyboard_tool/*.py",
        "scripts/install_smoke.py",
        "scripts/release_check.py",
    ):
        targets.extend(str(path) for path in sorted(repo.glob(pattern)))
    return targets


def check_help(command: list[str], *, cwd: Path, env: dict[str, str], expected_text: str = "usage:") -> None:
    result = run(command, cwd=cwd, env=env)
    if expected_text not in result.stdout:
        print(f"Help output missing expected description: {' '.join(command)}", file=sys.stderr)
        raise SystemExit(1)


def check_ignored_paths(repo: Path, env: dict[str, str]) -> None:
    for path in IGNORED_LOCAL_PATHS:
        run(["git", "check-ignore", "-q", path], cwd=repo, env=env)


def check_tracked_paths(repo: Path, env: dict[str, str]) -> None:
    result = run(["git", "ls-files"], cwd=repo, env=env)
    flagged = [path for path in result.stdout.splitlines() if TRACKED_PRIVATE_PATH_RE.search(path)]
    if flagged:
        print("Tracked private/generated paths found:", file=sys.stderr)
        for path in flagged:
            print(path, file=sys.stderr)
        raise SystemExit(1)


def check_private_text(repo: Path, env: dict[str, str]) -> None:
    result = run(
        ["git", "grep", "-I", "-n", "-E", PRIVATE_TEXT_RE, "--", "."],
        cwd=repo,
        env=env,
        allowed_returncodes={0, 1},
    )
    if result.stdout:
        print("Focused privacy scan found tracked text that needs review:", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        raise SystemExit(1)


def parse_args(argv: list[str]) -> argparse.Namespace:
    default_repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Run ScriptBoard release readiness checks.")
    parser.add_argument("--repo", type=Path, default=default_repo, help="ScriptBoard repository path.")
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used for unittest, py_compile, CLI help, and install smoke.",
    )
    parser.add_argument(
        "--skip-install-smoke",
        action="store_true",
        help="Skip the isolated normal-install smoke check.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    repo = args.repo.expanduser().resolve()
    if not (repo / "pyproject.toml").exists():
        print(f"Missing pyproject.toml at {repo}", file=sys.stderr)
        return 2

    env = release_env()
    run(["git", "diff", "--check"], cwd=repo, env=env)
    check_ignored_paths(repo, env)
    check_tracked_paths(repo, env)
    check_private_text(repo, env)
    run([args.python, "-m", "unittest"], cwd=repo, env=env)
    run([args.python, "-m", "py_compile", *compile_targets(repo)], cwd=repo, env=env)
    check_help([args.python, "-m", "scriptboard", "--help"], cwd=repo, env=env, expected_text=EXPECTED_HELP_TEXT)
    check_help([args.python, "-m", "scriptboard", "generate", "--help"], cwd=repo, env=env)
    check_help([args.python, "-m", "scriptboard", "plan", "--help"], cwd=repo, env=env)
    check_help([args.python, "-m", "scriptboard", "revisions", "--help"], cwd=repo, env=env)
    if not args.skip_install_smoke:
        run([args.python, str(repo / "scripts" / "install_smoke.py"), "--repo", str(repo), "--python", args.python], cwd=repo, env=env)

    print("release_check_ok")
    print(f"repo={repo}")
    print("checks=diff-check,ignored-paths,tracked-paths,privacy-scan,unittest,py-compile,cli-help,install-smoke")
    print("provider_calls=none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
