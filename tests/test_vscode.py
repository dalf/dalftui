"""Verify editor routing, private sockets, and the Alacritty shortcut through tmux."""
import importlib.util
import json
import os
from pathlib import Path
import select
import shlex
import stat
import subprocess
import sys
import termios
import time
import unittest
from unittest.mock import patch

from test_install import DisposableSetup, TmuxFixture, ROOT
from alacritty_config import load
import vscode

spec = importlib.util.spec_from_file_location('editor_picker', ROOT / 'ssh-picker.py')
picker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(picker)


class EditorTests(DisposableSetup):
    def setUp(self):
        super().setUp()
        self.log = self.directory / 'editor.json'
        self.bin = self.directory / 'bin'
        self.bin.mkdir()
        code = self.bin / 'code'
        code.write_text(f'#!{sys.executable}\nimport json, os, pathlib, sys\n'
                        'pathlib.Path(os.environ["EDITOR_TEST_LOG"]).write_text(json.dumps(sys.argv[1:]))\n')
        code.chmod(0o755)
        self.editor_env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'],
                               EDITOR_TEST_LOG=str(self.log))

    def test_local_folder_names_are_passed_as_one_encoded_uri(self):
        folder = "/tmp/project.with.dot 'quoted' $cash #?é"
        vscode.launch(folder, env=self.editor_env)
        self.assertEqual(json.loads(self.log.read_text()),
                         ['--new-window', '--folder-uri', Path(folder).as_uri()])

    def test_bridge_uses_its_fixed_destination_and_cleans_up(self):
        folder = "/home/alice/project.with.dot 'quoted' $cash #?é"
        with vscode.EditorBridge('alice@server', self.editor_env) as bridge:
            path = Path(bridge.local_socket)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            vscode.request(str(path), folder)
            self.assertEqual(json.loads(self.log.read_text()),
                             ['--new-window', '--folder-uri',
                              'vscode-remote://ssh-remote+alice@server/home/alice/'
                              'project.with.dot%20%27quoted%27%20%24cash%20%23%3F%C3%A9'])
        self.assertFalse(path.exists())
        self.assertFalse(path.parent.exists())

    def test_invalid_requests_do_not_launch_and_bridge_still_works(self):
        with vscode.EditorBridge('server', self.editor_env) as bridge:
            for folder in ('relative', None, '/has\0null'):
                with self.subTest(folder=folder):
                    import socket
                    with socket.socket(socket.AF_UNIX) as connection:
                        connection.connect(bridge.local_socket)
                        vscode.send_message(connection, {'folder': folder})
                        self.assertIn('error', vscode.read_message(connection))
            self.assertFalse(self.log.exists())
            vscode.request(bridge.local_socket, '/valid')
            self.assertTrue(self.log.exists())

    def test_ssh_command_keeps_alias_login_and_forwarding_separate(self):
        with vscode.EditorBridge('alice@server', self.editor_env) as bridge:
            args = picker.ssh_command('server', 'alice', bridge)
            self.assertEqual(args[args.index('-R') + 1],
                             bridge.remote_socket + ':' + bridge.local_socket)
            self.assertEqual(args[args.index('-l') + 1], 'alice')
            self.assertEqual(args[args.index('--') + 1], 'server')
            self.assertIn(bridge.remote_socket, shlex.split(args[-1])[2])

    def test_remote_session_policy_and_forwarded_socket_cleanup(self):
        tmux = self.bin / 'tmux'
        tmux.write_text('#!/bin/sh\n'
                        'if [ "$1" = list-sessions ]; then printf "%s" "$TEST_SESSIONS"; exit; fi\n'
                        'if [ "$1" = has-session ]; then exit 0; fi\n'
                        'printf "%s\\n" "$DALFTUI_EDITOR_SOCKET" > "$TEST_SOCKET_ENV"\n'
                        'printf "%s\\n" "$@" > "$TEST_TMUX_ARGS"\n')
        tmux.chmod(0o755)
        for sessions, selection, expected in [('', '', ['new-session', '-A', '-s', '0']),
                                              ('$5 0\n', '', ['attach-session', '-t', '$5']),
                                              ('$5 1\n', '', ['new-session']),
                                              ('$5 0\n$9 1\n', '$9\n',
                                               ['attach-session', '-t', '$9'])]:
            with self.subTest(sessions=sessions):
                socket_file = self.directory / 'remote.sock'
                socket_file.touch()
                bridge = type('Bridge', (), {'remote_socket': str(socket_file),
                                             'local_socket': '/tmp/local.sock'})()
                command = shlex.split(picker.ssh_command('server', bridge=bridge)[-1])
                env = dict(self.editor_env, TEST_SESSIONS=sessions,
                           TEST_SOCKET_ENV=str(self.directory / 'socket-env'),
                           TEST_TMUX_ARGS=str(self.directory / 'tmux-args'))
                subprocess.run(command, env=env, input=selection, text=True, check=True,
                               capture_output=True, timeout=5)
                self.assertEqual((self.directory / 'tmux-args').read_text().splitlines(), expected)
                self.assertEqual((self.directory / 'socket-env').read_text().strip(), str(socket_file))
                self.assertFalse(socket_file.exists())

    def test_plain_remote_ssh_does_not_try_to_launch_a_remote_gui(self):
        cwd = subprocess.CompletedProcess(['tmux'], 0, '/home/alice/project\n', '')
        with patch.object(vscode, 'client_environment', return_value={'SSH_CONNECTION': 'remote'}):
            with patch.object(vscode.subprocess, 'run', return_value=cwd):
                with patch.object(vscode, 'launch') as launch:
                    with self.assertRaisesRegex(RuntimeError, 'local dalftui terminal'):
                        vscode.open_pane('%0', 123)
                    launch.assert_not_called()


class EditorTmuxTests(TmuxFixture):
    def setUp(self):
        super().setUp()
        self.log = self.directory / 'editor.json'
        self.bin = self.directory / 'bin'
        self.bin.mkdir()
        code = self.bin / 'code'
        code.write_text(f'#!{sys.executable}\nimport json, os, pathlib, sys\n'
                        'pathlib.Path(os.environ["EDITOR_TEST_LOG"]).write_text(json.dumps(sys.argv[1:]))\n')
        code.chmod(0o755)
        self.editor_env = dict(self.env, PATH=str(self.bin) + ':' + os.environ['PATH'],
                               EDITOR_TEST_LOG=str(self.log), TERM='xterm-256color')
        self.editor_env.pop('SSH_CONNECTION', None)
        self.editor_env.pop('SSH_CLIENT', None)
        self.editor_env.pop(vscode.SOCKET_ENV, None)

    def attach(self, env):
        master, slave = os.openpty()
        termios.tcsetwinsize(slave, (40, 140))
        process = subprocess.Popen([*self.command, 'attach-session', '-t', 'verify'],
                                   stdin=slave, stdout=slave, stderr=slave,
                                   env=env, start_new_session=True)
        os.close(slave)
        def cleanup():
            process.terminate()
            process.wait(timeout=5)
            os.close(master)
        self.addCleanup(cleanup)
        until = time.monotonic() + 5
        while time.monotonic() < until:
            clients = self.tmux('list-clients', '-F', '#{client_pid}')
            if str(process.pid) in clients.splitlines():
                time.sleep(0.2)
                return process, master
            time.sleep(0.05)
        self.fail('The tmux client did not attach')

    def press_f3(self, master):
        binding = next(item for item in load(self.repo / 'config/alacritty.toml')['keyboard']['bindings']
                       if item['key'] == 'F3' and item['mods'] == 'Control|Shift')
        os.write(master, binding['chars'].encode())
        until = time.monotonic() + 5
        while time.monotonic() < until:
            if self.log.exists():
                return json.loads(self.log.read_text())
            if select.select([master], [], [], 0.05)[0]:
                os.read(master, 65536)
        self.fail('F3 did not open the editor')

    def prepare_pane(self):
        self.start()
        self.do_reload()
        folder = self.directory / "project.with.dot 'quoted' $cash #?é"
        folder.mkdir()
        self.tmux('new-window', '-c', str(folder), '-n', 'editor', 'sleep 600')
        return folder

    def test_f3_opens_local_active_pane_folder_with_client_environment(self):
        folder = self.prepare_pane()
        _, master = self.attach(self.editor_env)
        self.assertEqual(self.press_f3(master), ['--new-window', '--folder-uri', folder.as_uri()])

    def test_f3_routes_each_attached_client_to_its_own_bridge(self):
        folder = self.prepare_pane()
        with vscode.EditorBridge('first-server', self.editor_env) as first:
            with vscode.EditorBridge('second-server', self.editor_env) as second:
                _, master1 = self.attach(dict(self.editor_env, SSH_CONNECTION='remote',
                                              DALFTUI_EDITOR_SOCKET=first.local_socket))
                _, master2 = self.attach(dict(self.editor_env, SSH_CONNECTION='remote',
                                              DALFTUI_EDITOR_SOCKET=second.local_socket))
                for master, destination in ((master1, 'first-server'), (master2, 'second-server')):
                    self.log.unlink(missing_ok=True)
                    self.assertEqual(self.press_f3(master),
                                     ['--new-window', '--folder-uri', vscode.folder_uri(str(folder), destination)])

    def test_f3_uses_tcp_endpoint_and_token_from_its_ssh_client(self):
        folder = self.prepare_pane()
        with vscode.EditorBridge('windows-vm', self.editor_env, transport='tcp') as bridge:
            _, master = self.attach(dict(self.editor_env, SSH_CONNECTION='remote',
                                          DALFTUI_EDITOR_SOCKET=f'tcp:127.0.0.1:{bridge.local_port}',
                                          DALFTUI_EDITOR_TOKEN=bridge.token))
            self.assertEqual(self.press_f3(master),
                             ['--new-window', '--folder-uri', vscode.folder_uri(str(folder), 'windows-vm')])


if __name__ == '__main__':
    unittest.main()
