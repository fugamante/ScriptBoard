"""Compatibility wrapper for scriptboard.image_jobs."""

from scriptboard.image_jobs import *  # noqa: F401,F403
from scriptboard.image_jobs import main


if __name__ == "__main__":
    raise SystemExit(main())
