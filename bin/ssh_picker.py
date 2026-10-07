#!/usr/bin/env -S uv run --no-project --python >=3.11
"""Command launcher for SSH host selection and connections."""
from pathlib import Path
import sys

sys.dont_write_bytecode = True
CHECKOUT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CHECKOUT))

from dalftui.ssh import main


if __name__ == '__main__':
    raise SystemExit(main())
