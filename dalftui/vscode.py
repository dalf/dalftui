"""Open a pane's folder locally, or relay it through its SSH client's private socket."""
import argparse
import os
from pathlib import Path
import queue
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import quote

from bridge_protocol import (
    TOKEN_BYTES, error_message, parse_endpoint,
    parse_request, parse_response, read_message, request_message, send_message,
    success_message, valid_token, validate_folder,
)
# Preserve these public aliases used by existing bridge callers.
from bridge_protocol import MAX_REQUEST, SOCKET_ENV, TOKEN_ENV  # pylint: disable=unused-import
REQUEST_TIMEOUT = 3
RESPONSE_TIMEOUT = 3
LAUNCH_TIMEOUT = 15
CLIENT_TIMEOUT = 20
MAX_CONNECTIONS = 8
WINDOWS = sys.platform == 'win32'


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
        from .windows import vscode as windows_vscode
        return windows_vscode.windows_code_command(env)
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
        self.token = secrets.token_hex(TOKEN_BYTES)
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
            operation = parse_request(message)
            if self.stopped.is_set():
                return
            launch(operation.folder, self.destination, self.env, runner=self.run_editor)
            response = success_message()
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            response = error_message(error)
        if not self.stopped.is_set():
            try:
                # The request's remaining time must not become the response budget.
                connection.settimeout(RESPONSE_TIMEOUT)
                send_message(connection, response)
            except (OSError, ValueError):
                pass

    def run_editor(self, command, *, env, timeout, **_kwargs):
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


def request(socket_path, folder, token=None):
    validate_folder(folder)
    transport, address = parse_endpoint(socket_path)
    tcp = transport == 'tcp'
    if not valid_token(token):
        raise RuntimeError('Missing or invalid editor bridge credentials. '
                           'Reconnect using the dalftui SSH launcher.')
    try:
        with socket.socket(socket.AF_INET if tcp else socket.AF_UNIX) as connection:
            connection.settimeout(CLIENT_TIMEOUT)
            connection.connect(address)
            send_message(connection, request_message(folder, token))
            response = read_message(connection, deadline=time.monotonic() + CLIENT_TIMEOUT)
    except OSError as error:
        forwarding = 'TCP forwarding' if tcp else 'Unix socket forwarding'
        raise RuntimeError('Cannot reach local VS Code. Reconnect using the dalftui SSH launcher. '
                           f'The SSH server must allow {forwarding}.') from error
    parse_response(response)


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
            from .linux import tmux_editor
            tmux_editor.open_pane(args.pane, args.client)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        message = f'VS Code: {error}'
        print(message, file=sys.stderr)
        if args.folder:
            return 1
        tmux_editor.notify_error(message, args.client_tty)
        return 1
    return 0


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    raise SystemExit(main())
