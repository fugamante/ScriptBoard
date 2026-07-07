"""Compatibility wrapper for scriptboard.safari_generate."""

from scriptboard.safari_generate import *  # noqa: F401,F403
from scriptboard.safari_generate import main


if __name__ == "__main__":
    raise SystemExit(main())
