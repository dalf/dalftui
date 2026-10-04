"""Open a pane's folder locally, or relay it through its SSH client's private socket."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from urllib.parse import quote

SOCKET_ENV = 'DALFTUI_EDITOR_SOCKET'
TOKEN_ENV = 'DALFTUI_EDITOR_TOKEN'
MAX_REQUEST = 16384
WINDOWS = sys.platform == 'win32'


def validate_folder(folder):
    if not isinstance(folder, str) or not folder.startswith('/') or '\0' in folder:
        raise ValueError('The editor folder must be an absolute path.')


def folder_uri(folder, destination=None):
    if destination:
        validate_folder(folder)
        authority = quote('ssh-remote+' + destination, safe='+@')
        return 'vscode-remote://' + authority + quote(folder, safe='/')
    # Local Windows folders may start with a drive letter or a UNC share.
    if not isinstance(folder, str) or '\0' in folder or not Path(folder).is_absolute():
        raise ValueError('The editor folder must be an absolute path.')
    return Path(folder).as_uri()


def code_command(env):
    """Use the native CLI on Windows to preserve URIs without cmd.exe expansion."""
    executable = shutil.which('code', path=env.get('PATH', os.defpath))
    if not executable:
        raise RuntimeError('VS Code was not found. Install its code command on your computer.')
    if WINDOWS:
        path = Path(executable).resolve()
        root = path.parent.parent if path.suffix.lower() in ('.cmd', '.bat') else path.parent
        application = root / 'Code.exe'
        cli = root / 'resources/app/out/cli.js'
        if not application.is_file() or not cli.is_file():
            raise RuntimeError('Cannot find the Windows VS Code installation behind the code command.')
        env['ELECTRON_RUN_AS_NODE'] = '1'
        env.pop('VSCODE_DEV', None)
        return [str(application), str(cli)]
    return [executable]


def launch(folder, destination=None, env=None):
    env = dict(os.environ if env is None else env)
    command = code_command(env)
    for name in ('TMUX', 'TMUX_PANE', 'VSCODE_IPC_HOOK_CLI'):
        env.pop(name, None)
    result = subprocess.run([*command, '--new-window', '--folder-uri', folder_uri(folder, destination)],
                            env=env, capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=15)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Could not start VS Code.')


def read_message(connection):
    data = bytearray()
    while len(data) <= MAX_REQUEST:
        chunk = connection.recv(min(4096, MAX_REQUEST + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
        if b'\n' in chunk:
            break
    if len(data) > MAX_REQUEST or not data.endswith(b'\n'):
        raise ValueError('Invalid editor request.')
    message = json.loads(data)
    if not isinstance(message, dict):
        raise ValueError('Invalid editor request.')
    return message


def send_message(connection, message):
    connection.sendall(json.dumps(message).encode() + b'\n')


class EditorBridge:
    """One private bridge and fixed destination per SSH window."""
    def __init__(self, destination, env=None, transport=None):
        self.destination = destination
        self.env = dict(os.environ if env is None else env)
        self.transport = transport or ('tcp' if WINDOWS else 'unix')
        if self.transport not in ('unix', 'tcp'):
            raise ValueError('Unknown editor bridge transport.')
        self.token = secrets.token_hex(32) if self.transport == 'tcp' else None
        if self.transport == 'tcp':
            self.remote_port = 49152 + secrets.randbelow(16384)
            self.remote_socket = f'tcp:127.0.0.1:{self.remote_port}'
            self.remote_token_file = '/tmp/dalftui-editor-' + secrets.token_hex(16) + '.token'
        else:
            self.remote_socket = '/tmp/dalftui-editor-' + secrets.token_hex(16) + '.sock'

    @property
    def forward_spec(self):
        if self.transport == 'tcp':
            return f'127.0.0.1:{self.remote_port}:127.0.0.1:{self.local_port}'
        return f'{self.remote_socket}:{self.local_socket}'

    def __enter__(self):
        self.directory = None
        self.local_socket = None
        if self.transport == 'tcp':
            self.listener = socket.socket(socket.AF_INET)
        else:
            self.directory = tempfile.TemporaryDirectory(prefix='dalftui-editor-', dir='/tmp')
            self.local_socket = str(Path(self.directory.name) / 'editor.sock')
            self.listener = socket.socket(socket.AF_UNIX)
        try:
            if self.transport == 'tcp':
                self.listener.bind(('127.0.0.1', 0))
                self.local_port = self.listener.getsockname()[1]
            else:
                self.listener.bind(self.local_socket)
                os.chmod(self.local_socket, 0o600)
            self.listener.listen(4)
            self.listener.settimeout(0.2)
            self.stopped = threading.Event()
            self.thread = threading.Thread(target=self.serve, daemon=True)
            self.thread.start()
        except BaseException:
            self.listener.close()
            if self.directory:
                self.directory.cleanup()
            raise
        return self

    def serve(self):
        while not self.stopped.is_set():
            try:
                connection, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with connection:
                connection.settimeout(3)
                try:
                    message = read_message(connection)
                    if self.token:
                        supplied = message.get('token')
                        if (not isinstance(supplied, str)
                                or not secrets.compare_digest(supplied.encode(), self.token.encode())):
                            raise ValueError('Invalid editor request authentication.')
                    launch(message.get('folder'), self.destination, self.env)
                    response = {'ok': True}
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                    response = {'error': str(error)}
                try:
                    send_message(connection, response)
                except OSError:
                    pass

    def __exit__(self, *args):
        self.stopped.set()
        self.listener.close()
        self.thread.join(timeout=18)
        if self.directory:
            self.directory.cleanup()


def request(socket_path, folder, token=None):
    validate_folder(folder)
    tcp = socket_path.startswith('tcp:')
    if tcp:
        match = re.fullmatch(r'tcp:127\.0\.0\.1:([0-9]+)', socket_path)
        if not match or not 0 < int(match[1]) < 65536:
            raise ValueError('Invalid loopback editor endpoint.')
        if not token:
            raise RuntimeError('Missing editor bridge token. Reconnect using the dalftui SSH launcher.')
    try:
        with socket.socket(socket.AF_INET if tcp else socket.AF_UNIX) as connection:
            connection.settimeout(20)
            connection.connect(('127.0.0.1', int(match[1])) if tcp else socket_path)
            message = {'folder': folder}
            if tcp:
                message['token'] = token
            send_message(connection, message)
            response = read_message(connection)
    except OSError as error:
        forwarding = 'TCP forwarding' if tcp else 'Unix socket forwarding'
        raise RuntimeError('Cannot reach local VS Code. Reconnect using the dalftui SSH launcher. '
                           f'The SSH server must allow {forwarding}.') from error
    if response.get('ok') is not True:
        raise RuntimeError(response.get('error') or 'The VS Code request failed.')


def client_environment(pid):
    # A persistent tmux server/session can retain another client's old SSH socket.
    # Read the triggering attach client's initial environment instead.
    values = Path(f'/proc/{pid}/environ').read_bytes().split(b'\0')
    return dict(os.fsdecode(item).split('=', 1) for item in values if b'=' in item)


def open_pane(pane, client):
    result = subprocess.run(['tmux', 'display-message', '-p', '-t', pane, '#{pane_current_path}'],
                            capture_output=True, text=True, check=True, timeout=5)
    folder = result.stdout.removesuffix('\n')
    env = client_environment(client)
    if env.get(SOCKET_ENV):
        request(env[SOCKET_ENV], folder, env.get(TOKEN_ENV))
    elif env.get('SSH_CONNECTION') or env.get('SSH_CLIENT'):
        raise RuntimeError('For remote VS Code, reconnect using the dalftui SSH launcher '
                           'in your local dalftui terminal.')
    else:
        launch(folder, env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--pane')
    target.add_argument('--folder', help='Open an absolute local folder, including on Windows')
    parser.add_argument('--client', type=int)
    parser.add_argument('--client-tty')
    args = parser.parse_args()
    if args.pane and args.client is None:
        parser.error('--client is required with --pane')
    try:
        if args.folder:
            launch(args.folder)
        else:
            open_pane(args.pane, args.client)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        message = f'VS Code: {error}'
        print(message, file=sys.stderr)
        if args.folder:
            return 1
        command = ['tmux', 'display-message', '-d', '8000']
        if args.client_tty:
            command += ['-c', args.client_tty]
        try:
            subprocess.run([*command, message.replace('#', '##')], timeout=5, check=False)
        except (OSError, subprocess.SubprocessError):
            pass
        return 1
    return 0


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
