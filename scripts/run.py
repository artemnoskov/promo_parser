"""Convenience wrapper: run Part 1 from anywhere (`python scripts/run.py`)."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from promo_parser.cli.run import main

if __name__ == "__main__":
    main()
