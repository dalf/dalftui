#!/usr/bin/env -S uv run --no-project --python >=3.11
"""A readable shortcut guide, followed by the current tmux bindings."""
import argparse
import os
import shlex
import shutil
import subprocess
import sys
import textwrap

sys.dont_write_bytecode = True

RESET = "\033[0m"
WHITE = "\033[1;97m"
KEY = "\033[38;2;137;221;255m"
TEXT = "\033[38;2;229;231;235m"
MUTED = "\033[38;2;166;173;200m"


def tmux_profile():
    """Return the active dalftui tmux profile, or an empty string."""
    try:
        return subprocess.run(["tmux", "show-options", "-gqv", "@dalftui_profile"], capture_output=True,
                              text=True, timeout=5, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


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
    paragraph("Ctrl+B then F1 opens this guide. These tmux keys work over SSH.", MUTED)
    paragraph("↑/↓ or Page Up/Down: scroll   /: find a shortcut   q: close", MUTED)
    paragraph("Ctrl+B → key means release Ctrl+B, then press the next key.", MUTED)

    groups = {
        "Tabs / tmux windows": [
            ("Ctrl+B → c", "New window"),
            ("Ctrl+B → p / n", "Previous / next window"),
            ("Ctrl+B → 0-9", "Go to that window; Ctrl may stay held for 1-9 if the terminal reports Ctrl+digit"),
            ("Ctrl+B → ,", "Rename window"),
            ("Ctrl+B → &", "Close window (asks for confirmation)"),
        ],
        "Panes": [
            ("Ctrl+B → %", "Split into side-by-side panes"),
            ('Ctrl+B → "', "Split into top and bottom panes"),
            ("Ctrl+B → arrow", "Move to the pane in that direction"),
            ("Ctrl+B → Ctrl+arrow", "Resize the pane"),
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
        "Select / copy / paste": [
            ("Shift+drag", "Select text in kitty or Windows Terminal, locally or over SSH"),
            ("Ctrl+Shift+C / Ctrl+Shift+V", "Copy selection / paste; in Windows Terminal, select before copying"),
            ("Split panes", "Ctrl+B → z to zoom, Shift+drag, then Ctrl+B → z to restore"),
            ("Text in history", "Scroll with the wheel or Shift+Page Up, then Shift+drag"),
            ("Plain drag / double-click", "Does not select in shells (drag shows a hint); mouse apps such as htop receive it"),
        ],
        "kitty terminal": [
            ("Shift+Insert / middle click", "Paste Linux primary selection"),
            ("Ctrl+Shift+= / - / Backspace", "Larger font / smaller font / reset font size"),
            ("Ctrl+Shift+Right / Left", "Next / previous kitty tab, such as an SSH tab"),
        ],
        "SSH / servers": [
            ("Ctrl+B → F2", "Choose a host tagged dalftui; open a new kitty tab with remote tmux"),
            ("Type / arrows / Enter", "Filter hosts / select / connect in the host picker"),
            ("Esc", "Close the host picker"),
        ],
        "Session / help": [
            ("Ctrl+B → F1", "Open this guide"),
            ("Ctrl+B → ?", "Open tmux's native key reference"),
            ("Ctrl+B → d", "Detach from tmux; leave the session running"),
        ],
        "Editor": [
            ("Ctrl+B → F3 / v", "Open the current pane's folder in a new VS Code window"),
            ("Remote VS Code", "Reconnect through the dalftui SSH launcher after updating; each client needs credentials"),
        ],
    }
    if tmux_only:
        groups["History / search"][0] = ("Ctrl+B → Page Up / [", "Open tmux history")
        groups["Select / copy / paste"][3] = ("Text in history", "Scroll with the wheel or Ctrl+B → Page Up, then Shift+drag")
        del groups["kitty terminal"]
        if tmux_profile() == "macos":
            groups["SSH / servers"][0] = ("Ctrl+B → h", "Choose a host tagged dalftui; open a new Terminal.app or iTerm2 window with remote tmux")
        else:
            del groups["SSH / servers"]
    if tmux_only and sys.platform == "darwin":
        groups["Select / copy / paste"][:4] = [
            ("Fn+drag / Option+drag", "Select text in Terminal.app / iTerm2"),
            ("Cmd+C / Cmd+V", "Copy selection / paste"),
            ("Split panes", "Ctrl+B → z to zoom, select, then Ctrl+B → z to restore"),
            ("Text in history", "Scroll with the wheel or Ctrl+B → Page Up, then select"),
        ]
        # Apple keyboards send F1/F3 with Fn unless set to standard function keys.
        groups["Session / help"][0] = ("Ctrl+B → Fn+F1", "Open this guide")
        groups["Editor"][0] = (groups["Editor"][0][0].replace("F3", "Fn+F3"), groups["Editor"][0][1])
        del groups["Editor"][1]  # Relaying to an SSH client's editor is not supported on a Mac.
    for title, bindings in groups.items():
        heading(title)
        for keys, description in bindings:
            row(keys, description)

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tmux-only', action='store_true', help='Show the server and macOS guide')
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


if __name__ == "__main__":
    main()
