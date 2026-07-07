#!/usr/bin/env python3
"""Remove erased storyboard panels from jobs and image resources."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

from scriptboard.config import load_config


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_removed(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        item["job_id"]: item
        for item in data.get("erased_panels", [])
        if item.get("job_id")
    }


def image_paths(jobs: list[dict]) -> set[Path]:
    return {
        Path(job["image_path"]).resolve()
        for job in jobs
        if job.get("image_path")
    }


def cleanup(jobs_path: Path, removed_path: Path, images_dir: Path) -> dict:
    payload = json.loads(jobs_path.read_text(encoding="utf-8"))
    removed = load_removed(removed_path)
    before_jobs = payload.get("jobs", [])
    kept_jobs = [job for job in before_jobs if job.get("id") not in removed]
    removed_jobs = [job for job in before_jobs if job.get("id") in removed]

    referenced_after = image_paths(kept_jobs)
    deleted: list[str] = []
    retained_referenced_duplicates: list[str] = []
    removed_hashes: set[str] = set()

    for job in removed_jobs:
        image_path = Path(job.get("image_path", "")).resolve()
        if image_path.exists():
            removed_hashes.add(file_hash(image_path))
            image_path.unlink()
            deleted.append(str(image_path))

    if removed_hashes and images_dir.exists():
        for candidate in images_dir.rglob("*.png"):
            candidate = candidate.resolve()
            if "annotation_revision_backups" in candidate.parts:
                continue
            if not candidate.exists():
                continue
            if file_hash(candidate) not in removed_hashes:
                continue
            if candidate in referenced_after:
                retained_referenced_duplicates.append(str(candidate))
                continue
            candidate.unlink()
            deleted.append(str(candidate))

    payload["jobs"] = kept_jobs
    payload["summary"] = {
        "total": len(kept_jobs),
        "pending": sum(1 for job in kept_jobs if job.get("status") != "done"),
        "done": sum(1 for job in kept_jobs if job.get("status") == "done"),
    }
    payload["generated_at"] = datetime.now().isoformat(timespec="seconds")
    jobs_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        "removed_jobs": [job.get("id") for job in removed_jobs],
        "deleted_files": deleted,
        "retained_referenced_duplicates": retained_referenced_duplicates,
        "summary": payload["summary"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Optional ScriptBoard_Config.json path.")
    parser.add_argument("--jobs", type=Path)
    parser.add_argument("--removed", type=Path)
    parser.add_argument("--images-dir", type=Path)
    args = parser.parse_args()

    cwd = Path.cwd()
    config = load_config(args.config, base_dir=cwd)
    jobs_path = (args.jobs or Path(config.outputs.image_jobs)).expanduser()
    removed_path = (args.removed or Path(config.outputs.erased_panels)).expanduser()
    images_dir = (args.images_dir or Path(config.outputs.images_dir)).expanduser()
    if not jobs_path.is_absolute():
        jobs_path = cwd / jobs_path
    if not removed_path.is_absolute():
        removed_path = cwd / removed_path
    if not images_dir.is_absolute():
        images_dir = cwd / images_dir

    result = cleanup(jobs_path, removed_path, images_dir)
    print(json.dumps(result, indent=2, ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
