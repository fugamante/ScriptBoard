"""Compatibility wrapper for scriptboard.board."""

from scriptboard.board import *  # noqa: F401,F403
from scriptboard.board import main


if __name__ == "__main__":
    raise SystemExit(main())
