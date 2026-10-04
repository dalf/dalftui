"""Check the bridge contract against frozen peers, not two matching new peers."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bridge_protocol as protocol
from dalftui import vscode
from dalftui.linux import remote_bootstrap
from dalftui.windows import vscode as windows_vscode

spec = importlib.util.spec_from_file_location(
    'frozen_bridge_protocol_v1', Path(__file__).parent / 'fixtures/bridge_protocol_v1.py')
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)

bootstrap_spec = importlib.util.spec_from_file_location(
    'frozen_ssh_bootstrap_v1', Path(__file__).parent / 'fixtures/ssh_bootstrap_v1.py')
historical_bootstrap = importlib.util.module_from_spec(bootstrap_spec)
bootstrap_spec.loader.exec_module(historical_bootstrap)


@unittest.skipIf(sys.platform == 'win32', 'Remote bootstrap executes in a POSIX shell')
class BootstrapCompatibilityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='dalftui-bootstrap-compatibility-')
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.home = self.directory / "remote home's $cash ; é"
        self.home.mkdir()
        self.bin = self.directory / 'bin'
        self.bin.mkdir()
        for command in ('sh', 'stat', 'id', 'mkdir', 'cat', 'rm', 'rmdir'):
            (self.bin / command).symlink_to(shutil.which(command))
        (self.bin / 'python3').symlink_to(sys.executable)
        tmux = self.bin / 'tmux'
        tmux.write_text('#!/bin/sh\nexit 0\n')
        tmux.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.home), XDG_CONFIG_HOME='', PATH=str(self.bin))

    def run_script(self, script, *, token=None):
        return subprocess.run([str(self.bin / 'sh'), '-c', script],
                              input=token, env=self.env, cwd=self.directory,
                              capture_output=True, text=True, timeout=5)

    def bridge(self, transport):
        directory = self.directory / (transport + " credentials' $cash ; é")
        # No bridge object or current protocol helpers construct this peer.
        return SimpleNamespace(transport=transport, remote_directory=str(directory),
                               remote_owner_file=str(directory / 'claim.owner'),
                               remote_token_file=str(directory / 'token'),
                               remote_socket=(str(directory / 'editor.sock') if transport == 'unix'
                                              else 'tcp:127.0.0.1:49152'))

    def install_historical(self):
        checkout = self.directory / 'historical root checkout'
        (checkout / 'config').mkdir(parents=True)
        # The frozen historical editor occupies the old public root path. The
        # probe requires readable integration files and a standalone declaration.
        shutil.copy2(Path(__file__).parent / 'fixtures/bridge_protocol_v1.py',
                     checkout / 'vscode.py')
        (checkout / 'config/tmux.conf').write_text('# Historical editor integration\n')
        (checkout / 'bridge_protocol.py').write_text(historical_bootstrap.PROTOCOL_DECLARATION)
        installed = self.home / '.config/dalftui'
        installed.parent.mkdir()
        installed.symlink_to(checkout, target_is_directory=True)
        return checkout

    def test_frozen_old_desktop_probe_recognizes_current_remote_installation(self):
        for config_home in ('', 'relative-config', str(self.directory / "custom config's $cash ; é")):
            with self.subTest(config_home=config_home):
                self.env['XDG_CONFIG_HOME'] = config_home
                config = Path(config_home) if config_home.startswith('/') else self.home / '.config'
                installed = config / 'dalftui'
                installed.parent.mkdir(parents=True, exist_ok=True)
                if not installed.is_symlink():
                    installed.symlink_to(ROOT, target_is_directory=True)
                result = self.run_script(historical_bootstrap.REMOTE_EDITOR_CHECK)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout + result.stderr, '')

    def test_current_desktop_probe_and_setup_recognize_supported_historical_root_installation(self):
        self.install_historical()
        for transport in ('unix', 'tcp'):
            with self.subTest(transport=transport):
                bridge = self.bridge(transport)
                result = self.run_script(remote_bootstrap.prepare_credentials_script(
                    bridge, check_installation=True), token=legacy.TOKEN + '\n')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout + result.stderr, '')
                self.assertEqual(Path(bridge.remote_token_file).read_text(), legacy.TOKEN + '\n')
                self.assertTrue(Path(bridge.remote_owner_file).is_file())
                cleanup = self.run_script(remote_bootstrap.cleanup_script(bridge))
                self.assertEqual(cleanup.returncode, 0, cleanup.stderr)
                self.assertFalse(Path(bridge.remote_directory).exists())

    def test_current_desktop_refuses_credentials_without_a_supported_readable_declaration(self):
        checkout = self.install_historical()
        declaration = checkout / 'bridge_protocol.py'
        cases = (('undeclared', None), ('unreadable', None),
                 ('unsupported', 'print(999)\n'), ('malformed', 'print("unknown")\n'),
                 ('failed', 'raise SystemExit(1)\n'))
        for name, content in cases:
            declaration.unlink(missing_ok=True)
            if name == 'unreadable':
                declaration.symlink_to(checkout / 'missing-declaration.py')
            elif content is not None:
                declaration.write_text(content)
            for transport in ('unix', 'tcp'):
                with self.subTest(declaration=name, transport=transport):
                    bridge = self.bridge(transport)
                    result = self.run_script(remote_bootstrap.prepare_credentials_script(
                        bridge, check_installation=True), token=legacy.TOKEN + '\n')
                    self.assertEqual(result.returncode, 4, result.stderr)
                    self.assertEqual(result.stdout + result.stderr, '')
                    self.assertFalse(Path(bridge.remote_directory).exists())


class MemoryConnection:
    """Socket-shaped stream for codec checks, with realistic recv size limits."""
    def __init__(self, data=b'', *, fragment_size=None):
        self.data = bytearray(data)
        self.fragment_size = fragment_size
        self.sent = bytearray()
        self.timeouts = []
        self.reads = 0

    def recv(self, size):
        self.reads += 1
        if self.fragment_size is not None:
            size = min(size, self.fragment_size)
        result = bytes(self.data[:size])
        del self.data[:size]
        return result

    def sendall(self, data):
        self.sent.extend(data)

    def settimeout(self, value):
        self.timeouts.append(value)


class FrozenPeerTests(unittest.TestCase):
    def old_laptop(self, *, launch_error=None):
        """A real TCP listener running only the frozen server implementation."""
        listener = socket.socket(socket.AF_INET)
        self.addCleanup(listener.close)
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        listener.settimeout(5)
        outcome = {}

        def serve():
            try:
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(5)
                    outcome['message'] = legacy.serve_connection(
                        connection, legacy.TOKEN, launch_error=launch_error)
            except BaseException as error:
                outcome['error'] = error

        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        self.addCleanup(worker.join, 6)
        return f'tcp:127.0.0.1:{listener.getsockname()[1]}', worker, outcome

    def assert_old_laptop_finished(self, worker, outcome):
        worker.join(6)
        self.assertFalse(worker.is_alive(), 'The historical server did not finish.')
        if 'error' in outcome:
            raise outcome['error']
        self.assertIn('message', outcome)

    def test_old_remote_client_opens_folder_on_current_laptop(self):
        with patch.object(vscode, 'launch') as launch:
            with vscode.EditorBridge('alice@fixed-server', transport='tcp') as bridge:
                legacy.request(f'tcp:127.0.0.1:{bridge.local_port}',
                               legacy.FOLDER, bridge.token)
                launch.assert_called_once()
                args, kwargs = launch.call_args
                self.assertEqual(args[0], legacy.FOLDER)
                self.assertEqual(args[1], 'alice@fixed-server')
                self.assertIs(kwargs['runner'].__self__, bridge)

    def test_old_remote_client_reads_current_laptop_error(self):
        with patch.object(vscode, 'launch', side_effect=RuntimeError('Editor unavailable.')):
            with vscode.EditorBridge('server', transport='tcp') as bridge:
                with self.assertRaisesRegex(RuntimeError, 'Editor unavailable'):
                    legacy.request(f'tcp:127.0.0.1:{bridge.local_port}',
                                   legacy.FOLDER, bridge.token)

    def test_old_remote_client_uses_current_configured_windows_editor(self):
        with tempfile.TemporaryDirectory(prefix='dalftui-historical-windows-') as directory:
            root = Path(directory).resolve()
            application = root / "VS Code's %PATH% & é" / 'Code.exe'
            cli = application.parent / 'resources/app/out/cli.js'
            cli.parent.mkdir(parents=True)
            cli.touch()
            application.touch()
            local_app_data = root / 'local application data'
            config = local_app_data / windows_vscode.WINDOWS_CONFIG
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({'code': str(application)}, ensure_ascii=False),
                              encoding='utf-8-sig')
            env = dict(LOCALAPPDATA=str(local_app_data), PATH='untrusted-alternative',
                       VSCODE_DEV='1', TMUX='stale', TMUX_PANE='%9',
                       VSCODE_IPC_HOOK_CLI='stale')
            original_env = dict(env)
            with (patch.object(vscode, 'WINDOWS', True),
                  patch.object(windows_vscode, 'windows_code_command',
                               wraps=windows_vscode.windows_code_command) as select,
                  patch.object(vscode.shutil, 'which', side_effect=AssertionError('unsafe discovery'))):
                with vscode.EditorBridge('alice@fixed-server', env, transport='tcp') as bridge:
                    with patch.object(bridge, 'run_editor',
                                      return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
                        legacy.request(f'tcp:127.0.0.1:{bridge.local_port}',
                                       legacy.FOLDER, bridge.token)
                    select.assert_called_once()
                    run.assert_called_once()
                    self.assertEqual(run.call_args.args[0],
                                     [str(application), str(cli), '--new-window', '--folder-uri',
                                      'vscode-remote://ssh-remote+alice@fixed-server/'
                                      'home/alice/project.with.dot%20%22quoted%22%20'
                                      '%24cash%20%23%3F%C3%A9'])
                    selected_env = run.call_args.kwargs['env']
                    self.assertEqual(selected_env,
                                     {'LOCALAPPDATA': str(local_app_data),
                                      'PATH': 'untrusted-alternative', 'ELECTRON_RUN_AS_NODE': '1'})
                    self.assertFalse(run.call_args.kwargs.get('shell', False))
                    self.assertEqual(run.call_args.kwargs['timeout'], vscode.LAUNCH_TIMEOUT)
                    self.assertEqual(bridge.env, original_env)
            self.assertEqual(env, original_env)

    def test_current_remote_client_opens_folder_on_old_laptop(self):
        endpoint, worker, outcome = self.old_laptop()
        vscode.request(endpoint, legacy.FOLDER, legacy.TOKEN)
        self.assert_old_laptop_finished(worker, outcome)
        self.assertEqual(outcome['message']['folder'], legacy.FOLDER)
        self.assertEqual(outcome['message']['token'], legacy.TOKEN)
        # The old server must ignore the newly explicit v1 metadata.
        self.assertEqual(outcome['message']['protocol_version'], 1)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Client routing reads Linux /proc')
    def test_root_editor_entrypoint_routes_client_credentials_to_old_laptop(self):
        with tempfile.TemporaryDirectory(prefix='dalftui-historical-entrypoint-') as directory:
            root = Path(directory).resolve()
            checkout = root / "checkout's $cash ; é"
            for relative in ('vscode.py', 'bridge_protocol.py', 'dalftui/__init__.py',
                             'dalftui/vscode.py', 'dalftui/linux/__init__.py',
                             'dalftui/linux/tmux_editor.py'):
                destination = checkout / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, destination)
            outside = root / 'unrelated directory'
            outside.mkdir()
            binary = root / 'bin'
            binary.mkdir()
            tmux = binary / 'tmux'
            tmux.write_text("#!/bin/sh\n"
                            "[ \"$#\" -eq 5 ] && [ \"$1\" = display-message ] &&\n"
                            "[ \"$2\" = -p ] && [ \"$3\" = -t ] && [ \"$4\" = %7 ] &&\n"
                            "[ \"$5\" = '#{pane_current_path}' ] || exit 99\n"
                            "printf '%s\\n' \"$TEST_PANE_FOLDER\"\n")
            tmux.chmod(0o755)
            endpoint, worker, outcome = self.old_laptop()
            client_env = dict(os.environ, DALFTUI_EDITOR_SOCKET=endpoint,
                              DALFTUI_EDITOR_TOKEN=legacy.TOKEN, SSH_CONNECTION='remote')
            client_env.pop('PYTHONPATH', None)
            # /proc exposes the attach client's initial environment. Keep a
            # separate disposable client alive with credentials supplied at exec.
            client = subprocess.Popen([sys.executable, '-I', '-c',
                                       'import sys; sys.stdin.buffer.read()'],
                                      stdin=subprocess.PIPE, env=client_env)
            try:
                command_env = dict(client_env, PATH=str(binary), TEST_PANE_FOLDER=legacy.FOLDER,
                                   DALFTUI_EDITOR_SOCKET='tcp:127.0.0.1:0',
                                   DALFTUI_EDITOR_TOKEN='wrong-client-token')
                result = subprocess.run(
                    [sys.executable, str(checkout / 'vscode.py'), '--pane', '%7',
                     '--client', str(client.pid), '--client-tty', '/dev/pts/probe'],
                    cwd=outside, env=command_env, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertEqual(result.stderr, '')
                self.assert_old_laptop_finished(worker, outcome)
                self.assertEqual(outcome['message']['folder'], legacy.FOLDER)
                self.assertEqual(outcome['message']['token'], legacy.TOKEN)
                self.assertEqual(outcome['message']['protocol_version'], 1)
            finally:
                client.stdin.close()
                client.wait(timeout=5)

    def test_current_remote_client_reads_old_laptop_error(self):
        endpoint, worker, outcome = self.old_laptop(launch_error='Historical editor error.')
        with self.assertRaisesRegex(RuntimeError, 'Historical editor error'):
            vscode.request(endpoint, legacy.FOLDER, legacy.TOKEN)
        self.assert_old_laptop_finished(worker, outcome)

    def test_maximum_legacy_folder_request_still_reaches_old_laptop(self):
        seed = {'folder': '/', 'token': legacy.TOKEN}
        size = len(json.dumps(seed).encode('utf-8')) + 1
        folder = '/' + 'x' * (16384 - size)
        self.assertEqual(len(json.dumps(dict(seed, folder=folder)).encode('utf-8')) + 1,
                         16384)

        endpoint, worker, outcome = self.old_laptop()
        vscode.request(endpoint, folder, legacy.TOKEN)
        self.assert_old_laptop_finished(worker, outcome)
        self.assertEqual(outcome['message'], {'folder': folder, 'token': legacy.TOKEN})
        # Adding optional metadata must not make a previously valid v1 request
        # exceed the deployed peer's fixed limit. Missing metadata still means v1.
        self.assertEqual(protocol.parse_request(outcome['message']).protocol_version, 1)

    def test_current_laptop_rejects_unknown_protocol_before_launch(self):
        with patch.object(vscode, 'launch') as launch:
            with vscode.EditorBridge('server', transport='tcp') as bridge:
                with socket.create_connection(('127.0.0.1', bridge.local_port), timeout=5) as connection:
                    legacy.send_message(connection, {'folder': legacy.FOLDER,
                                                     'token': bridge.token,
                                                     'protocol_version': 999})
                    response = legacy.read_message(connection)
                self.assertIn('error', response)
                with self.assertRaisesRegex(RuntimeError, 'protocol'):
                    protocol.parse_response(response)
                launch.assert_not_called()


class ContractTests(unittest.TestCase):
    def test_version_and_credential_environment_names_are_deployed_v1(self):
        self.assertEqual(protocol.PROTOCOL_VERSION, 1)
        self.assertEqual(protocol.SUPPORTED_PROTOCOL_VERSIONS, frozenset({1}))
        self.assertEqual(protocol.SOCKET_ENV, 'DALFTUI_EDITOR_SOCKET')
        self.assertEqual(protocol.TOKEN_ENV, 'DALFTUI_EDITOR_TOKEN')
        self.assertEqual(protocol.SOCKET_ENV, legacy.SOCKET_ENV)
        self.assertEqual(protocol.TOKEN_ENV, legacy.TOKEN_ENV)

    def test_cli_reports_version_without_loading_editor_or_picker(self):
        result = subprocess.run([sys.executable, '-I', str(ROOT / 'bridge_protocol.py'), '--version'],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '1\n')
        self.assertEqual(result.stderr, '')

    def test_historical_request_and_responses_remain_readable(self):
        decoded = protocol.read_message(MemoryConnection(legacy.REQUEST_LINE, fragment_size=7))
        request = protocol.parse_request(decoded)
        self.assertEqual(request.folder, legacy.FOLDER)
        self.assertEqual(request.token, legacy.TOKEN)
        self.assertEqual(request.protocol_version, 1)
        protocol.parse_response(protocol.read_message(MemoryConnection(legacy.SUCCESS_LINE)))
        with self.assertRaisesRegex(RuntimeError, 'Could not start VS Code'):
            protocol.parse_response(protocol.read_message(MemoryConnection(legacy.ERROR_LINE)))

    def test_current_messages_are_understood_by_frozen_decoder(self):
        messages = [protocol.request_message(legacy.FOLDER, legacy.TOKEN),
                    protocol.success_message(), protocol.error_message('Editor failed.')]
        for message in messages:
            with self.subTest(message=message):
                connection = MemoryConnection()
                protocol.send_message(connection, message)
                self.assertTrue(connection.sent.endswith(b'\n'))
                self.assertEqual(legacy.read_message(MemoryConnection(connection.sent)), message)
                self.assertEqual(message['protocol_version'], 1)

    def test_explicit_v1_and_optional_unknown_fields_preserve_request(self):
        request = protocol.parse_request({'folder': legacy.FOLDER, 'token': legacy.TOKEN,
                                         'protocol_version': 1,
                                         'destination': 'untrusted-server',
                                         'future_optional_metadata': {'ignored': True}})
        self.assertEqual((request.folder, request.token, request.protocol_version),
                         (legacy.FOLDER, legacy.TOKEN, 1))
        with self.assertRaises((AttributeError, TypeError)):
            request.folder = '/mutated'

    def test_unsupported_or_malformed_request_versions_fail_closed(self):
        for version in (0, 2, -1, 999, True, False, '1', 1.0, None, [], {}):
            with self.subTest(version=version):
                with self.assertRaises(protocol.IncompatibleProtocolError):
                    protocol.parse_request({'folder': legacy.FOLDER, 'token': legacy.TOKEN,
                                            'protocol_version': version})

    def test_unsupported_or_malformed_response_versions_fail_closed(self):
        for version in (0, 2, -1, 999, True, False, '1', 1.0, None, [], {}):
            for response in ({'ok': True}, {'error': 'Editor failed.'}):
                with self.subTest(version=version, response=response):
                    with self.assertRaises(protocol.IncompatibleProtocolError):
                        protocol.parse_response(dict(response, protocol_version=version))

    def test_legacy_and_versioned_response_semantics(self):
        for metadata in ({}, {'protocol_version': 1}):
            with self.subTest(metadata=metadata):
                self.assertIsNone(protocol.parse_response(dict(metadata, ok=True,
                                                              future_optional_field='ignored')))
                with self.assertRaisesRegex(RuntimeError, 'Permission denied'):
                    protocol.parse_response(dict(metadata, error='Permission denied.'))
                for bad_ok in (False, 1, 'true', None):
                    with self.subTest(ok=bad_ok):
                        with self.assertRaises(ValueError):
                            protocol.parse_response(dict(metadata, ok=bad_ok))

    def test_token_format_is_exact_lowercase_256_bit_hex(self):
        self.assertTrue(protocol.valid_token(legacy.TOKEN))
        invalid = (None, True, 1, [], {}, '', 'a' * 63, 'a' * 65,
                   'A' * 64, 'é' * 64, 'a' * 64 + '\n', '\ud800', 'g' * 64)
        for token in invalid:
            with self.subTest(token=token):
                self.assertFalse(protocol.valid_token(token))
                with self.assertRaises((ValueError, RuntimeError)):
                    protocol.request_message(legacy.FOLDER, token)
                with self.assertRaises(ValueError):
                    protocol.parse_request({'folder': legacy.FOLDER, 'token': token})

    def test_remote_folder_is_an_absolute_posix_path_and_preserves_text(self):
        for folder in ('/', legacy.FOLDER, '/srv/with\nnewline', '/srv/../project'):
            with self.subTest(folder=folder):
                protocol.validate_folder(folder)
                self.assertEqual(protocol.parse_request(
                    {'folder': folder, 'token': legacy.TOKEN}).folder, folder)
        for folder in (None, True, 1, [], {}, '', 'relative', 'C:\\project', '/has\0null'):
            with self.subTest(folder=folder):
                with self.assertRaises(ValueError):
                    protocol.validate_folder(folder)
                with self.assertRaises(ValueError):
                    protocol.request_message(folder, legacy.TOKEN)
                with self.assertRaises(ValueError):
                    protocol.parse_request({'folder': folder, 'token': legacy.TOKEN})

    def test_only_loopback_tcp_endpoints_are_accepted(self):
        for port in (1, 49152, 65535):
            with self.subTest(port=port):
                self.assertEqual(protocol.parse_endpoint(f'tcp:127.0.0.1:{port}'),
                                 ('tcp', ('127.0.0.1', port)))
        endpoints = ('tcp:127.0.0.1:0', 'tcp:127.0.0.1:65536', 'tcp:127.0.0.1:-1',
                     'tcp:127.0.0.1:22\n', 'tcp:localhost:22', 'tcp:0.0.0.0:22',
                     'tcp:192.0.2.1:22', 'tcp:[::1]:22', 'tcp:127.0.0.1:abc')
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(ValueError):
                    protocol.parse_endpoint(endpoint)
        self.assertEqual(protocol.parse_endpoint('/tmp/é space/editor.sock'),
                         ('unix', '/tmp/é space/editor.sock'))

    def test_utf8_json_line_framing_is_preserved(self):
        message = {'folder': legacy.FOLDER, 'token': legacy.TOKEN}
        line = json.dumps(message, ensure_ascii=False).encode('utf-8') + b'\n'
        self.assertEqual(protocol.read_message(MemoryConnection(line, fragment_size=1)), message)
        invalid_lines = (b'', b'{}', b'[]\n', b'null\n', b'not json\n',
                         b'{}\n{}\n', b'{"folder":"\xff"}\n')
        for line in invalid_lines:
            with self.subTest(line=line):
                with self.assertRaises((ValueError, UnicodeError)):
                    protocol.read_message(MemoryConnection(line))

    def test_utf16_and_utf32_json_lines_are_outside_the_utf8_contract(self):
        for encoding in ('utf-16-be', 'utf-32-be'):
            with self.subTest(encoding=encoding):
                line = '{}\n'.encode(encoding)
                # Big endian input ends with a literal newline byte, so the
                # framing check alone cannot enforce the declared UTF-8 codec.
                self.assertTrue(line.endswith(b'\n'))
                self.assertEqual(legacy.read_message(MemoryConnection(line)), {})
                with self.assertRaises((ValueError, UnicodeError)):
                    protocol.read_message(MemoryConnection(line))

    def test_exact_16384_byte_legacy_limit_includes_newline(self):
        message = {'folder': legacy.FOLDER, 'token': legacy.TOKEN, 'padding': ''}
        size = len(json.dumps(message).encode()) + 1
        message['padding'] = 'x' * (16384 - size)
        line = json.dumps(message).encode() + b'\n'
        self.assertEqual(len(line), 16384)
        self.assertEqual(protocol.read_message(MemoryConnection(line)), message)
        self.assertEqual(legacy.read_message(MemoryConnection(line)), message)
        oversized = line[:-3] + b'x' + line[-3:]
        self.assertEqual(len(oversized), 16385)
        with self.assertRaises(ValueError):
            protocol.read_message(MemoryConnection(oversized))

    def test_outbound_limit_includes_newline_and_rejects_before_sending(self):
        message = protocol.request_message(legacy.FOLDER, legacy.TOKEN)
        message['padding'] = ''
        size = len(json.dumps(message).encode('utf-8')) + 1
        message['padding'] = 'x' * (16384 - size)
        connection = MemoryConnection()
        protocol.send_message(connection, message)
        self.assertEqual(len(connection.sent), 16384)
        self.assertTrue(connection.sent.endswith(b'\n'))
        self.assertEqual(legacy.read_message(MemoryConnection(connection.sent)), message)

        message['padding'] += 'x'
        self.assertEqual(len(json.dumps(message).encode('utf-8')) + 1, 16385)
        connection = MemoryConnection()
        with self.assertRaises(ValueError):
            protocol.send_message(connection, message)
        self.assertEqual(connection.sent, b'')

    def test_maximum_legacy_error_keeps_v1_semantics_without_optional_metadata(self):
        size = len(json.dumps({'error': ''}).encode('utf-8')) + 1
        error = 'x' * (16384 - size)
        message = protocol.error_message(error)
        self.assertEqual(message, {'error': error})
        connection = MemoryConnection()
        protocol.send_message(connection, message)
        self.assertEqual(len(connection.sent), 16384)
        decoded = legacy.read_message(MemoryConnection(connection.sent))
        self.assertEqual(decoded, {'error': error})
        with self.assertRaises(RuntimeError) as caught:
            protocol.parse_response(decoded)
        self.assertEqual(str(caught.exception), error)

    def test_deadline_expiration_is_checked_before_reading(self):
        connection = MemoryConnection(legacy.REQUEST_LINE)
        with patch.object(protocol.time, 'monotonic', return_value=100.0):
            with self.assertRaises(TimeoutError):
                protocol.read_message(connection, deadline=100.0)
        self.assertEqual(connection.reads, 0)

    def test_deadline_expiration_is_checked_after_reading(self):
        connection = MemoryConnection(legacy.REQUEST_LINE)
        with patch.object(protocol.time, 'monotonic', side_effect=[100.0, 101.0]):
            with self.assertRaises(TimeoutError):
                protocol.read_message(connection, deadline=101.0)
        self.assertEqual(connection.timeouts, [1.0])


if __name__ == '__main__':
    unittest.main()
