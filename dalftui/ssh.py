#!/usr/bin/env -S uv run --no-project --python >=3.11
"""Pick an SSH host, using remote tmux and a VS Code bridge when installed."""
import argparse
from dataclasses import dataclass
import fnmatch
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
from bridge_protocol import SOCKET_ENV, TOKEN_ENV
from .linux import remote_bootstrap
from .linux import ops
from .host_picker import HostAction
from .vscode import EditorBridge

SSH_CONFIG = Path.home() / '.ssh/config'
PICKER_TAG = 'dalftui'
HOST_CACHE_VERSION = 1
CHECKS_CONFIG = Path.home() / '.ssh/dalftui-checks.json'

CHECKOUT_ROOT = Path(__file__).resolve().parent.parent


def valid_host(value):
    return bool(value) and not value.startswith('-') and all(
        char.isprintable() and not char.isspace() for char in value)


def ssh_executable():
    if sys.platform == 'win32':
        from .windows import ssh as windows_ssh
        return windows_ssh.ssh_executable()
    return 'ssh'


def host_config_snapshot(path):
    """Collect aliases and fingerprint dependencies we can track without OpenSSH."""
    hosts, visited = [], set()
    dependencies = []
    cacheable = True

    def read(config, depth=0):
        nonlocal cacheable
        config = config.expanduser().resolve()
        if depth >= 16:
            cacheable = False
            return
        if config in visited:
            return
        visited.add(config)
        try:
            contents = config.read_text()
        except (OSError, UnicodeError):
            cacheable = False
            return
        dependencies.append([str(config), hashlib.sha256(contents.encode('utf-8')).hexdigest()])
        for line in contents.splitlines():
            match = re.match(r'\s*(\w+)(?:\s*=\s*|\s+)(.*)', line)
            if not match:
                if line.strip() and not line.lstrip().startswith('#'):
                    cacheable = False
                continue
            keyword, value = match.groups()
            keyword = keyword.lower()
            try:
                words = shlex.split(value, comments=True)
            except ValueError:
                cacheable = False
                continue
            # Environment expansion and unsupported include syntax can hide
            # dependencies. Keep using OpenSSH, but do not reuse its results.
            if '${' in value or (keyword in ('hostname', 'tag') and '%' in value):
                cacheable = False
            if keyword == 'match' and not static_host_match(words):
                cacheable = False
            if keyword == 'host':
                hosts.extend(word for word in words if valid_host(word)
                             and not any(char in word for char in '*?!'))
            elif keyword == 'include':
                if any(char in value for char in ('%', '$', '\\')):
                    cacheable = False
                for pattern in words:
                    include = Path(os.path.expanduser(pattern))
                    if str(include).startswith('~'):
                        cacheable = False
                    if not include.is_absolute():
                        include = SSH_CONFIG.parent / include
                    filenames = sorted(glob.glob(str(include)))
                    dependencies.append([str(include), filenames])
                    for filename in filenames:
                        read(Path(filename), depth + 1)

    read(path)
    digest = hashlib.sha256(json.dumps(dependencies).encode('utf-8')).hexdigest() if cacheable else None
    return list(dict.fromkeys(hosts)), digest


def static_host_match(words):
    """Unknown or externally evaluated Match conditions must bypass the cache."""
    index = 0
    while index < len(words):
        criterion = words[index].lower().lstrip('!')
        index += 1
        if criterion in ('all', 'canonical', 'final'):
            continue
        if criterion not in ('host', 'originalhost', 'tagged') or index == len(words):
            return False
        index += 1
    return bool(words)


def configured_hosts(path=SSH_CONFIG):
    """Collect explicit aliases, including Include files; wildcard rules are not hosts."""
    return host_config_snapshot(path)[0]


def host_cache_path():
    if sys.platform == 'win32':
        from .windows import ssh as windows_ssh
        return windows_ssh.host_cache_path()
    from .linux import ssh_picker
    return ssh_picker.host_cache_path()


def host_cache_key(digest):
    if digest is None:
        return None
    executable = shutil.which(ssh_executable())
    if not executable:
        return None
    try:
        executable = Path(executable).resolve()
        info = executable.stat()
    except OSError:
        return None
    return {'version': HOST_CACHE_VERSION, 'config': digest, 'tag': PICKER_TAG,
            'ssh': [str(executable), info.st_size, info.st_mtime_ns, info.st_ctime_ns]}


def read_host_cache(path, key, aliases):
    try:
        cached = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(cached, dict) or cached.get('key') != key:
        return None
    hosts = cached.get('hosts')
    if (not isinstance(hosts, list) or
            any(not isinstance(host, str) or host not in aliases for host in hosts) or
            hosts != [host for host in aliases if host in hosts]):
        return None
    return hosts


def write_host_cache(path, key, hosts):
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name + '.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({'key': key, 'hosts': hosts}, stream)
        os.replace(temporary, path)
    except OSError:
        # A read-only/unavailable cache must not prevent opening the picker.
        pass
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def configured_tag(host):
    """Evaluate an alias's tag without DNS hostname canonicalization."""
    if not valid_host(host):
        raise ValueError('Invalid SSH destination')
    # ssh -G still performs canonicalization when enabled in the user's config.
    # Listing aliases must not wait for DNS on every host (e.g. outside a VPN).
    args = [ssh_executable(), '-G', '-o', 'CanonicalizeHostname=no',
            '-F', str(SSH_CONFIG), '--', host]
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


def target_hosts(*, refresh=False):
    aliases, digest = host_config_snapshot(SSH_CONFIG)
    key = host_cache_key(digest)
    path = host_cache_path() if key is not None else None
    if path is not None and not refresh:
        cached = read_host_cache(path, key, aliases)
        if cached is not None:
            return sorted(cached, key=str.casefold)
    hosts = [host for host in aliases if configured_tag(host) == PICKER_TAG]
    if path is not None:
        # Do not publish a mixed result if files/client changed during probing.
        _, after = host_config_snapshot(SSH_CONFIG)
        if host_cache_key(after) == key:
            write_host_cache(path, key, hosts)
    return sorted(hosts, key=str.casefold)


def validate_picker_host(host, *, require_tag=True):
    if not valid_host(host):
        return 'Enter a valid SSH hostname, IP address or user@host.'
    if require_tag and configured_tag(host) != PICKER_TAG:
        return f'{host} is not enabled: add Tag dalftui to its SSH configuration.'
    return ''


def pick_host(*, refresh=False):
    """Choose a host in the native full-screen grid."""
    options = {'refresh': True} if refresh else {}
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RuntimeError('The SSH picker requires an interactive terminal. '
                           'Open it in a terminal, or use --connect HOST to connect directly.')
    hosts = target_hosts(**options)
    if sys.platform == 'win32':
        from . import host_picker
        from .windows.host_picker import ConsoleScreen, ConsoleUnavailable
        try:
            with ConsoleScreen() as screen:
                return host_picker.pick(screen, hosts, validate_picker_host,
                                        details=connection_details, checks=saved_checks)
        except ConsoleUnavailable as error:
            raise RuntimeError(f'{error} Use --connect HOST to connect directly.') from error
    from .linux import ssh_picker
    if ssh_picker.curses is None:
        raise RuntimeError('The SSH picker requires Python curses support. '
                           'Use --connect HOST to connect directly.')
    return ssh_picker.curses.wrapper(ssh_picker.pick, hosts, action='connect')


def connection_details(host):
    """Evaluate only the selected destination, using the connection's SSH options."""
    try:
        result = subprocess.run([*ssh_base(host), '-G', '--', host], capture_output=True,
                                text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(f'Could not read SSH details for {host}: {error}') from error
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Could not read SSH configuration')
    labels = {'hostname': 'Hostname', 'user': 'User', 'port': 'Port',
              'proxyjump': 'Jump host', 'proxycommand': 'Proxy command',
              'identityfile': 'Identity file', 'identitiesonly': 'Identities only',
              'forwardagent': 'Agent forwarding'}
    lines = [f'SSH destination: {host}']
    for line in result.stdout.splitlines():
        key, _, value = line.partition(' ')
        if key in labels:
            lines.append(f'{labels[key]}: {value}')
    return lines + ['', 'Values are evaluated by OpenSSH; no connection is opened.',
                    'If User is unset in your configuration, dalftui asks for a login.',
                    'Identity files are paths only; key contents are never read.']


@dataclass(frozen=True)
class SavedCheck:
    name: str
    command: str
    timeout: int = 30


def saved_checks(host):
    """Load local, trusted shell commands only when the checks action is opened."""
    checks = [SavedCheck('packages', ops.package_status_script()),
              SavedCheck('system', ops.system_status_script(), 20)]
    try:
        data = json.loads(CHECKS_CONFIG.read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return checks
    except (OSError, ValueError) as error:
        raise RuntimeError(f'Could not read {CHECKS_CONFIG}: {error}') from error
    if not isinstance(data, dict) or set(data) != {'checks'} or not isinstance(data['checks'], list):
        raise ValueError(f'{CHECKS_CONFIG}: expected an object with a checks array')
    names = {check.name for check in checks}
    for item in data['checks']:
        if not isinstance(item, dict) or set(item) - {'name', 'command', 'hosts', 'timeout'}:
            raise ValueError(f'{CHECKS_CONFIG}: invalid check fields')
        name, command = item.get('name'), item.get('command')
        timeout, hosts = item.get('timeout', 30), item.get('hosts', ['*'])
        if (not isinstance(name, str) or not name.strip() or not name.isprintable()
                or name in names or not isinstance(command, str) or not command.strip()
                or '\0' in command or len(command) > 16000
                or type(timeout) is not int or not 1 <= timeout <= 3600
                or not isinstance(hosts, list) or not hosts
                or any(not isinstance(pattern, str) or not pattern for pattern in hosts)):
            raise ValueError(f'{CHECKS_CONFIG}: invalid or duplicate check {name!r}; '
                             'provide name, command, hosts, and a timeout from 1 to 3600 seconds')
        names.add(name)
        if any(fnmatch.fnmatchcase(host, pattern) for pattern in hosts):
            checks.append(SavedCheck(name, command, timeout))
    return checks


def action_arguments(selection):
    if not isinstance(selection, HostAction):
        return []
    if selection.mode == 'check':
        return ['--check', selection.check]
    return ['--' + selection.mode]


def connect_selection(selection, transport=None):
    if isinstance(selection, HostAction):
        return connect(selection.host, transport, mode=selection.mode, check=selection.check)
    return connect(selection, transport)


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


def prepare_editor_credentials(host, login, bridge, env, *, check_installation=False):
    """Prepare private credentials, or return False when integration is absent."""
    script = remote_bootstrap.prepare_credentials_script(
        bridge, check_installation=check_installation)
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
    script = remote_bootstrap.cleanup_script(bridge)
    try:
        subprocess.run([*ssh_base(host, login), '-T', '-n', '-o', 'ClearAllForwardings=yes',
                        '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
                        '--', host, 'sh -c ' + shlex.quote(script)], env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


def terminal_supports_rgb(env):
    """Recognize local terminal hints without guessing from xterm-256color."""
    if env.get('TERM_PROGRAM') == 'Apple_Terminal':
        return False  # Older Terminal.app versions use the same TERM name.
    return bool(env.get('WT_SESSION')) or env.get('COLORTERM', '').lower() in ('truecolor', '24bit')


def ssh_command(host, login=None, bridge=None, *, mode='normal', check=None, rgb=False):
    args = [*ssh_base(host, login), '-t']
    if bridge:
        # Keep the forwarding and its local bridge owned by this SSH window.
        if sys.platform != 'win32':
            args += ['-S', 'none']
        # Both transports must refuse an occupied or disallowed forward.
        args += ['-R', bridge.forward_spec, '-o', 'ExitOnForwardFailure=yes']
    return [*args, '--', host,
            'sh -c ' + shlex.quote(remote_bootstrap.session_script(
                bridge, mode=mode, check=check, rgb=rgb))]


def connect(host, transport=None, *, mode='normal', check=None):
    env = dict(os.environ)
    rgb = sys.stdout.isatty() and terminal_supports_rgb(env)
    env['TERM'] = 'xterm-256color'
    env.pop('TMUX', None)
    env.pop('TMUX_PANE', None)
    env.pop(SOCKET_ENV, None)
    env.pop(TOKEN_ENV, None)
    try:
        options = {'rgb': True} if rgb else {}
        if mode != 'normal':
            options['mode'] = mode
        if mode == 'check':
            selected = next((item for item in saved_checks(host) if item.name == check), None)
            if selected is None:
                raise ValueError(f'No saved check {check!r} is configured for {host}')
            options['check'] = selected
        login = None
        user = configured_login(host)
        if user is None:
            while not login:
                value = input(f'SSH login for {host}: ').strip()
                if valid_host(value) and '@' not in value and '/' not in value:
                    login = value
                else:
                    print('Enter a username, such as alice.')
        if sys.platform == 'win32':
            from .windows import ssh as terminal
        else:
            from .linux import ssh_picker as terminal
        terminal.set_terminal_title(f'{login or user}@{host.rsplit("@", 1)[-1]}')
        print(f'Connecting to {host} …', flush=True)
        destination = f'{login}@{host}' if login else host
        bridge = EditorBridge(destination, env, transport)
        status = 1
        prepared = None
        try:
            prepared = prepare_editor_credentials(host, login, bridge, env, check_installation=True)
            if prepared:
                with bridge:
                    status = subprocess.run(ssh_command(host, login, bridge, **options), env=env).returncode
            else:
                status = subprocess.run(ssh_command(host, login, **options), env=env).returncode
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
                        help='Choose a host in a full-screen grid and connect here (Windows default)')
    action.add_argument('--list', action='store_true', help='Print the host list without connecting')
    session = parser.add_mutually_exclusive_group()
    session.add_argument('--plain', action='store_true', help='With --connect: bypass tmux')
    session.add_argument('--ops', action='store_true', help='With --connect: open three ops panes')
    session.add_argument('--check', metavar='NAME', help='With --connect: run a saved check, then a shell')
    parser.add_argument('--refresh-hosts', action='store_true',
                        help='Recompute the picker host list instead of using its cache')
    parser.add_argument('--bridge', choices=('unix', 'tcp'),
                        help='Desktop editor bridge listener; the server side is always a '
                             'private Unix socket (default: TCP on Windows, Unix socket elsewhere)')
    parser.add_argument('--terminal-type', default='',
                        help='macOS: the tmux client terminal type; iTerm2 opens iTerm2, otherwise Terminal.app')
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error('Python 3.11 or newer is required.')
    if args.connect and args.refresh_hosts:
        parser.error('--refresh-hosts cannot be used with --connect')
    if (args.plain or args.ops or args.check is not None) and not args.connect:
        parser.error('--plain, --ops and --check require --connect HOST')
    refresh_options = {'refresh': True} if args.refresh_hosts else {}
    if args.connect:
        selection = args.connect
        if args.plain or args.ops or args.check is not None:
            mode = 'plain' if args.plain else 'ops' if args.ops else 'check'
            selection = HostAction(args.connect, mode, args.check)
        return connect_selection(selection, args.bridge)
    if args.list:
        print('\n'.join(target_hosts(**refresh_options)))
        return 0
    if sys.platform == 'win32' or args.pick:
        try:
            host = pick_host(**refresh_options)
            return connect_selection(host, args.bridge) if host else 0
        except KeyboardInterrupt:
            return 130
        except (OSError, RuntimeError, UnicodeError) as error:
            print(f'Could not choose an SSH host: {error}', file=sys.stderr)
            return 1
    from .linux import ssh_picker
    return ssh_picker.run_picker(parser, **refresh_options, terminal_type=args.terminal_type)


if __name__ == '__main__':
    raise SystemExit(main())
