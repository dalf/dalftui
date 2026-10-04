"""Frozen SSH discovery and standalone declaration at the bin/ migration.

These copies do not import current helpers. Keep v1 and v2 fixtures frozen.
"""

SUPPORTED_PROTOCOL_VERSIONS = frozenset({1, 2})

REMOTE_EDITOR_CHECK = """command -v tmux >/dev/null 2>&1 || exit 3
case ${XDG_CONFIG_HOME:-} in
    /*) dalftui_config=$XDG_CONFIG_HOME ;;
    *) dalftui_config=$HOME/.config ;;
esac
[ -r "$dalftui_config/dalftui/config/tmux.conf" ] || exit 3
[ -r "$dalftui_config/dalftui/bin/vscode.py" ] &&
[ -r "$dalftui_config/dalftui/bridge_protocol.py" ] || exit 4
command -v python3 >/dev/null 2>&1 || exit 4
remote_protocol=$(python3 "$dalftui_config/dalftui/bridge_protocol.py" --version 2>/dev/null) || exit 4
case $remote_protocol in
""" + f"    {'|'.join(str(version) for version in sorted(SUPPORTED_PROTOCOL_VERSIONS))}) ;;\n" + """    *) exit 4 ;;
esac
"""


PROTOCOL_DECLARATION = """import argparse

PROTOCOL_VERSION = 2


def main():
    parser = argparse.ArgumentParser(description='Report the editor bridge protocol version.')
    parser.add_argument('--version', action='store_true', required=True)
    parser.parse_args()
    print(PROTOCOL_VERSION)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
"""
