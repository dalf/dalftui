#!/usr/bin/env python3
"""A readable shortcut guide, followed by the current Alacritty/tmux bindings."""
import argparse
import os
import shlex
import shutil
import subprocess
import sys
import textwrap

sys.dont_write_bytecode = True
from alacritty_config import config_path, load

RESET = "\033[0m"
WHITE = "\033[1;97m"
KEY = "\033[38;2;137;221;255m"
TEXT = "\033[38;2;229;231;235m"
MUTED = "\033[38;2;166;173;200m"


def render(tmux_only=False):
    width = max(24, shutil.get_terminal_size((100, 30)).columns - 4)
    lines = []

    def paragraph(value, color=TEXT):
        lines.extend("  " + color + part + RESET for part in textwrap.wrap(value, width))

    def heading(value):
        lines.extend(["", "  " + WHITE + value.upper() + RESET,
                      "  " + MUTED + "─" * min(width, 76) + RESET])

    def row(key, description):
        if width >= 70 and len(key) <= 33:
            parts = textwrap.wrap(description, width - 36) or [""]
            lines.append("  " + KEY + key.ljust(36) + TEXT + parts[0] + RESET)
            lines.extend("  " + " " * 36 + TEXT + part + RESET for part in parts[1:])
        else:
            paragraph(key, KEY)
            lines.extend("    " + TEXT + part + RESET
                         for part in textwrap.wrap(description, width - 2))

    heading("Keyboard shortcuts")
    intro = ("Ctrl+B then F1 opens this guide. These tmux keys work over SSH." if tmux_only
             else "Ctrl+B then F1 opens this guide. Win means the Windows/Super key.")
    paragraph(intro, MUTED)
    paragraph("↑/↓ or Page Up/Down: scroll   /: find a shortcut   q: close", MUTED)
    paragraph("Ctrl+B → key means release Ctrl+B, then press the next key.", MUTED)

    groups = {
        "Tabs / tmux windows": [
            ("Ctrl+Shift+T", "New tab"),
            ("Ctrl+Page Up / Page Down", "Previous / next tab"),
            ("Ctrl+B → ,", "Rename tab"),
            ("Ctrl+B → &", "Close tab (asks for confirmation)"),
        ],
        "Panes": [
            ("Ctrl+Shift+D", "Split into side-by-side panes"),
            ("Ctrl+Shift+E", "Split into top and bottom panes"),
            ("Ctrl+Alt+arrow", "Move to the pane in that direction"),
            ("Ctrl+Alt+Shift+arrow", "Resize the pane by five cells"),
            ("Ctrl+B → z", "Zoom pane / restore layout"),
            ("Ctrl+B → x", "Close pane (asks for confirmation)"),
        ],
        "History / search": [
            ("Shift+Page Up", "Open tmux history; passed through to fullscreen apps"),
            ("Ctrl+B → Page Up", "Open tmux history, including inside fullscreen apps"),
            ("Arrows / Page Up / Page Down", "Browse while in history"),
            ("Ctrl+F, text, Enter", "Find literal text while in history"),
            ("Esc", "Leave history and return to the application"),
        ],
        "Clipboard / terminal": [
            ("Shift+drag", "Select in Alacritty and copy automatically"),
            ("Ctrl+Shift+C", "Copy selection"),
            ("Ctrl+Shift+V", "Paste clipboard"),
            ("Shift+Insert / middle click", "Paste Linux primary selection"),
            ("Ctrl+= / Ctrl+- / Ctrl+0", "Larger font / smaller font / reset font size"),
            ("Ctrl+Shift+F / Ctrl+Shift+B", "Search Alacritty's own buffer forward / backward"),
        ],
        "SSH / servers": [
            ("Ctrl+B → F2", "Choose a host tagged dalftui; open a new Alacritty window with remote tmux"),
            ("Type / arrows / Enter", "Filter hosts / select / connect in the host picker"),
            ("Esc", "Close the host picker"),
        ],
        "Session / help": [
            ("Ctrl+B → F1", "Open this guide"),
            ("Win+Shift+H", "Alternative in Alacritty"),
            ("Ctrl+B → ?", "Open tmux's native key reference"),
            ("Ctrl+B → d", "Detach; reopen Alacritty to reattach to session 0"),
        ],
    }
    if tmux_only:
        groups["Tabs / tmux windows"] = [
            ("Ctrl+B → c", "New window"),
            ("Ctrl+B → p / n", "Previous / next window"),
            ("Ctrl+B → ,", "Rename window"),
            ("Ctrl+B → &", "Close window (asks for confirmation)"),
        ]
        groups["Panes"] = [
            ("Ctrl+B → %", "Split into side-by-side panes"),
            ('Ctrl+B → "', "Split into top and bottom panes"),
            ("Ctrl+B → arrow", "Move to the pane in that direction"),
            ("Ctrl+B → Ctrl+arrow", "Resize the pane"),
            ("Ctrl+B → z", "Zoom pane / restore layout"),
            ("Ctrl+B → x", "Close pane (asks for confirmation)"),
        ]
        groups["History / search"][0] = ("Ctrl+B → Page Up / [", "Open tmux history")
        del groups["Clipboard / terminal"]
        del groups["SSH / servers"]
        groups["Session / help"] = [
            ("Ctrl+B → F1", "Open this guide"),
            ("Ctrl+B → ?", "Open tmux's native key reference"),
            ("Ctrl+B → d", "Detach from tmux; leave the session running"),
        ]
        groups["From your dalftui Alacritty client"] = [
            ("Ctrl+Shift+T", "New remote tmux window"),
            ("Ctrl+Page Up / Page Down", "Previous / next remote window"),
            ("Ctrl+Shift+D / Ctrl+Shift+E", "Split side by side / top and bottom"),
            ("Ctrl+Alt+arrow", "Move to the pane in that direction"),
            ("Ctrl+Alt+Shift+arrow", "Resize the pane by five cells"),
            ("Shift+drag / Ctrl+Shift+V", "Copy selection / paste using your local terminal"),
        ]
    for title, bindings in groups.items():
        heading(title)
        if title == "From your dalftui Alacritty client":
            paragraph("These shortcuts are supplied by Alacritty on your computer.", MUTED)
        for keys, description in bindings:
            row(keys, description)

    if not tmux_only:
        heading("Alacritty custom bindings (live)")
        paragraph("Read from alacritty.toml and its imports each time this guide opens. Terminal defaults are listed above.", MUTED)
        config = config_path()
        try:
            bindings = load(config)["keyboard"]["bindings"]
            for binding in bindings:
                mods = binding.get("mods", "").replace("Control", "Ctrl").replace("Super", "Win").replace("|", "+")
                key = binding.get("key", "?")
                label = (mods + "+" if mods else "") + key
                if "action" in binding:
                    description = binding["action"]
                elif "command" in binding:
                    description = "Run " + str(binding["command"])
                else:
                    chars = binding.get("chars", "")
                    if chars.startswith("\x02"):
                        tail = chars[1:]
                        description = "tmux: Ctrl+B → " + ("F1" if tail == "\x1bOP" else tail)
                    else:
                        description = "Send " + ascii(chars)
                row(label, description)
        except (OSError, ValueError, KeyError) as error:
            paragraph("Cannot read Alacritty bindings: " + str(error), MUTED)

    try:
        result = subprocess.run(["tmux", "list-keys"], capture_output=True, text=True,
                                timeout=5, check=True)
        table = None
        for line in result.stdout.splitlines():
            parts = shlex.split(line)
            index = parts.index("-T")
            current, key = parts[index + 1:index + 3]
            if current != table:
                table = current
                heading("Live tmux bindings / " + table)
                if table == "prefix":
                    paragraph("Press Ctrl+B first. C- = Ctrl, M- = Alt, S- = Shift.", MUTED)
                elif table == "root":
                    paragraph("Direct bindings, with no Ctrl+B prefix.", MUTED)
                elif table.startswith("copy-mode"):
                    paragraph("Bindings used while browsing tmux history.", MUTED)
            command = " ".join(parts[index + 3:])
            if "-N" in parts[:index]:
                command = parts[parts.index("-N") + 1]
            # Menus contain hundreds of characters; name the command without its UI definition.
            if command.startswith("display-menu "):
                command = "Open tmux menu"
            row(key, command.replace("send-keys -X ", ""))
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        paragraph("Cannot read live tmux bindings: " + str(error), MUTED)

    lines.extend(["", "  " + MUTED + "q: close and return to your terminal" + RESET, ""])
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tmux-only', action='store_true', help='Show the server guide')
    parser.add_argument('--print', action='store_true', help='Print without opening the pager')
    args = parser.parse_args()
    content = render(tmux_only=args.tmux_only)
    if args.print:
        print(content)
    else:
        env = dict(os.environ, LESS="", LESSCHARSET="utf-8")
        subprocess.run(["less", "-R", "-i", "-P",
                        " SHORTCUTS  |  ↑↓ / PgUp PgDn scroll  |  / search  |  q close "],
                       input=content.encode(), env=env, check=False)
