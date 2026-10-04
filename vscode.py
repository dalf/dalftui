"""Open a pane's folder locally, or relay it through its SSH client's private socket."""
import argparse
import json
import os
from pathlib import Path
import queue
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import quote

SOCKET_ENV = 'DALFTUI_EDITOR_SOCKET'
TOKEN_ENV = 'DALFTUI_EDITOR_TOKEN'
MAX_REQUEST = 16384
REQUEST_TIMEOUT = 3
RESPONSE_TIMEOUT = 3
LAUNCH_TIMEOUT = 15
CLIENT_TIMEOUT = 20
MAX_CONNECTIONS = 8
WINDOWS = sys.platform == 'win32'
WINDOWS_CONFIG = Path('dalftui') / 'config.json'


def windows_code_command(env):
    """Load the absolute VS Code application selected by Windows setup."""
    recovery = ("Rerun dalftui's setup-windows.ps1. For a portable installation, "
                "pass -VSCodePath with its directory or Code.exe path.")
    local_app_data = env.get('LOCALAPPDATA')
    if not local_app_data or not Path(local_app_data).is_absolute():
        raise RuntimeError(f'VS Code is not configured. {recovery}')
    config_path = Path(local_app_data) / WINDOWS_CONFIG
    try:
        config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        raise RuntimeError(f'VS Code is not configured. {recovery}') from None
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f'Cannot read the VS Code configuration at {config_path}. '
                           f'{recovery}') from error
    application_value = config.get('code') if isinstance(config, dict) else None
    if not isinstance(application_value, str) or '\0' in application_value:
        raise RuntimeError(f'The VS Code configuration at {config_path} is invalid. {recovery}')
    application = Path(application_value)
    if not application.is_absolute() or application.name.lower() != 'code.exe':
        raise RuntimeError(f'The VS Code configuration at {config_path} is invalid. {recovery}')
    cli = application.parent / 'resources/app/out/cli.js'
    if not application.is_file() or not cli.is_file():
        raise RuntimeError(f'The configured VS Code installation is missing: {application}. '
                           f'{recovery}')
    env['ELECTRON_RUN_AS_NODE'] = '1'
    env.pop('VSCODE_DEV', None)
    return [str(application), str(cli)]


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
    if WINDOWS:
        return windows_code_command(env)
    executable = shutil.which('code', path=env.get('PATH', os.defpath))
    if not executable:
        raise RuntimeError('VS Code was not found. Install its code command on your computer.')
    return [executable]


def launch(folder, destination=None, env=None, *, runner=None):
    env = dict(os.environ if env is None else env)
    command = code_command(env)
    for name in ('TMUX', 'TMUX_PANE', 'VSCODE_IPC_HOOK_CLI'):
        env.pop(name, None)
    run = subprocess.run if runner is None else runner
    result = run([*command, '--new-window', '--folder-uri', folder_uri(folder, destination)],
                 env=env, capture_output=True, text=True, encoding='utf-8',
                 errors='replace', timeout=LAUNCH_TIMEOUT)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Could not start VS Code.')


def read_message(connection, *, deadline=None):
    """Read one bounded JSON line, optionally before an absolute monotonic deadline."""
    data = bytearray()
    while len(data) <= MAX_REQUEST:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Editor request deadline expired.')
            connection.settimeout(remaining)
        chunk = connection.recv(min(4096, MAX_REQUEST + 1 - len(data)))
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError('Editor request deadline expired.')
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
    def __init__(self, destination, env=None, transport=None, *,
                 request_timeout=REQUEST_TIMEOUT, max_connections=MAX_CONNECTIONS):
        if request_timeout <= 0 or max_connections < 1:
            raise ValueError('Editor bridge limits must be positive.')
        self.request_timeout = request_timeout
        self.max_connections = max_connections
        self.destination = destination
        self.env = dict(os.environ if env is None else env)
        self.transport = transport or ('tcp' if WINDOWS else 'unix')
        if self.transport not in ('unix', 'tcp'):
            raise ValueError('Unknown editor bridge transport.')
        self.token = secrets.token_hex(32)
        self.remote_directory = '/tmp/dalftui-editor-' + secrets.token_hex(16)
        self.remote_token_file = self.remote_directory + '/token'
        # A separate, non-secret claim lets cleanup refuse a pre-existing directory.
        self.remote_owner_file = self.remote_directory + '/' + secrets.token_hex(16) + '.owner'
        if self.transport == 'tcp':
            self.remote_port = 49152 + secrets.randbelow(16384)
            self.remote_socket = f'tcp:127.0.0.1:{self.remote_port}'
        else:
            self.remote_socket = self.remote_directory + '/editor.sock'

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
            self.listener.listen(self.max_connections)
            self.listener.settimeout(0.2)
            self.stopped = threading.Event()
            # Admission and process creation share the shutdown lock. There is no
            # unbounded submission queue, and queued sockets count toward capacity.
            self.lock = threading.Lock()
            self.connections = set()
            self.processes = set()
            self.pending = queue.Queue(maxsize=self.max_connections)
            self.workers = []
            for _ in range(self.max_connections):
                worker = threading.Thread(target=self.work, daemon=True)
                worker.start()
                self.workers.append(worker)
            self.thread = threading.Thread(target=self.serve, daemon=True)
            self.thread.start()
        except BaseException:
            self.__exit__()
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
            deadline = time.monotonic() + self.request_timeout
            with self.lock:
                if self.stopped.is_set() or len(self.connections) >= self.max_connections:
                    # At most one extra accepted socket exists while being rejected.
                    connection.close()
                    continue
                self.connections.add(connection)
                self.pending.put_nowait((connection, deadline))

    def work(self):
        while not self.stopped.is_set():
            try:
                connection, deadline = self.pending.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.handle(connection, deadline)
            finally:
                with self.lock:
                    connection.close()
                    self.connections.discard(connection)
                self.pending.task_done()

    def handle(self, connection, deadline):
        try:
            message = read_message(connection, deadline=deadline)
            supplied = message.get('token')
            if (not valid_token(supplied)
                    or not secrets.compare_digest(supplied, self.token)):
                raise ValueError('Invalid editor bridge credentials. '
                                 'Reconnect using the dalftui SSH launcher.')
            if self.stopped.is_set():
                return
            launch(message.get('folder'), self.destination, self.env, runner=self.run_editor)
            response = {'ok': True}
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            response = {'error': str(error)}
        if not self.stopped.is_set():
            try:
                # The request's remaining time must not become the response budget.
                connection.settimeout(RESPONSE_TIMEOUT)
                send_message(connection, response)
            except OSError:
                pass

    def run_editor(self, command, *, env, timeout, **kwargs):
        """Start under the shutdown lock; wait outside it so accepts stay independent."""
        # A file avoids pipe-reader threads or inherited pipes delaying shutdown.
        with tempfile.TemporaryFile() as stderr:
            with self.lock:
                if self.stopped.is_set():
                    raise RuntimeError('The editor bridge has stopped.')
                process = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL,
                                           stderr=stderr)
                self.processes.add(process)
            try:
                returncode = process.wait(timeout=timeout)
            finally:
                try:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=1)
                finally:
                    with self.lock:
                        self.processes.discard(process)
            stderr.seek(0)
            return subprocess.CompletedProcess(command, returncode, '',
                                               stderr.read().decode('utf-8', errors='replace'))

    @staticmethod
    def close_socket(connection):
        # close() alone need not interrupt recv() in another thread on every OS.
        try:
            connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        connection.close()

    def __exit__(self, *args):
        if hasattr(self, 'lock'):
            with self.lock:
                self.stopped.set()
                self.close_socket(self.listener)
                for connection in self.connections:
                    self.close_socket(connection)
                for process in self.processes:
                    try:
                        process.kill()
                    except OSError:
                        pass
            # The accept thread closes a socket accepted just before shutdown if
            # it had not yet registered it. No admission or launch can follow stop.
            if hasattr(self, 'thread') and self.thread.ident is not None:
                self.thread.join()
            for worker in self.workers:
                worker.join()
            while not self.pending.empty():
                self.pending.get_nowait()
                self.pending.task_done()
            self.connections.clear()
        else:
            self.listener.close()
        if self.directory:
            self.directory.cleanup()


def valid_token(token):
    return isinstance(token, str) and re.fullmatch(r'[0-9a-f]{64}', token) is not None


def request(socket_path, folder, token=None):
    validate_folder(folder)
    tcp = socket_path.startswith('tcp:')
    if tcp:
        match = re.fullmatch(r'tcp:127\.0\.0\.1:([0-9]+)', socket_path)
        if not match or not 0 < int(match[1]) < 65536:
            raise ValueError('Invalid loopback editor endpoint.')
    if not valid_token(token):
        raise RuntimeError('Missing or invalid editor bridge credentials. '
                           'Reconnect using the dalftui SSH launcher.')
    try:
        with socket.socket(socket.AF_INET if tcp else socket.AF_UNIX) as connection:
            connection.settimeout(CLIENT_TIMEOUT)
            connection.connect(('127.0.0.1', int(match[1])) if tcp else socket_path)
            send_message(connection, {'folder': folder, 'token': token})
            response = read_message(connection, deadline=time.monotonic() + CLIENT_TIMEOUT)
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
