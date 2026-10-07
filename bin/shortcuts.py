#!/usr/bin/env -S uv run --no-project --python >=3.11
"""Command launcher for the dalftui shortcut guide."""
from pathlib import Path
import sys

sys.dont_write_bytecode = True
CHECKOUT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CHECKOUT))

from dalftui.linux.shortcuts import main


if __name__ == "__main__":
    main()
