"""Convenience wrapper: run Part 2 from anywhere (`python scripts/verify.py`)."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from promo_parser.cli.verify import main

if __name__ == "__main__":
    main()
