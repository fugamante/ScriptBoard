"""Compatibility wrapper for scriptboard.cleanup_removed."""

from scriptboard.cleanup_removed import *  # noqa: F401,F403
from scriptboard.cleanup_removed import main


if __name__ == "__main__":
    raise SystemExit(main())
