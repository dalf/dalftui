"""Windows-compatible connection tests; no curses, tmux, or desktop GUI required."""
import importlib.util
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import vscode


def load_picker(name='windows_picker'):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'ssh-picker.py')
    picker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(picker)
    return picker


picker = load_picker()


class WindowsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='dalftui-windows-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()

    def test_connect_cli_imports_without_curses(self):
        with patch.dict(sys.modules, {'curses': None}):
            module = load_picker('no_curses_picker')
        self.assertIsNone(module.curses)
        with patch.object(module, 'connect', return_value=0) as connect:
            with patch.object(sys, 'argv', ['ssh-picker.py', '--connect', 'vm-alias']):
                self.assertEqual(module.main(), 0)
        connect.assert_called_once_with('vm-alias', None)

    def test_windows_defaults_to_authenticated_tcp(self):
        with patch.object(vscode, 'WINDOWS', True):
            with vscode.EditorBridge('vm-alias') as bridge:
                self.assertEqual(bridge.transport, 'tcp')
                self.assertEqual(bridge.listener.getsockname()[0], '127.0.0.1')
                self.assertIsNone(bridge.directory)
                self.assertIsNone(bridge.local_socket)
                self.assertEqual(len(bridge.token), 64)

    def test_tcp_rejects_unauthenticated_requests_and_still_handles_valid_ones(self):
        opened = []
        with patch.object(vscode, 'launch', side_effect=lambda *args: opened.append(args)):
            with vscode.EditorBridge('vm-alias', transport='tcp') as bridge:
                for token in (None, 'wrong', 123, 'é'):
                    with self.subTest(token=token):
                        with socket.create_connection(('127.0.0.1', bridge.local_port), timeout=5) as connection:
                            vscode.send_message(connection, {'folder': '/project', 'token': token})
                            self.assertIn('error', vscode.read_message(connection))
                self.assertFalse(opened)
                vscode.request(f'tcp:127.0.0.1:{bridge.local_port}', '/project', bridge.token)
                self.assertEqual(opened[0][:2], ('/project', 'vm-alias'))

    def test_tcp_listener_is_closed_when_the_connection_ends(self):
        with vscode.EditorBridge('vm-alias', transport='tcp') as bridge:
            address = bridge.listener.getsockname()
        with self.assertRaises(OSError):
            socket.create_connection(address, timeout=1)

    def test_tcp_client_rejects_non_loopback_endpoints(self):
        for endpoint in ('tcp:0.0.0.0:1234', 'tcp:example.org:1234', 'tcp:127.0.0.1:0',
                         'tcp:127.0.0.1:70000'):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(ValueError):
                    vscode.request(endpoint, '/project', 'token')

    def test_windows_cli_avoids_batch_shell_and_preserves_encoded_folder_uri(self):
        install = self.root / 'VS Code with spaces %percent%'
        cli = install / 'resources/app/out/cli.js'
        cli.parent.mkdir(parents=True)
        cli.touch()
        app = install / 'Code.exe'
        app.touch()
        batch = install / 'bin/code.cmd'
        batch.parent.mkdir()
        batch.write_text('@echo off\n')
        folder = "/home/alice/project.with.dot 'quoted' %PATH% & #?é"
        result = subprocess.CompletedProcess(['Code.exe'], 0, '', '')
        with patch.object(vscode, 'WINDOWS', True):
            with patch.object(vscode.shutil, 'which', return_value=str(batch)):
                with patch.object(vscode.subprocess, 'run', return_value=result) as run:
                    vscode.launch(folder, 'alice@vm-alias', {'PATH': 'test', 'VSCODE_DEV': '1'})
        self.assertEqual(run.call_args.args[0],
                         [str(app), str(cli), '--new-window', '--folder-uri',
                          vscode.folder_uri(folder, 'alice@vm-alias')])
        self.assertFalse(run.call_args.kwargs.get('shell', False))
        self.assertEqual(run.call_args.kwargs['env']['ELECTRON_RUN_AS_NODE'], '1')
        self.assertNotIn('VSCODE_DEV', run.call_args.kwargs['env'])

    def test_token_setup_sends_secret_on_stdin_and_not_in_process_arguments(self):
        result = subprocess.CompletedProcess(['ssh'], 0)
        with vscode.EditorBridge('vm-alias', transport='tcp') as bridge:
            with patch.object(picker.subprocess, 'run', return_value=result) as run:
                picker.prepare_tcp_token('vm-alias', 'alice', bridge, {})
            self.assertEqual(run.call_args.kwargs['input'], (bridge.token + '\n').encode('ascii'))
            self.assertFalse(run.call_args.kwargs.get('text', False))
            self.assertIn('-T', run.call_args.args[0])
            self.assertNotIn(bridge.token, ' '.join(run.call_args.args[0]))
            self.assertIn('umask 077', run.call_args.args[0][-1])
            command = picker.ssh_command('vm-alias', 'alice', bridge)
            self.assertNotIn(bridge.token, ' '.join(command))
            self.assertEqual(command[command.index('-R') + 1], bridge.forward_spec)
            self.assertIn(bridge.remote_token_file, command[-1])
            self.assertIn('ExitOnForwardFailure=yes', command)

    def test_configured_username_and_unset_username_use_real_ssh_config(self):
        if not shutil.which(picker.ssh_executable()):
            self.skipTest('OpenSSH is not installed')
        picker.secure_ssh_directory(self.root)
        config = self.root / 'ssh config with spaces'
        config.write_text('Host vm-alias\n    HostName 127.0.0.1\n    User alice\n')
        with patch.object(picker, 'SSH_CONFIG', config):
            self.assertEqual(picker.configured_login('vm-alias'), 'alice')
            self.assertIsNone(picker.configured_login('another-alias'))


if __name__ == '__main__':
    unittest.main()
