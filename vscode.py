"""Open a pane's folder locally, or relay it through its SSH client's private socket."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from urllib.parse import quote

SOCKET_ENV = 'DALFTUI_EDITOR_SOCKET'
MAX_REQUEST = 16384


def folder_uri(folder, destination=None):
    if not isinstance(folder, str) or not folder.startswith('/') or '\0' in folder:
        raise ValueError('The editor folder must be an absolute path.')
    if destination:
        authority = quote('ssh-remote+' + destination, safe='+@')
        return 'vscode-remote://' + authority + quote(folder, safe='/')
    return Path(folder).as_uri()


def launch(folder, destination=None, env=None):
    env = dict(os.environ if env is None else env)
    executable = shutil.which('code', path=env.get('PATH', os.defpath))
    if not executable:
        raise RuntimeError('VS Code was not found. Install its code command on your computer.')
    for name in ('TMUX', 'TMUX_PANE', 'VSCODE_IPC_HOOK_CLI'):
        env.pop(name, None)
    result = subprocess.run([executable, '--new-window', '--folder-uri', folder_uri(folder, destination)],
                            env=env, capture_output=True, text=True, timeout=15)
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
    """One local socket and fixed SSH destination per SSH window; no TCP listener."""
    def __init__(self, destination, env=None):
        self.destination = destination
        self.env = dict(os.environ if env is None else env)
        self.remote_socket = '/tmp/dalftui-editor-' + secrets.token_hex(16) + '.sock'

    def __enter__(self):
        self.directory = tempfile.TemporaryDirectory(prefix='dalftui-editor-', dir='/tmp')
        self.local_socket = str(Path(self.directory.name) / 'editor.sock')
        self.listener = socket.socket(socket.AF_UNIX)
        try:
            self.listener.bind(self.local_socket)
            os.chmod(self.local_socket, 0o600)
            self.listener.listen(4)
            self.listener.settimeout(0.2)
            self.stopped = threading.Event()
            self.thread = threading.Thread(target=self.serve, daemon=True)
            self.thread.start()
        except BaseException:
            self.listener.close()
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
        self.directory.cleanup()


def request(socket_path, folder):
    folder_uri(folder)  # Validate before sending anything.
    try:
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(20)
            connection.connect(socket_path)
            send_message(connection, {'folder': folder})
            response = read_message(connection)
    except OSError as error:
        raise RuntimeError('Cannot reach local VS Code. Reopen the SSH window with Ctrl+B, F2. '
                           'The SSH server must allow Unix socket forwarding.') from error
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
        request(env[SOCKET_ENV], folder)
    elif env.get('SSH_CONNECTION') or env.get('SSH_CLIENT'):
        raise RuntimeError('For remote VS Code, reopen this connection using Ctrl+B, F2 '
                           'in your local dalftui terminal.')
    else:
        launch(folder, env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pane', required=True)
    parser.add_argument('--client', required=True, type=int)
    parser.add_argument('--client-tty')
    args = parser.parse_args()
    try:
        open_pane(args.pane, args.client)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        message = f'VS Code: {error}'
        print(message, file=sys.stderr)
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
