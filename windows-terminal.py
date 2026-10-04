#!/usr/bin/env python3
"""Compatibility launcher for Windows Terminal configuration."""
from pathlib import Path
import sys

sys.dont_write_bytecode = True
CHECKOUT = Path(__file__).resolve().parent
sys.path.insert(0, str(CHECKOUT))

from dalftui.windows.terminal_settings import main


if __name__ == '__main__':
    raise SystemExit(main())
