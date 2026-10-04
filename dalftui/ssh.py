#!/usr/bin/env python3
"""Pick an SSH host, using remote tmux and a VS Code bridge when installed."""
import argparse
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
from bridge_protocol import SOCKET_ENV, SUPPORTED_PROTOCOL_VERSIONS, TOKEN_BYTES, TOKEN_ENV
from .vscode import EditorBridge

SSH_CONFIG = Path.home() / '.ssh/config'
PICKER_TAG = 'dalftui'

# Use the same tmux policy for local and remote terminals, with a silent shell
# fallback on remote hosts. Execute with sh even when the login shell is fish.
CHECKOUT_ROOT = Path(__file__).resolve().parent.parent
TMUX_START_SCRIPT = (CHECKOUT_ROOT / 'tmux-start.sh').read_text()
REMOTE_SCRIPT = """unset TMUX TMUX_PANE DALFTUI_EDITOR_SOCKET DALFTUI_EDITOR_TOKEN
{editor_setup}
if ! command -v tmux >/dev/null 2>&1; then
    "${SHELL:-/bin/sh}" -l
    exit $?
fi
""" + TMUX_START_SCRIPT

# The installer links the checkout here in both desktop and tmux-only modes.
# Status 3 means there is no remote editor integration to prepare.
# Status 4 means an installed integration cannot declare a supported protocol.
REMOTE_EDITOR_CHECK = """command -v tmux >/dev/null 2>&1 || exit 3
case ${XDG_CONFIG_HOME:-} in
    /*) dalftui_config=$XDG_CONFIG_HOME ;;
    *) dalftui_config=$HOME/.config ;;
esac
[ -r "$dalftui_config/dalftui/vscode.py" ] &&
[ -r "$dalftui_config/dalftui/config/tmux.conf" ] || exit 3
[ -r "$dalftui_config/dalftui/bridge_protocol.py" ] || exit 4
command -v python3 >/dev/null 2>&1 || exit 4
remote_protocol=$(python3 "$dalftui_config/dalftui/bridge_protocol.py" --version 2>/dev/null) || exit 4
case $remote_protocol in
""" + f"    {'|'.join(str(version) for version in sorted(SUPPORTED_PROTOCOL_VERSIONS))}) ;;\n" + """    *) exit 4 ;;
esac
"""


def valid_host(value):
    return bool(value) and not value.startswith('-') and all(
        char.isprintable() and not char.isspace() for char in value)


def ssh_executable():
    if sys.platform == 'win32':
        from .windows import ssh as windows_ssh
        return windows_ssh.ssh_executable()
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
        if 'bad configuration option: tag' in result.stderr.lower():
            raise RuntimeError('The host picker requires OpenSSH 9.4+ for Tag dalftui. '
                               'Update your OpenSSH client, then retry.')
        raise RuntimeError(result.stderr.strip() or f'Could not read SSH configuration for {host}')
    return next((line.split(None, 1)[1] for line in result.stdout.splitlines()
                 if line.startswith('tag ')), '')


def target_hosts():
    return [host for host in configured_hosts(SSH_CONFIG)
            if configured_tag(host) == PICKER_TAG]


def pick_fzf(hosts=None):
    """Use the native Windows fzf picker, also available with --pick on Linux."""
    executable = shutil.which('fzf')
    if not executable:
        raise RuntimeError('fzf was not found. Run setup-windows.ps1, or install fzf '
                           'with winget or Chocolatey. Use --connect HOST to connect directly.')
    hosts = target_hosts() if hosts is None else hosts
    if not hosts:
        raise RuntimeError(f'No hosts enabled in {SSH_CONFIG}. Add Tag dalftui '
                           'to the SSH Host entries you want in the picker.')
    env = dict(os.environ)
    # Personal multi-select/print-query settings would change the returned host.
    env.pop('FZF_DEFAULT_OPTS', None)
    env.pop('FZF_DEFAULT_OPTS_FILE', None)
    result = subprocess.run(
        [executable, '--height=80%', '--layout=reverse', '--border=rounded',
         '--no-multi', '--prompt=Host> ',
         '--header=SSH hosts | Tag dalftui\nType to filter | Up/Down select | Enter connect | Esc cancel',
         '--color=bg:-1,fg:#e5e7eb,bg+:#e5e7eb,fg+:#111827,hl:#89b4fa,hl+:#1565c0,'
         'header:#a6adc8,prompt:#89b4fa,pointer:#89b4fa,border:#585b70'],
        input='\n'.join(hosts) + '\n', stdout=subprocess.PIPE,
        encoding='utf-8', env=env)
    if result.returncode in (1, 130):
        return None
    if result.returncode:
        raise RuntimeError(f'fzf exited with status {result.returncode}.')
    selected = result.stdout.strip()
    if selected not in hosts:
        raise RuntimeError('fzf did not return a configured, tagged host.')
    return selected


def configured_login(host):
    """Let OpenSSH resolve User, with a fallback marker to distinguish its local-user default."""
    marker = f'__alacritty_unset_user_{os.getpid()}__'
    with tempfile.TemporaryDirectory(prefix='alacritty-ssh-config-') as directory:
        if sys.platform == 'win32':
            from .windows import ssh as windows_ssh
            windows_ssh.secure_ssh_directory(directory)
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


def editor_resources(bridge):
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


def prepare_editor_credentials(host, login, bridge, env, *, check_installation=False):
    """Prepare private credentials, or return False when integration is absent."""
    # stdin is carried by SSH; putting the secret in sh -c arguments would expose
    # it through the VM's process list. The private file is consumed on attach.
    # mkdir refuses existing paths, including symlinks. The claim is separate
    # from the token so cleanup still recognizes the directory after consumption.
    # Create it before -R: sshd binds a Unix forward before the attach command.
    script = (REMOTE_EDITOR_CHECK if check_installation else '') + editor_resources(bridge) + """
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
    result = subprocess.run([*ssh_base(host, login), '-T', '-o', 'ClearAllForwardings=yes',
                             '--', host, 'sh -c ' + shlex.quote(script)],
                            input=(bridge.token + '\n').encode('ascii'), env=env)
    if check_installation and result.returncode == 3:
        return False
    if check_installation and result.returncode == 4:
        print('Remote dalftui cannot declare a supported editor bridge protocol. '
              'Update dalftui from https://github.com/dalf/dalftui on the older machine '
              'and reconnect. Connecting without the VS Code bridge.', file=sys.stderr)
        return False
    if result.returncode:
        raise RuntimeError('Could not prepare the VS Code bridge credentials on the SSH server.')
    return True


def cleanup_editor_bridge(host, login, bridge, env):
    # The remote trap handles normal exit. Also try after failed setup, cancelled
    # attach, or disconnect, without asking for another password just for cleanup.
    # Output is unused. On Windows, inherited pipes can outlive ssh.exe and make
    # subprocess.run's timeout recovery wait for a surviving ProxyCommand child.
    script = editor_resources(bridge) + '\ncleanup_editor_resources\n'
    try:
        subprocess.run([*ssh_base(host, login), '-T', '-n', '-o', 'ClearAllForwardings=yes',
                        '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
                        '--', host, 'sh -c ' + shlex.quote(script)], env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


def ssh_command(host, login=None, bridge=None):
    args = [*ssh_base(host, login), '-t']
    editor_setup = ''
    if bridge:
        # Keep the forwarding and its local bridge owned by this SSH window.
        if sys.platform != 'win32':
            args += ['-S', 'none']
        # Both transports must refuse an occupied or disallowed forward.
        args += ['-R', bridge.forward_spec, '-o', 'ExitOnForwardFailure=yes']
        editor_setup = editor_resources(bridge) + """
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
    return [*args, '--', host,
            'sh -c ' + shlex.quote(REMOTE_SCRIPT.replace('{editor_setup}', editor_setup))]


def connect(host, transport=None):
    env = dict(os.environ, TERM='xterm-256color')
    env.pop('TMUX', None)
    env.pop('TMUX_PANE', None)
    env.pop(SOCKET_ENV, None)
    env.pop(TOKEN_ENV, None)
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
        bridge = EditorBridge(destination, env, transport)
        status = 1
        prepared = None
        try:
            prepared = prepare_editor_credentials(host, login, bridge, env, check_installation=True)
            if prepared:
                with bridge:
                    status = subprocess.run(ssh_command(host, login, bridge), env=env).returncode
            else:
                status = subprocess.run(ssh_command(host, login), env=env).returncode
        finally:
            # Stop accepting/launching before any potentially slow cleanup SSH.
            if prepared is not False:
                cleanup_editor_bridge(host, login, bridge, env)
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--connect', metavar='HOST')
    action.add_argument('--pick', action='store_true',
                        help='Use fzf to choose a host and connect in this terminal (Windows default)')
    action.add_argument('--list', action='store_true', help='Print the host list without connecting')
    parser.add_argument('--bridge', choices=('unix', 'tcp'),
                        help='Editor bridge transport (default: TCP on Windows, Unix socket on Linux)')
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error('Python 3.11 or newer is required.')
    if args.connect:
        return connect(args.connect, args.bridge)
    if args.list:
        print('\n'.join(target_hosts()))
        return 0
    if sys.platform == 'win32' or args.pick:
        try:
            host = pick_fzf()
            return connect(host, args.bridge) if host else 0
        except KeyboardInterrupt:
            return 130
        except (OSError, RuntimeError, UnicodeError) as error:
            print(f'Could not choose an SSH host: {error}', file=sys.stderr)
            return 1
    from .linux import ssh_picker
    return ssh_picker.run_picker(parser)


if __name__ == '__main__':
    raise SystemExit(main())
