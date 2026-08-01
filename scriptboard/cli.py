"""Command-line entrypoint for ScriptBoard."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from scriptboard import board, builder, cleanup_removed, image_jobs, image_providers, safari_generate
from scriptboard.config import load_config


def resolve_path(value: Path, base: Path) -> Path:
    value = value.expanduser()
    return value if value.is_absolute() else base / value


def add_config_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, help="Optional ScriptBoard_Config.json path.")


def resolve_optional_path(value: Path | None, base: Path) -> Path | None:
    return resolve_path(value, base) if value else None


def run_build(args: argparse.Namespace) -> int:
    input_dir = args.input.expanduser().resolve()
    config = load_config(args.config, base_dir=input_dir)
    md_path = resolve_path(args.output or Path(config.outputs.prompts_md), input_dir)
    json_path = resolve_path(args.json or Path(config.outputs.prompts_json), input_dir)
    builder.build(input_dir, md_path, json_path, config)
    return 0


def run_jobs(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    config = load_config(args.config, base_dir=cwd)
    prompts_path = resolve_path(args.prompts or Path(config.outputs.prompts_json), cwd)
    images_dir = resolve_path(args.images_dir or Path(config.outputs.images_dir), cwd)
    jobs_path = resolve_path(args.jobs or Path(config.outputs.image_jobs), cwd)
    removed_path = resolve_path(args.removed or Path(config.outputs.erased_panels), cwd)
    board_path = resolve_path(args.board or Path(config.outputs.board_html), jobs_path.parent)
    catalog_path = resolve_path(args.catalog or Path(config.outputs.panel_catalog), jobs_path.parent)

    payload = image_jobs.build_jobs(prompts_path, images_dir, jobs_path, removed_path)
    jobs_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"Wrote {jobs_path} ({payload['summary']['pending']} pending, {payload['summary']['done']} done)",
        file=sys.stderr,
    )
    image_jobs.build_catalog(payload, catalog_path)
    print(f"Wrote {catalog_path}", file=sys.stderr)
    if not args.no_board:
        board.build(jobs_path, board_path, config)
    return 0


def run_board(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    config = load_config(args.config, base_dir=cwd)
    jobs_path = resolve_path(args.jobs or Path(config.outputs.image_jobs), cwd)
    output_path = resolve_path(args.output or Path(config.outputs.board_html), jobs_path.parent)
    if args.config is None:
        config = load_config(None, base_dir=jobs_path.parent)
    board.build(jobs_path, output_path, config)
    return 0


def run_cleanup(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    config = load_config(args.config, base_dir=cwd)
    jobs_path = resolve_path(args.jobs or Path(config.outputs.image_jobs), cwd)
    removed_path = resolve_path(args.removed or Path(config.outputs.erased_panels), cwd)
    images_dir = resolve_path(args.images_dir or Path(config.outputs.images_dir), cwd)
    result = cleanup_removed.cleanup(jobs_path, removed_path, images_dir)
    print(json.dumps(result, indent=2, ensure_ascii=False), file=sys.stderr)
    return 0


def run_generate(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    config = load_config(args.config, base_dir=cwd)
    jobs_path = resolve_path(args.jobs or Path(config.outputs.image_jobs), cwd)
    revisions_path = resolve_optional_path(args.revisions, cwd)
    prompt_revisions = image_providers.load_prompt_revisions(revisions_path)
    if args.dry_run:
        raw = image_providers.load_ledger(jobs_path)
        result = image_providers.generation_plan(
            raw,
            limit=args.limit,
            retry_failed=args.retry_failed,
            job_id=args.job_id,
            prompt_revisions=prompt_revisions,
        )
        result["provider"] = args.provider
        print(json.dumps(result, indent=2, ensure_ascii=False), file=sys.stderr)
        return 0

    provider = image_providers.make_provider(
        args.provider,
        model=args.model,
        size=args.size,
        quality=args.quality,
        output_format=args.output_format,
    )
    result = image_providers.run_provider_generation(
        jobs_path,
        provider,
        limit=args.limit,
        retry_failed=args.retry_failed,
        stop_on_error=args.stop_on_error,
        job_id=args.job_id,
        prompt_revisions=prompt_revisions,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False), file=sys.stderr)
    return 0


def run_plan(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    config = load_config(args.config, base_dir=cwd)
    jobs_path = resolve_path(args.jobs or Path(config.outputs.image_jobs), cwd)
    revisions_path = resolve_optional_path(args.revisions, cwd)
    prompt_revisions = image_providers.load_prompt_revisions(revisions_path)
    raw = image_providers.load_ledger(jobs_path)
    result = image_providers.review_plan(
        raw,
        limit=args.limit,
        status=args.status,
        job_id=args.job_id,
        retry_failed=args.retry_failed,
        prompt_revisions=prompt_revisions,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False), file=sys.stderr)
    return 0


def read_revised_prompt(args: argparse.Namespace, cwd: Path) -> str | None:
    if not args.revised_prompt_file:
        return None
    prompt_path = resolve_path(args.revised_prompt_file, cwd)
    return prompt_path.read_text(encoding="utf-8")


def run_revisions_scaffold(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    config = load_config(args.config, base_dir=cwd)
    jobs_path = resolve_path(args.jobs or Path(config.outputs.image_jobs), cwd)
    revisions_path = resolve_path(args.revisions, cwd)
    result = image_providers.scaffold_prompt_revision(
        jobs_path,
        revisions_path,
        job_id=args.job_id,
        status=args.status,
        revised_prompt=read_revised_prompt(args, cwd),
        replace=args.replace,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False), file=sys.stderr)
    return 0


def run_revisions_validate(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    config = load_config(args.config, base_dir=cwd)
    jobs_path = resolve_path(args.jobs or Path(config.outputs.image_jobs), cwd)
    revisions_path = resolve_path(args.revisions, cwd)
    result = image_providers.validate_prompt_revision_file(
        jobs_path,
        revisions_path,
        job_id=args.job_id,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False), file=sys.stderr)
    return 1 if args.strict and result["summary"]["blocked"] else 0


def run_inspect_visible_images(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    config = load_config(args.config, base_dir=cwd)
    jobs_path = resolve_path(args.jobs or Path(config.outputs.image_jobs), cwd)
    return safari_generate.inspect_visible_images(args.chatgpt_url, jobs_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scriptboard", description="ScriptBoard screenplay storyboard tools.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Build storyboard prompts from screenplay drafts.")
    add_config_arg(build_parser)
    build_parser.add_argument("--input", type=Path, default=Path.cwd(), help="Folder containing screenplay drafts.")
    build_parser.add_argument("--output", type=Path, help="Markdown output file.")
    build_parser.add_argument("--json", type=Path, help="JSON output file.")
    build_parser.set_defaults(func=run_build)

    jobs_parser = subparsers.add_parser("jobs", help="Build image jobs, panel catalog, and optionally the board.")
    add_config_arg(jobs_parser)
    jobs_parser.add_argument("--prompts", type=Path)
    jobs_parser.add_argument("--images-dir", type=Path)
    jobs_parser.add_argument("--jobs", type=Path)
    jobs_parser.add_argument("--catalog", type=Path)
    jobs_parser.add_argument("--board", type=Path)
    jobs_parser.add_argument("--removed", type=Path)
    jobs_parser.add_argument("--no-board", action="store_true", help="Skip rebuilding the local storyboard board HTML.")
    jobs_parser.set_defaults(func=run_jobs)

    board_parser = subparsers.add_parser("board", help="Build the local storyboard board HTML.")
    add_config_arg(board_parser)
    board_parser.add_argument("--jobs", type=Path)
    board_parser.add_argument("--output", type=Path)
    board_parser.set_defaults(func=run_board)

    cleanup_parser = subparsers.add_parser("cleanup", help="Apply erased-panel cleanup to jobs and images.")
    add_config_arg(cleanup_parser)
    cleanup_parser.add_argument("--jobs", type=Path)
    cleanup_parser.add_argument("--removed", type=Path)
    cleanup_parser.add_argument("--images-dir", type=Path)
    cleanup_parser.set_defaults(func=run_cleanup)

    plan_parser = subparsers.add_parser(
        "plan",
        help="Review sanitized storyboard image jobs before generation.",
    )
    add_config_arg(plan_parser)
    plan_parser.add_argument("--jobs", type=Path, help="Storyboard image-job ledger path.")
    plan_parser.add_argument("--limit", type=int, default=10, help="Maximum jobs to show.")
    plan_parser.add_argument("--status", choices=["pending", "failed", "all"], default="pending")
    plan_parser.add_argument("--job-id", help="Review one exact job ID regardless of status filter.")
    plan_parser.add_argument("--retry-failed", action="store_true", help="Show failed jobs as selectable for retry.")
    plan_parser.add_argument("--revisions", type=Path, help="Ignored local prompt revision JSON path.")
    plan_parser.set_defaults(func=run_plan)

    revisions_parser = subparsers.add_parser(
        "revisions",
        help="Scaffold and validate ignored local prompt revision files.",
    )
    revisions_subparsers = revisions_parser.add_subparsers(dest="revision_command", required=True)

    revisions_scaffold_parser = revisions_subparsers.add_parser(
        "scaffold",
        help="Create or update one local prompt revision entry without printing prompt text.",
    )
    add_config_arg(revisions_scaffold_parser)
    revisions_scaffold_parser.add_argument("--jobs", type=Path, help="Storyboard image-job ledger path.")
    revisions_scaffold_parser.add_argument(
        "--revisions",
        type=Path,
        required=True,
        help="Ignored local revision JSON path.",
    )
    revisions_scaffold_parser.add_argument("--job-id", required=True, help="Exact job ID to scaffold.")
    revisions_scaffold_parser.add_argument("--status", choices=["draft", "ready"], help="Revision status to write.")
    revisions_scaffold_parser.add_argument(
        "--revised-prompt-file",
        type=Path,
        help="Local text file containing the revised prompt. Contents are written but never printed.",
    )
    revisions_scaffold_parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace an existing entry for the job ID.",
    )
    revisions_scaffold_parser.set_defaults(func=run_revisions_scaffold)

    revisions_validate_parser = revisions_subparsers.add_parser(
        "validate",
        help="Validate a local prompt revision file against the current job ledger.",
    )
    add_config_arg(revisions_validate_parser)
    revisions_validate_parser.add_argument("--jobs", type=Path, help="Storyboard image-job ledger path.")
    revisions_validate_parser.add_argument(
        "--revisions",
        type=Path,
        required=True,
        help="Ignored local revision JSON path.",
    )
    revisions_validate_parser.add_argument("--job-id", help="Validate one exact revision entry.")
    revisions_validate_parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 when any selected revision is blocked.",
    )
    revisions_validate_parser.set_defaults(func=run_revisions_validate)

    generate_parser = subparsers.add_parser(
        "generate",
        help="Generate pending storyboard images through a provider backend.",
    )
    add_config_arg(generate_parser)
    generate_parser.add_argument("--jobs", type=Path, help="Storyboard image-job ledger path.")
    generate_parser.add_argument("--provider", choices=["openai", "fake"], default="openai")
    generate_parser.add_argument("--model", help="Provider model override.")
    generate_parser.add_argument("--size", default=image_providers.DEFAULT_OPENAI_IMAGE_SIZE)
    generate_parser.add_argument("--quality", default=image_providers.DEFAULT_OPENAI_IMAGE_QUALITY)
    generate_parser.add_argument("--output-format", default=image_providers.DEFAULT_OPENAI_IMAGE_FORMAT)
    generate_parser.add_argument("--limit", type=int, default=1, help="Maximum jobs to generate in this run.")
    generate_parser.add_argument("--job-id", help="Generate or preview one exact job ID.")
    generate_parser.add_argument("--dry-run", action="store_true", help="Preview selected jobs without writing files.")
    generate_parser.add_argument("--retry-failed", action="store_true", help="Retry failed jobs before pending jobs.")
    generate_parser.add_argument("--revisions", type=Path, help="Ignored local prompt revision JSON path.")
    generate_parser.add_argument("--stop-on-error", action="store_true", help="Exit on the first provider failure.")
    generate_parser.set_defaults(func=run_generate)

    inspect_parser = subparsers.add_parser(
        "inspect-visible-images",
        help="Inspect visible ChatGPT estuary images against the local job ledger.",
    )
    add_config_arg(inspect_parser)
    inspect_parser.add_argument("--jobs", type=Path, help="Storyboard image-job ledger path.")
    inspect_parser.add_argument("--chatgpt-url", default=safari_generate.DEFAULT_CHATGPT_URL)
    inspect_parser.set_defaults(func=run_inspect_visible_images)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
