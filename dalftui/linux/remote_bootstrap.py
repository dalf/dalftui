"""Build self-contained POSIX shell programs for Linux SSH servers.

Generation is portable: desktop callers, including Windows, only need Python
and this checkout's canonical tmux policy. SSH execution and the local editor
bridge lifecycle belong to dalftui.ssh.
"""
from pathlib import Path
import shlex

from bridge_protocol import SOCKET_ENV, SUPPORTED_PROTOCOL_VERSIONS, TOKEN_BYTES, TOKEN_ENV
from . import ops

# The installer links the checkout here in both desktop and tmux-only modes.
# Status 3 means there is no remote editor integration to prepare.
# Status 4 means an installed integration cannot declare a supported protocol.
_INSTALLATION_CHECK = """command -v tmux >/dev/null 2>&1 || exit 3
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


def _editor_resources(bridge):
    """Shell helpers for this bridge's private remote resources (Linux server)."""
    socket_file = bridge.remote_socket if bridge.transport == 'unix' else ''
    return (f'editor_directory={shlex.quote(bridge.remote_directory)}\n'
            f'editor_owner={shlex.quote(bridge.remote_owner_file)}\n'
            f'editor_token={shlex.quote(bridge.remote_token_file)}\n'
            f'editor_socket={shlex.quote(socket_file)}\n' + """
editor_directory_valid() {
    [ ! -L "$editor_directory" ] && [ -d "$editor_directory" ] &&
    [ "$(stat -c '%u:%a' -- "$editor_directory")" = "$(id -u):700" ]
}
editor_file_valid() {
    [ ! -L "$1" ] && [ -f "$1" ] &&
    [ "$(stat -c '%u:%a' -- "$1")" = "$(id -u):600" ]
}
editor_owned() {
    editor_directory_valid && editor_file_valid "$editor_owner"
}
cleanup_editor_resources() {
    if editor_owned; then
        rm -f -- "$editor_token"
        if [ -n "$editor_socket" ]; then rm -f -- "$editor_socket"; fi
        rm -f -- "$editor_owner"
        rmdir -- "$editor_directory" 2>/dev/null
    fi
}
""")


def prepare_credentials_script(bridge, *, check_installation=False):
    """Prepare private resources and read the credential from SSH stdin."""
    # stdin is carried by SSH; putting the secret in sh -c arguments would expose
    # it through the VM's process list. The private file is consumed on attach.
    # mkdir refuses existing paths, including symlinks. The claim is separate
    # from the token so cleanup still recognizes the directory after consumption.
    # Create it before -R: sshd binds a Unix forward before the attach command.
    return (_INSTALLATION_CHECK if check_installation else '') + _editor_resources(bridge) + """
umask 077
set -C
mkdir -m 700 -- "$editor_directory" || exit 1
trap 'rm -f -- "$editor_token" "$editor_owner"; rmdir -- "$editor_directory" 2>/dev/null' EXIT
trap 'exit 1' HUP INT TERM
editor_directory_valid || exit 1
: > "$editor_owner" || exit 1
cat > "$editor_token" || exit 1
trap - EXIT HUP INT TERM
"""


def cleanup_script(bridge):
    """Clean up only this attachment's validated, owned remote resources."""
    return _editor_resources(bridge) + '\ncleanup_editor_resources\n'


def session_script(bridge=None, *, mode='normal', check=None, rgb=False):
    """Consume credentials and run the embedded policy in the same shell.

    Keep its exit/signal traps active through the policy and silent login-shell
    fallback. A remote host with tmux does not need a dalftui checkout.
    """
    if mode not in ('normal', 'plain', 'check', 'ops'):
        raise ValueError(f'Unknown SSH session mode: {mode}')
    if mode == 'check' and check is None:
        raise ValueError('A saved check is required')
    editor_setup = ''
    if bridge:
        editor_setup = _editor_resources(bridge) + """
editor_credentials_error() {
    printf '%s\\n' 'Missing or invalid editor bridge credentials. Reconnect using the dalftui SSH launcher.' >&2
    exit 1
}
editor_owned || editor_credentials_error
trap cleanup_editor_resources EXIT
trap 'exit 1' HUP TERM
trap 'exit 130' INT
editor_file_valid "$editor_token" || editor_credentials_error
"""
        editor_setup += (f'{TOKEN_ENV}=$(cat -- "$editor_token") || editor_credentials_error\n'
                         'rm -f -- "$editor_token" || editor_credentials_error\n'
                         f'[ "${{{TOKEN_ENV}}}" ] && [ "${{#{TOKEN_ENV}}}" -eq {TOKEN_BYTES * 2} ] || editor_credentials_error\n'
                         f'case "${{{TOKEN_ENV}}}" in *[!0-9a-f]*) editor_credentials_error ;; esac\n'
                         f'{SOCKET_ENV}={shlex.quote(bridge.remote_socket)}\n'
                         f'export {SOCKET_ENV} {TOKEN_ENV}\n')
    # Resolve our actual module location, even through an installed checkout
    # symlink. Copied desktop checkouts must embed their own canonical policy.
    prefix = f'unset TMUX TMUX_PANE {SOCKET_ENV} {TOKEN_ENV}\n' + editor_setup
    if mode == 'plain':
        return prefix + ops.LOGIN_SHELL
    if mode == 'check':
        return prefix + ops.check_script(check.name, check.command, check.timeout)
    policy = (ops.session_script() if mode == 'ops' else
              Path(__file__).resolve().with_name('tmux-start.sh').read_text(encoding='utf-8'))
    fallback_notice = ("    printf '%s\\n' 'tmux is unavailable; opening a shell.'\n"
                       if mode == 'ops' else '')
    tmux_features = """# The hint belongs to this attachment, even when other clients share the server.
# Older remote tmux versions without -T still run the ordinary session policy.
if tmux -T RGB -V >/dev/null 2>&1; then
    tmux() { command tmux -T RGB "$@"; }
fi
""" if rgb else ''
    return prefix + 'if ! command -v tmux >/dev/null 2>&1; then\n' + fallback_notice + """
    "${SHELL:-/bin/sh}" -l
    exit $?
fi
""" + tmux_features + policy
