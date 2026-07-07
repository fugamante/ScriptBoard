"""Compatibility wrapper for scriptboard.builder."""

from scriptboard.builder import *  # noqa: F401,F403
from scriptboard.builder import main


if __name__ == "__main__":
    raise SystemExit(main())
