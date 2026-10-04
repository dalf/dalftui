"""Verify editor routing, private sockets, and the Alacritty shortcut through tmux."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import select
import shlex
import signal
import socket
import stat
import subprocess
import sys
import tempfile
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
            vscode.request(str(path), folder, bridge.token)
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
                    with socket.socket(socket.AF_UNIX) as connection:
                        connection.connect(bridge.local_socket)
                        vscode.send_message(connection, {'folder': folder, 'token': bridge.token})
                        self.assertIn('error', vscode.read_message(connection))
            self.assertFalse(self.log.exists())
            vscode.request(bridge.local_socket, '/valid', bridge.token)
            self.assertTrue(self.log.exists())

    def test_unix_bridge_rejects_protocol_changed_during_an_attachment(self):
        with vscode.EditorBridge('server', self.editor_env) as bridge:
            vscode.request(bridge.local_socket, '/before-update', bridge.token)
            self.assertTrue(self.log.exists())
            self.log.unlink()
            # An already running bridge must recheck every request: a remote
            # checkout can be updated while its SSH attachment remains open.
            with socket.socket(socket.AF_UNIX) as connection:
                connection.settimeout(5)
                connection.connect(bridge.local_socket)
                vscode.send_message(connection, {'folder': '/after-update',
                                                 'token': bridge.token,
                                                 'protocol_version': 999})
                response = vscode.read_message(connection)
                self.assertIn('protocol', response['error'].lower())
                self.assertNotIn(bridge.token, response['error'])
            self.assertFalse(self.log.exists())
            vscode.request(bridge.local_socket, '/still-supported', bridge.token)
            self.assertEqual(json.loads(self.log.read_text())[-1],
                             vscode.folder_uri('/still-supported', 'server'))

    def assert_unix_authentication(self, bridge):
        messages = [{'folder': '/project'}]
        messages += [{'folder': '/project', 'token': token} for token in
                     (None, '', '0' * 64, 'wrong', 123, True, [], {}, 'é' * 64,
                      '\ud800', bridge.token + '\n', bridge.token[:-1])]
        for message in messages:
            with self.subTest(token=message.get('token')):
                with socket.socket(socket.AF_UNIX) as connection:
                    connection.settimeout(5)
                    connection.connect(bridge.local_socket)
                    vscode.send_message(connection, message)
                    response = vscode.read_message(connection)
                    self.assertIn('Reconnect using the dalftui SSH launcher', response['error'])
                    self.assertNotIn(bridge.token, response['error'])
                self.assertFalse(self.log.exists())
        # The request cannot override the bridge's fixed destination.
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(5)
            connection.connect(bridge.local_socket)
            vscode.send_message(connection, {'folder': '/valid', 'token': bridge.token,
                                             'destination': 'other-server'})
            self.assertEqual(vscode.read_message(connection), {'ok': True, 'protocol_version': 1})
        self.assertEqual(json.loads(self.log.read_text())[-1],
                         vscode.folder_uri('/valid', bridge.destination))

    def test_unix_requires_authentication_and_recovers_after_invalid_tokens(self):
        with vscode.EditorBridge('fixed-server', self.editor_env) as bridge:
            self.assertEqual(len(bytes.fromhex(bridge.token)), 32)
            self.assert_unix_authentication(bridge)

    def test_reachable_permissive_unix_socket_still_requires_authentication(self):
        # This is a same-account reachability probe, not a cross-user/remote sshd test.
        with vscode.EditorBridge('fixed-server', self.editor_env) as bridge:
            Path(bridge.local_socket).parent.chmod(0o755)
            Path(bridge.local_socket).chmod(0o666)
            self.assertEqual(stat.S_IMODE(Path(bridge.local_socket).stat().st_mode), 0o666)
            self.assert_unix_authentication(bridge)

    def test_unix_bridges_have_separate_credentials(self):
        with vscode.EditorBridge('first-server', self.editor_env) as first:
            with vscode.EditorBridge('second-server', self.editor_env) as second:
                self.assertNotEqual(first.token, second.token)
                self.assertNotEqual(first.remote_directory, second.remote_directory)
                for target, other in ((first, second), (second, first)):
                    with self.assertRaisesRegex(RuntimeError, 'Reconnect using the dalftui SSH launcher'):
                        vscode.request(target.local_socket, '/project', other.token)
                    self.assertFalse(self.log.exists())
                for bridge in (first, second):
                    vscode.request(bridge.local_socket, '/project', bridge.token)
                    self.assertEqual(json.loads(self.log.read_text())[-1],
                                     vscode.folder_uri('/project', bridge.destination))

    def test_old_unix_attachments_fail_closed_with_reconnect_instructions(self):
        cwd = subprocess.CompletedProcess(['tmux'], 0, '/project\n', '')
        with vscode.EditorBridge('server', self.editor_env) as bridge:
            env = {vscode.SOCKET_ENV: bridge.local_socket, 'SSH_CONNECTION': 'remote'}
            with patch.object(vscode, 'client_environment', return_value=env):
                with patch.object(vscode.subprocess, 'run', return_value=cwd):
                    with patch.object(vscode.socket, 'socket') as connection:
                        with self.assertRaisesRegex(RuntimeError, 'Reconnect using the dalftui SSH launcher'):
                            vscode.open_pane('%0', 123)
                        connection.assert_not_called()
            self.assertFalse(self.log.exists())

    def test_ssh_command_keeps_alias_login_and_forwarding_separate(self):
        with vscode.EditorBridge('alice@server', self.editor_env) as bridge:
            args = picker.ssh_command('server', 'alice', bridge)
            self.assertEqual(args[args.index('-R') + 1],
                             bridge.remote_socket + ':' + bridge.local_socket)
            self.assertEqual(args[args.index('-l') + 1], 'alice')
            self.assertEqual(args[args.index('--') + 1], 'server')
            self.assertIn(bridge.remote_socket, shlex.split(args[-1])[2])
            self.assertEqual(bridge.transport, 'unix')
            self.assertTrue(bridge.token)
            self.assertNotIn('127.0.0.1:', args[args.index('-R') + 1])
            self.assertIn('ExitOnForwardFailure=yes', args)
            self.assertEqual(args[args.index('-S') + 1], 'none')

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
                bridge = vscode.EditorBridge('server', self.editor_env)
                bridge.local_socket = '/tmp/local.sock'
                bridge.remote_directory = str(self.directory / 'remote-bridge')
                bridge.remote_token_file = bridge.remote_directory + '/token'
                bridge.remote_owner_file = bridge.remote_directory + '/claim.owner'
                bridge.remote_socket = bridge.remote_directory + '/editor.sock'
                # Simulate only the SSH execution by running its sh command locally.
                real_run = subprocess.run
                def local_ssh(args, **kwargs):
                    return real_run(shlex.split(args[-1]), **kwargs, timeout=5)
                with patch.object(picker.subprocess, 'run', side_effect=local_ssh):
                    picker.prepare_editor_credentials('server', None, bridge, self.editor_env)
                socket_file = Path(bridge.remote_socket)
                socket_file.touch()
                command = shlex.split(picker.ssh_command('server', bridge=bridge)[-1])
                env = dict(self.editor_env, TEST_SESSIONS=sessions,
                           TEST_SOCKET_ENV=str(self.directory / 'socket-env'),
                           TEST_TMUX_ARGS=str(self.directory / 'tmux-args'))
                subprocess.run(command, env=env, input=selection, text=True, check=True,
                               capture_output=True, timeout=5)
                self.assertEqual((self.directory / 'tmux-args').read_text().splitlines(), expected)
                self.assertEqual((self.directory / 'socket-env').read_text().strip(), str(socket_file))
                self.assertFalse(socket_file.exists())
                self.assertFalse(Path(bridge.remote_token_file).exists())
                self.assertFalse(Path(bridge.remote_directory).exists())

    def test_plain_remote_ssh_does_not_try_to_launch_a_remote_gui(self):
        cwd = subprocess.CompletedProcess(['tmux'], 0, '/home/alice/project\n', '')
        with patch.object(vscode, 'client_environment', return_value={'SSH_CONNECTION': 'remote'}):
            with patch.object(vscode.subprocess, 'run', return_value=cwd):
                with patch.object(vscode, 'launch') as launch:
                    with self.assertRaisesRegex(RuntimeError, 'local dalftui terminal'):
                        vscode.open_pane('%0', 123)
                    launch.assert_not_called()


class RemoteCredentialsTests(unittest.TestCase):
    """Execute remote sh scripts locally; no SSH host or real tmux session is used."""
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='dalftui-credentials-')
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.bin = self.directory / 'bin'
        self.bin.mkdir()
        tmux = self.bin / 'tmux'
        tmux.write_text(f'#!{sys.executable}\nimport hashlib, json, os, pathlib, sys, time\n'
                        'if sys.argv[1] == "list-sessions": sys.exit(0)\n'
                        'pathlib.Path(os.environ["TEST_ATTACH"]).write_text(json.dumps({\n'
                        '"endpoint": os.environ["DALFTUI_EDITOR_SOCKET"],\n'
                        '"digest": hashlib.sha256(os.environ["DALFTUI_EDITOR_TOKEN"].encode()).hexdigest(),\n'
                        '"token_file_exists": pathlib.Path(os.environ["TEST_TOKEN_FILE"]).exists()}))\n'
                        'if os.environ.get("TEST_WAIT_SIGNAL"): time.sleep(30)\n'
                        'sys.exit(int(os.environ.get("TEST_TMUX_STATUS", "0")))\n')
        tmux.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'],
                        TEST_ATTACH=str(self.directory / 'attachment.json'))
        self.real_run = subprocess.run

    def bridge(self, transport='unix'):
        bridge = vscode.EditorBridge('server', transport=transport)
        bridge.remote_directory = str(self.directory / Path(bridge.remote_directory).name)
        bridge.remote_owner_file = bridge.remote_directory + '/' + Path(bridge.remote_owner_file).name
        bridge.remote_token_file = bridge.remote_directory + '/token'
        if transport == 'unix':
            bridge.remote_socket = bridge.remote_directory + '/editor.sock'
            bridge.local_socket = '/tmp/test-local.sock'
        else:
            bridge.local_port = 12345
        return bridge

    def local_ssh(self, args, **kwargs):
        self.assertNotIn('-R', args)
        kwargs.setdefault('stdout', subprocess.PIPE)
        kwargs.setdefault('stderr', subprocess.PIPE)
        kwargs.setdefault('timeout', 5)
        return self.real_run(shlex.split(args[-1]), **kwargs)

    def prepare(self, bridge):
        with patch.object(picker.subprocess, 'run', side_effect=self.local_ssh) as run:
            picker.prepare_editor_credentials('server', 'alice', bridge, self.env)
        return run.call_args

    def cleanup(self, bridge):
        with patch.object(picker.subprocess, 'run', side_effect=self.local_ssh) as run:
            picker.cleanup_editor_bridge('server', 'alice', bridge, self.env)
        self.assertIn('BatchMode=yes', run.call_args.args[0])
        self.assertNotIn(bridge.token, ' '.join(run.call_args.args[0]))

    def attach(self, bridge, **env):
        return self.real_run(shlex.split(picker.ssh_command('server', bridge=bridge)[-1]),
                             env=dict(self.env, TEST_TOKEN_FILE=bridge.remote_token_file, **env),
                             capture_output=True, timeout=5)

    def test_both_transports_deliver_private_credentials_on_stdin_before_forwarding(self):
        for transport in ('unix', 'tcp'):
            with self.subTest(transport=transport):
                bridge = self.bridge(transport)
                call = self.prepare(bridge)
                self.assertEqual(call.kwargs['input'], (bridge.token + '\n').encode('ascii'))
                self.assertNotIn(bridge.token, ' '.join(call.args[0]))
                self.assertNotIn(bridge.token, call.kwargs['env'].values())
                self.assertIn('ClearAllForwardings=yes', call.args[0])
                self.assertEqual(stat.S_IMODE(Path(bridge.remote_directory).stat().st_mode), 0o700)
                for filename in (bridge.remote_owner_file, bridge.remote_token_file):
                    self.assertEqual(stat.S_IMODE(Path(filename).stat().st_mode), 0o600)
                    self.assertEqual(Path(filename).stat().st_uid, os.getuid())
                self.assertEqual(Path(bridge.remote_token_file).read_text(), bridge.token + '\n')
                if transport == 'unix':
                    # Simulate sshd's bind locally before executing the command.
                    with socket.socket(socket.AF_UNIX) as forwarded:
                        forwarded.bind(bridge.remote_socket)
                result = self.attach(bridge, TEST_TMUX_STATUS='23', SHELL='/usr/bin/fish')
                self.assertEqual(result.returncode, 23, result.stderr)
                attachment = json.loads(Path(self.env['TEST_ATTACH']).read_text())
                self.assertEqual(attachment, {'endpoint': bridge.remote_socket,
                                             'digest': hashlib.sha256(bridge.token.encode()).hexdigest(),
                                             'token_file_exists': False})
                self.assertNotIn(bridge.token.encode(), result.stdout + result.stderr)
                self.assertFalse(Path(bridge.remote_directory).exists())

    def test_setup_and_cleanup_refuse_preexisting_directories_files_and_symlinks(self):
        for kind in ('directory', 'file', 'symlink'):
            with self.subTest(kind=kind):
                bridge = self.bridge()
                target = Path(bridge.remote_directory)
                victim = self.directory / (kind + '-victim')
                victim.mkdir()
                if kind == 'directory':
                    target.mkdir(mode=0o700)
                elif kind == 'file':
                    target.write_text('existing')
                else:
                    target.symlink_to(victim, target_is_directory=True)
                with self.assertRaisesRegex(RuntimeError, 'prepare.*credentials'):
                    self.prepare(bridge)
                self.cleanup(bridge)
                self.assertTrue(target.exists())
                self.assertEqual(list(victim.iterdir()), [])
                self.assertFalse(Path(bridge.remote_token_file).exists())

    def test_exclusive_token_creation_refuses_symlink_substitution(self):
        bridge = self.bridge()
        victim = self.directory / 'victim'
        victim.write_text('untouched')
        # Fault injection after mkdir, within our own account. Real other users
        # cannot create this link in the private directory.
        mkdir = self.bin / 'mkdir'
        mkdir.write_text('#!/bin/sh\n/bin/mkdir "$@" || exit\n'
                         'for directory do :; done\n'
                         'ln -s -- "$TEST_VICTIM" "$directory/token"\n')
        mkdir.chmod(0o755)
        self.env['TEST_VICTIM'] = str(victim)
        with self.assertRaises(RuntimeError):
            self.prepare(bridge)
        self.assertEqual(victim.read_text(), 'untouched')
        self.assertFalse(Path(bridge.remote_directory).exists())

    def test_partial_credential_delivery_failure_removes_only_its_directory(self):
        bridge = self.bridge()
        other = self.bridge()
        self.prepare(other)
        cat = self.bin / 'cat'
        cat.write_text('#!/bin/sh\nprintf partial\nexit 1\n')
        cat.chmod(0o755)
        with self.assertRaises(RuntimeError):
            self.prepare(bridge)
        self.assertFalse(Path(bridge.remote_directory).exists())
        self.assertTrue(Path(other.remote_token_file).exists())
        self.cleanup(other)
        self.assertFalse(Path(other.remote_directory).exists())

    def test_attach_rejects_missing_malformed_public_and_symlinked_credentials(self):
        for kind in ('missing', 'malformed', 'public', 'symlink'):
            with self.subTest(kind=kind):
                bridge = self.bridge()
                self.prepare(bridge)
                token_file = Path(bridge.remote_token_file)
                if kind == 'missing':
                    token_file.unlink()
                elif kind == 'malformed':
                    token_file.write_text('do-not-print-this-invalid-credential')
                elif kind == 'public':
                    token_file.chmod(0o644)
                else:
                    token_file.unlink()
                    victim = self.directory / 'symlink-credential-victim'
                    victim.write_text('untouched')
                    token_file.symlink_to(victim)
                result = self.attach(bridge)
                self.assertEqual(result.returncode, 1)
                self.assertIn(b'Reconnect using the dalftui SSH launcher', result.stderr)
                self.assertNotIn(b'do-not-print', result.stderr)
                self.assertNotIn(bridge.token.encode(), result.stdout + result.stderr)
                self.assertFalse(Path(self.env['TEST_ATTACH']).exists())
                self.assertFalse(Path(bridge.remote_directory).exists())
                if kind == 'symlink':
                    self.assertEqual(victim.read_text(), 'untouched')

    def test_cleanup_requires_private_owned_directory_and_claim(self):
        bridge = self.bridge()
        other = self.bridge()
        self.prepare(bridge)
        self.prepare(other)
        Path(bridge.remote_socket).touch()
        Path(bridge.remote_directory).chmod(0o755)
        result = self.attach(bridge)
        self.assertEqual(result.returncode, 1)
        self.cleanup(bridge)
        self.assertTrue(Path(bridge.remote_token_file).exists())
        self.assertTrue(Path(bridge.remote_socket).exists())
        Path(bridge.remote_directory).chmod(0o700)
        Path(bridge.remote_owner_file).chmod(0o644)
        self.cleanup(bridge)
        self.assertTrue(Path(bridge.remote_token_file).exists())
        Path(bridge.remote_owner_file).chmod(0o600)
        self.cleanup(bridge)
        self.assertFalse(Path(bridge.remote_directory).exists())
        self.assertTrue(Path(other.remote_token_file).exists())
        self.cleanup(other)

    def test_remote_signal_removes_consumed_credentials_and_forwarded_socket(self):
        for termination in (signal.SIGHUP, signal.SIGTERM):
            with self.subTest(signal=termination):
                bridge = self.bridge()
                self.prepare(bridge)
                with socket.socket(socket.AF_UNIX) as forwarded:
                    forwarded.bind(bridge.remote_socket)
                attached = Path(self.env['TEST_ATTACH'])
                attached.unlink(missing_ok=True)
                command = shlex.split(picker.ssh_command('server', bridge=bridge)[-1])
                process = subprocess.Popen(command, start_new_session=True,
                                           env=dict(self.env, TEST_TOKEN_FILE=bridge.remote_token_file,
                                                    TEST_WAIT_SIGNAL='yes'),
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    until = time.monotonic() + 5
                    while not attached.exists() and time.monotonic() < until:
                        time.sleep(0.02)
                    self.assertTrue(attached.exists(), 'The fake tmux client did not start')
                    self.assertFalse(Path(bridge.remote_token_file).exists())
                    os.killpg(process.pid, termination)
                    self.assertEqual(process.wait(timeout=5), 1)
                    self.assertFalse(Path(bridge.remote_directory).exists())
                finally:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=5)


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
        self.editor_env.pop(vscode.TOKEN_ENV, None)

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
                                              DALFTUI_EDITOR_SOCKET=first.local_socket,
                                              DALFTUI_EDITOR_TOKEN=first.token))
                _, master2 = self.attach(dict(self.editor_env, SSH_CONNECTION='remote',
                                              DALFTUI_EDITOR_SOCKET=second.local_socket,
                                              DALFTUI_EDITOR_TOKEN=second.token))
                self.assertNotEqual(first.token, second.token)
                # Deliberately mismatched server state must not influence either client.
                self.tmux('set-environment', '-g', vscode.SOCKET_ENV, second.local_socket)
                self.tmux('set-environment', '-g', vscode.TOKEN_ENV, first.token)
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
