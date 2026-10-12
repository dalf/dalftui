"""Verify that dalftui's keys and tab labels start Python through uv, except the bridge's remote side."""
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import time
import unittest
from unittest.mock import patch

import test_install as install_tests
from test_install import setup

UV_RUN = 'uv run --no-project --python ">=3.11" '
SESSION_HOOKS = ('client-session-changed', 'client-detached', 'session-closed')


class UvDependencyTests(unittest.TestCase):
    def test_every_profile_requires_uv_with_an_install_hint(self):
        def which(name):
            return None if name == 'uv' else '/test/bin'
        for profile, hint in [('server', './bootstrap'), ('desktop', './bootstrap'),
                              ('macos', 'brew install tmux oh-my-posh uv')]:
            with self.subTest(profile=profile):
                platform = 'darwin' if profile == 'macos' else 'linux'
                with patch.object(setup.sys, 'platform', platform), \
                        patch.object(setup.shutil, 'which', side_effect=which):
                    with self.assertRaisesRegex(RuntimeError, f'first: uv .*{hint}'):
                        setup.dependencies(profile)


class UvBindingFixture(install_tests.TmuxFixture):
    def setUp(self):
        super().setUp()
        self.start()
        self.do_reload()

    def commands(self, table):
        """Each key's shell command, as tmux will run it."""
        # list-keys escapes $ inside double quotes, which shlex keeps.
        return {shlex.split(line)[3]: shlex.split(line)[-1].replace('\\$', '$')
                for line in self.tmux('list-keys', '-T', table).splitlines()}

    def session_hooks(self):
        """Each session-owner hook, with show-hooks' escapes removed."""
        hooks = {}
        for hook in SESSION_HOOKS:
            # Within double quotes show-hooks escapes ", and $ twice.
            hooks[hook] = (self.tmux('show-hooks', '-g', hook).replace('\\\\', '\\')
                           .replace('\\"', '"').replace('\\$', '$'))
            self.assertIn('/bin/session_owner.py sync', hooks[hook])
        return hooks

    def assert_session_hooks_use_python3(self):
        # Linux hosts run the helper like the bridge's remote side: plain python3.
        for hook, command in self.session_hooks().items():
            self.assertIn("run-shell -b 'python3 ", command.replace('"', "'"), hook)
            self.assertNotIn('uv run', command, hook)


class DesktopUvTests(UvBindingFixture):
    def test_session_owner_hooks_use_python3(self):
        self.assert_session_hooks_use_python3()

    def test_desktop_keys_run_through_uv(self):
        commands = self.commands('prefix')
        for key, script in [('F1', 'bin/shortcuts.py'), ('F3', '/bin/vscode.py')]:
            self.assertTrue(commands[key].startswith('PATH="$PATH:$HOME/.local/bin" ' + UV_RUN), commands[key])
            self.assertIn(script, commands[key])
        # F2 is a run-shell -C command; tmux expands $DALFTUI_PYTHON when the key runs.
        self.assertIn('"$DALFTUI_PYTHON bin/ssh_picker.py --client-pid #{client_pid}"', commands['F2'])


class ServerUvTests(UvBindingFixture):
    profile = 'server'

    def test_session_owner_hooks_use_python3(self):
        self.assert_session_hooks_use_python3()

    def test_server_guide_uses_uv_and_the_bridge_keeps_python3(self):
        commands = self.commands('prefix')
        self.assertIn(UV_RUN + 'bin/shortcuts.py --tmux-only', commands['F1'])
        # The remote side of the VS Code bridge keeps the python3 that remote_bootstrap checks.
        self.assertTrue(commands['F3'].startswith('python3 '), commands['F3'])

    def test_tab_label_helper_runs_through_uv(self):
        # Some tmux versions escape $ when showing an option.
        label = self.tmux('show-options', '-gv', '@dalftui_program_label').replace('\\$', '$')
        self.assertTrue(label.startswith('#(PATH="$PATH:$HOME/.local/bin" ' + UV_RUN), label)
        self.assertIn('/bin/tmux_label.py ', label)

    def test_reload_fails_when_uv_is_missing(self):
        def reload():
            with patch.object(setup.shutil, 'which', return_value=None), redirect_stdout(io.StringIO()):
                setup.reload_config(self.paths, socket=self.socket)
        with self.assertRaisesRegex(RuntimeError, 'uv is missing'):
            reload()
        local_bin = self.paths.home_dir / '.local/bin'
        local_bin.mkdir(parents=True, exist_ok=True)
        (local_bin / 'uv').touch()
        reload()

    @unittest.skipUnless(shutil.which('uv'), 'uv is required')
    def test_guide_key_finds_uv_in_local_bin_without_it_on_path(self):
        command = self.commands('prefix')['F1'] + ' --print'
        home = self.directory / 'home'
        (home / '.local/bin').mkdir(parents=True)
        (home / '.local/bin/uv').symlink_to(shutil.which('uv'))
        # Like a tmux server started by an SSH command: uv only in ~/.local/bin.
        env = dict(self.env, HOME=str(home), PATH=os.pathsep.join(
            directory for directory in os.environ['PATH'].split(os.pathsep)
            if not (Path(directory) / 'uv').exists()))
        result = subprocess.run(['sh', '-c', command], cwd=self.repo, env=env,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Ctrl+B → c', result.stdout)


class MacUvTests(UvBindingFixture):
    profile = 'macos'

    def test_mac_keys_run_through_uv(self):
        prefix = self.commands('prefix')
        for command in (prefix['F1'], prefix['F3']):
            self.assertIn(UV_RUN, command)

    def test_session_owner_hooks_run_through_uv(self):
        for hook, command in self.session_hooks().items():
            self.assertIn('PATH="$PATH:$HOME/.local/bin" ' + UV_RUN, command, hook)

    @unittest.skipUnless(shutil.which('uv'), 'uv is required')
    def test_uv_hook_keeps_one_client_per_session(self):
        # The hook command itself runs, through uv, as tmux expands it on macOS.
        from test_session_owner import Client
        env = dict(self.env, TERM='xterm-256color')
        clients = []
        for _ in range(2):
            clients.append(Client(self, [*self.command, 'attach-session', '-t', 'verify'], env))
            client = clients[-1]
            until = time.monotonic() + 10
            while str(client.process.pid) not in self.tmux('list-clients', '-F', '#{client_pid}').split():
                self.assertLess(time.monotonic(), until, 'the client did not attach')
                time.sleep(0.05)
        # uv may need a while to start the helper the first time.
        clients[0].process.wait(60)
        self.assertIn('Another terminal took over this tmux session.', clients[0].text())
        self.assertEqual(self.tmux('list-clients', '-F', '#{client_pid}'), str(clients[1].process.pid))


if __name__ == '__main__':
    unittest.main()
