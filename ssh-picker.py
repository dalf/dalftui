#!/usr/bin/env python3
"""Pick an SSH host, open another Alacritty window, and attach remote tmux."""
import argparse
try:
    import curses
except ImportError:
    curses = None
import glob
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
from vscode import EditorBridge, SOCKET_ENV, TOKEN_ENV

SSH_CONFIG = Path.home() / '.ssh/config'
PICKER_TAG = 'dalftui'

# Execute with sh so this also works when the remote login shell is fish.
REMOTE_SCRIPT = """unset TMUX TMUX_PANE DALFTUI_EDITOR_SOCKET DALFTUI_EDITOR_TOKEN
{editor_setup}
if ! command -v tmux >/dev/null 2>&1; then
    printf '%s\\n' 'tmux is not installed on this host.' >&2
    exit 127
fi
sessions=$(tmux list-sessions -F '#{session_id}' 2>/dev/null)
run_tmux() {
if [ -z "$sessions" ]; then
    tmux new-session -A -s 0
    return $?
fi
set -- $sessions
if [ "$#" -eq 1 ]; then
    tmux attach-session -t "$1"
    return $?
fi
tmux attach-session \\; choose-tree -sZ
}
run_tmux
"""


def valid_host(value):
    return bool(value) and not value.startswith('-') and all(
        char.isprintable() and not char.isspace() for char in value)


def ssh_executable():
    if sys.platform == 'win32':
        native = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/OpenSSH/ssh.exe'
        if native.is_file():
            return str(native)
    return 'ssh'


def configured_hosts(path=SSH_CONFIG):
    """Collect explicit aliases, including Include files; wildcard rules are not hosts."""
    hosts, visited = [], set()

    def read(config, depth=0):
        config = config.expanduser().resolve()
        if config in visited or depth >= 16:
            return
        visited.add(config)
        try:
            lines = config.read_text().splitlines()
        except (OSError, UnicodeError):
            return
        for line in lines:
            match = re.match(r'\s*(\w+)(?:\s*=\s*|\s+)(.*)', line)
            if not match:
                continue
            keyword, value = match.groups()
            try:
                words = shlex.split(value, comments=True)
            except ValueError:
                continue
            if keyword.lower() == 'host':
                hosts.extend(word for word in words if valid_host(word)
                             and not any(char in word for char in '*?!'))
            elif keyword.lower() == 'include':
                for pattern in words:
                    include = Path(os.path.expanduser(pattern))
                    if not include.is_absolute():
                        include = SSH_CONFIG.parent / include
                    for filename in sorted(glob.glob(str(include))):
                        read(Path(filename), depth + 1)

    read(path)
    return list(dict.fromkeys(hosts))


def configured_tag(host):
    """Ask OpenSSH for the effective tag, including matching Host/Match/Include rules."""
    if not valid_host(host):
        raise ValueError('Invalid SSH destination')
    args = [ssh_executable(), '-G', '-F', str(SSH_CONFIG), '--', host]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f'Could not read the SSH tag for {host}: {error}') from error
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f'Could not read SSH configuration for {host}')
    return next((line.split(None, 1)[1] for line in result.stdout.splitlines()
                 if line.startswith('tag ')), '')


def target_hosts():
    return [host for host in configured_hosts(SSH_CONFIG)
            if configured_tag(host) == PICKER_TAG]


def pick(screen, hosts):
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN, -1)
    curses.init_pair(2, curses.COLOR_WHITE, -1)
    curses.init_pair(3, 246 if curses.COLORS >= 256 else curses.COLOR_WHITE, -1)
    curses.set_escdelay(25)
    query, selected, message = '', 0, ''

    def write(y, x, text, style=0):
        height, width = screen.getmaxyx()
        if 0 <= y < height and x < width - 1:
            try:
                screen.addnstr(y, x, text, width - x - 1, style)
            except curses.error:
                pass

    while True:
        height, width = screen.getmaxyx()
        screen.erase()
        matches = [host for host in hosts if query.casefold() in host.casefold()]
        selected = max(0, min(selected, len(matches) - 1))
        capacity = max(1, height - 9)
        start = max(0, selected - capacity + 1)
        write(1, 2, 'SSH HOSTS · TAG DALFTUI', curses.color_pair(1) | curses.A_BOLD)
        write(2, 2, 'Type to filter · ↑/↓ select · Enter opens a new window · Esc cancels', curses.color_pair(3))
        write(4, 2, 'Filter: ', curses.color_pair(3))
        write(4, 10, query, curses.color_pair(2))
        if not matches:
            hint = ('No matching tagged hosts. Enter checks the typed hostname.' if query
                    else 'No hosts enabled. Add Tag dalftui to an SSH Host entry.')
            write(6, 2, hint, curses.color_pair(3))
        for index in range(start, min(len(matches), start + capacity)):
            label = matches[index]
            style = curses.color_pair(2)
            if index == selected:
                style |= curses.A_REVERSE | curses.A_BOLD
            write(6 + index - start, 2, ('  ' + label).ljust(max(0, width - 5)), style)
        write(height - 3, 2, message, curses.color_pair(1))
        write(height - 2, 2, 'Remote tmux: none → create · one → attach · several → choose', curses.color_pair(3))
        try:
            screen.move(min(4, height - 1), min(10 + len(query), max(0, width - 2)))
        except curses.error:
            pass
        screen.refresh()
        key = screen.get_wch()
        if key in ('\x1b', '\x03'):
            return None
        if key in ('\n', '\r', curses.KEY_ENTER):
            if matches:
                return matches[selected]
            if valid_host(query):
                try:
                    if configured_tag(query) == PICKER_TAG:
                        return query
                    message = f'{query} is not enabled: add Tag dalftui to its SSH configuration.'
                except RuntimeError as error:
                    message = str(error)
            continue
        if key == curses.KEY_UP:
            selected = max(0, selected - 1)
        elif key == curses.KEY_DOWN:
            selected = min(len(matches) - 1, selected + 1)
        elif key == curses.KEY_PPAGE:
            selected = max(0, selected - capacity)
        elif key == curses.KEY_NPAGE:
            selected = min(len(matches) - 1, selected + capacity)
        elif key in ('\x7f', '\b', curses.KEY_BACKSPACE):
            query, selected, message = query[:-1], 0, ''
        elif key == '\x15':
            query, selected, message = '', 0, ''
        elif isinstance(key, str) and key.isprintable() and not key.isspace():
            query, selected, message = query + key, 0, ''


def configured_login(host):
    """Let OpenSSH resolve User, with a fallback marker to distinguish its local-user default."""
    marker = f'__alacritty_unset_user_{os.getpid()}__'
    with tempfile.TemporaryDirectory(prefix='alacritty-ssh-config-') as directory:
        wrapper = Path(directory) / 'config'
        content = ''
        if SSH_CONFIG.exists():
            quoted = str(SSH_CONFIG).replace('\\', '\\\\').replace('"', '\\"')
            content = f'Include "{quoted}"\n'
        wrapper.write_text(content + f'Host *\n    User {marker}\n')
        result = subprocess.run([ssh_executable(), '-G', '-F', str(wrapper), '--', host],
                                capture_output=True, text=True, timeout=10)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or 'Could not read SSH configuration')
        user = next((line.split(None, 1)[1] for line in result.stdout.splitlines()
                     if line.startswith('user ')), marker)
        return None if user == marker else user


def ssh_base(host, login=None):
    if not valid_host(host):
        raise ValueError('Invalid SSH destination')
    args = [ssh_executable(), '-o', 'RemoteCommand=none']
    if login is not None:
        if not valid_host(login) or '@' in login or '/' in login:
            raise ValueError('Invalid SSH login')
        args.extend(['-l', login])
    return args


def prepare_tcp_token(host, login, bridge, env):
    # stdin is carried by SSH; putting the secret in sh -c arguments would expose
    # it through the VM's process list. The private file is consumed on attach.
    script = 'umask 077\nset -C\ncat > ' + shlex.quote(bridge.remote_token_file)
    result = subprocess.run([*ssh_base(host, login), '-T', '-o', 'ClearAllForwardings=yes',
                             '--', host, 'sh -c ' + shlex.quote(script)],
                            input=(bridge.token + '\n').encode('ascii'), env=env)
    if result.returncode:
        raise RuntimeError('Could not prepare the Windows VS Code bridge on the SSH server.')


def cleanup_tcp_token(host, login, bridge, env):
    # Normal attachment consumes the file. If attachment fails, avoid asking for
    # another password just to remove an inactive token left by the setup step.
    script = 'rm -f -- ' + shlex.quote(bridge.remote_token_file)
    try:
        subprocess.run([*ssh_base(host, login), '-T', '-n', '-o', 'ClearAllForwardings=yes',
                        '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
                        '--', host, 'sh -c ' + shlex.quote(script)], env=env,
                       capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


def ssh_command(host, login=None, bridge=None):
    args = [*ssh_base(host, login), '-t']
    editor_setup = ''
    if bridge:
        # Keep the forwarding and its local bridge owned by this SSH window.
        if sys.platform != 'win32':
            args += ['-S', 'none']
        forward = getattr(bridge, 'forward_spec', f'{bridge.remote_socket}:{bridge.local_socket}')
        args += ['-R', forward]
        editor_setup = (f'{SOCKET_ENV}={shlex.quote(bridge.remote_socket)}\n'
                        f'export {SOCKET_ENV}\n')
        if getattr(bridge, 'token', None):
            # Refuse an occupied remote TCP port instead of attaching with a broken bridge.
            args += ['-o', 'ExitOnForwardFailure=yes']
            token_file = shlex.quote(bridge.remote_token_file)
            editor_setup += (f'{TOKEN_ENV}=$(cat -- {token_file}) || exit 1\n'
                             f'export {TOKEN_ENV}\n'
                             f'rm -f -- {token_file}\n')
        else:
            editor_setup += f'trap \'rm -f -- "${SOCKET_ENV}"\' EXIT\n'
    return [*args, '--', host,
            'sh -c ' + shlex.quote(REMOTE_SCRIPT.replace('{editor_setup}', editor_setup))]


def connect(host, transport=None):
    env = dict(os.environ, TERM='xterm-256color')
    env.pop('TMUX', None)
    env.pop('TMUX_PANE', None)
    try:
        login = None
        if configured_login(host) is None:
            while not login:
                value = input(f'SSH login for {host}: ').strip()
                if valid_host(value) and '@' not in value and '/' not in value:
                    login = value
                else:
                    print('Enter a username, such as alice.')
        print(f'Connecting to {host} …', flush=True)
        destination = f'{login}@{host}' if login else host
        with EditorBridge(destination, env, transport) as bridge:
            status = 1
            try:
                if bridge.token:
                    prepare_tcp_token(host, login, bridge, env)
                status = subprocess.run(ssh_command(host, login, bridge), env=env).returncode
            finally:
                if bridge.token and status:
                    cleanup_tcp_token(host, login, bridge, env)
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError, subprocess.TimeoutExpired, EOFError, ValueError) as error:
        print(error, file=sys.stderr)
        status = 1
    if status:
        print(f'\nSSH to {host} ended with status {status}.')
        try:
            input('Press Enter to close this window.')
        except (EOFError, KeyboardInterrupt):
            pass
    return status


def open_window(host):
    alacritty = shutil.which('alacritty')
    if not alacritty:
        raise RuntimeError('Alacritty was not found in PATH')
    env = dict(os.environ)
    env.pop('TMUX', None)
    env.pop('TMUX_PANE', None)
    # -e overrides the normal local-tmux startup command for this new OS window.
    args = [alacritty, '--title', f'SSH · {host}', '-e', sys.executable,
            str(Path(__file__).resolve()), '--connect', host]
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(args, env=env, start_new_session=True,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        try:
            status = process.wait(timeout=0.4)
        except subprocess.TimeoutExpired:
            return
        if status:
            log.seek(0)
            raise RuntimeError(log.read().decode(errors='replace').strip() or 'Could not open Alacritty')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--connect', metavar='HOST')
    parser.add_argument('--bridge', choices=('unix', 'tcp'),
                        help='Editor bridge transport (default: TCP on Windows, Unix socket on Linux)')
    parser.add_argument('--list', action='store_true', help='Print the host list without connecting')
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error('Python 3.11 or newer is required.')
    if args.connect:
        return connect(args.connect, args.bridge)
    if args.list:
        print('\n'.join(target_hosts()))
        return 0
    if curses is None:
        parser.error('Use --connect HOST on Windows; the interactive host picker requires curses.')
    try:
        host = curses.wrapper(pick, target_hosts())
        if host:
            open_window(host)
    except (OSError, RuntimeError, curses.error) as error:
        print(f'Could not open SSH window: {error}', file=sys.stderr)
        try:
            input('Press Enter to return.')
        except (EOFError, KeyboardInterrupt):
            pass
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
