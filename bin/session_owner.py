#!/usr/bin/env python3
"""Command launcher for tmux session ownership and SSH agent aliases."""
from pathlib import Path
import sys

sys.dont_write_bytecode = True
CHECKOUT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CHECKOUT))

from dalftui.linux.session_owner import main


if __name__ == '__main__':
    raise SystemExit(main())
