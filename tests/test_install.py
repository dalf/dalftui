"""Test installation, rollback and updates using disposable directories."""
from contextlib import redirect_stdout
import io
import importlib.util
from importlib.machinery import SourceFileLoader
import json
import os
from pathlib import Path
import shutil
import shlex
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import dalftui.linux.alacritty_config as alacritty_config
import dalftui.linux.setup as setup
import dalftui.linux.shortcuts as shortcuts


class DependencyTests(unittest.TestCase):
    def test_server_accepts_supported_tmux_versions(self):
        for version in ('3.2', '3.2a', '3.3a', '3.4', '3.7c'):
            with self.subTest(version=version):
                result = subprocess.CompletedProcess(['tmux', '-V'], 0, f'tmux {version}\n', '')
                with patch.object(setup.shutil, 'which', return_value='/test/bin'):
                    with patch.object(setup.subprocess, 'run', return_value=result):
                        setup.dependencies('tmux-only')

    def test_server_rejects_older_tmux_and_reports_its_version(self):
        result = subprocess.CompletedProcess(['tmux', '-V'], 0, 'tmux 3.1c\n', '')
        with patch.object(setup.shutil, 'which', return_value='/test/bin'):
            with patch.object(setup.subprocess, 'run', return_value=result):
                with self.assertRaisesRegex(RuntimeError, r'tmux 3\.2.*Detected 3\.1'):
                    setup.dependencies('tmux-only')


class DisposableSetup(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='dalftui-install-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        # Both spaces and shell metacharacters must work in checkout and XDG paths.
        self.repo = self.directory / "checkout 'quoted' $repo"
        shutil.copytree(ROOT, self.repo, ignore=shutil.ignore_patterns('.git', '__pycache__'))
        self.paths = setup.Paths(self.directory / 'user', self.directory / "custom config 'quoted' $xdg",
                                 self.directory / 'state')
        self.paths.home_dir.mkdir()

    def install(self, **kwargs):
        with redirect_stdout(io.StringIO()):
            return setup.install(self.paths, self.repo, **kwargs)

class InstallationTests(DisposableSetup):
    def test_existing_files_are_backed_up_with_permissions_and_symlinks(self):
        self.paths.alacritty.parent.mkdir(parents=True)
        self.paths.alacritty.write_text('[font]\nsize = 12.0\n')
        self.paths.alacritty.chmod(0o600)
        self.paths.tmux.write_text('set -g mouse off\n')
        guide = self.paths.config_dir / 'tmux/shortcuts.py'
        guide.parent.mkdir()
        guide.symlink_to('/a/previous/guide.py')
        backup = self.install()
        records = json.loads((backup / 'manifest.json').read_text())
        originals = {item['original']: item for item in records}
        saved = backup / originals[str(self.paths.alacritty)]['backup']
        self.assertEqual(saved.read_text(), '[font]\nsize = 12.0\n')
        self.assertEqual(stat.S_IMODE(saved.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.paths.alacritty.stat().st_mode), 0o600)
        saved_guide = backup / originals[str(guide)]['backup']
        self.assertEqual(os.readlink(saved_guide), '/a/previous/guide.py')
        self.assertEqual(self.paths.root.resolve(), self.repo)
        self.assertEqual(guide.resolve(), self.repo / 'shortcuts.py')

    def test_repeat_install_preserves_local_settings_and_file_timestamps(self):
        self.install()
        local = self.paths.config_dir / 'alacritty/local.toml'
        local.write_text('[font]\nsize = 13.0\n')
        local_tmux = self.paths.config_dir / 'tmux/local.conf'
        local_tmux.write_text('set -g history-limit 4321\n')
        before = {path: path.stat().st_mtime_ns for path in
                  [self.paths.alacritty, self.paths.tmux, local, local_tmux]}
        self.assertIsNone(self.install())
        self.assertEqual(before, {path: path.stat().st_mtime_ns for path in before})
        self.assertEqual(alacritty_config.load(self.paths.alacritty)['font']['size'], 13.0)
        self.assertEqual(local_tmux.read_text(), 'set -g history-limit 4321\n')

    def test_checkout_updates_are_visible_without_reinstall(self):
        self.install()
        target = self.repo / 'config/alacritty.toml'
        target.write_text(target.read_text().replace('size = 10.5', 'size = 12.5'))
        self.assertEqual(alacritty_config.load(self.paths.alacritty)['font']['size'], 12.5)
        bindings = alacritty_config.load(self.paths.alacritty)['keyboard']['bindings']
        self.assertTrue(any(item['key'] == 'T' and item['mods'] == 'Control|Shift' for item in bindings))
        self.assertEqual(self.paths.root.resolve(), self.repo)

    def test_alacritty_starts_the_shared_tmux_session_policy(self):
        self.install()
        shell = alacritty_config.load(self.paths.alacritty)['terminal']['shell']
        self.assertEqual(shell['program'], 'sh')
        self.assertEqual(shell['args'][0], '-c')
        self.assertIn('/dalftui/tmux-start.sh', shell['args'][1])
        binary_dir = self.directory / 'bin'
        binary_dir.mkdir()
        command_log = self.directory / 'tmux-command'
        tmux = binary_dir / 'tmux'
        tmux.write_text('#!/bin/sh\n'
                        'if [ "$1" = list-sessions ]; then exit 1; fi\n'
                        'printf "%s\\n" "$@" > "$TEST_COMMAND_LOG"\n')
        tmux.chmod(0o755)
        env = dict(os.environ, HOME=str(self.paths.home_dir),
                   XDG_CONFIG_HOME=str(self.paths.config_dir),
                   PATH=str(binary_dir) + os.pathsep + os.defpath,
                   TEST_COMMAND_LOG=str(command_log))
        result = subprocess.run([shell['program'], *shell['args']], env=env,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(command_log.read_text().splitlines(),
                         ['new-session', '-A', '-s', '0'])

    def test_dry_run_does_not_create_files_or_backups(self):
        self.paths.tmux.write_text('set -g mouse off\n')
        self.install(dry_run=True)
        self.assertEqual(self.paths.tmux.read_text(), 'set -g mouse off\n')
        self.assertFalse(self.paths.config_dir.exists())
        self.assertFalse(self.paths.state_dir.exists())

    def test_failure_restores_previous_files(self):
        self.paths.tmux.write_text('set -g mouse off\n')
        original_write = setup.write
        failed = False

        def fail_once(path, item):
            nonlocal failed
            if path == self.paths.tmux and not failed:
                failed = True
                raise OSError('simulated installation failure')
            original_write(path, item)

        with patch.object(setup, 'write', side_effect=fail_once):
            with self.assertRaisesRegex(OSError, 'simulated'):
                self.install()
        self.assertEqual(self.paths.tmux.read_text(), 'set -g mouse off\n')
        self.assertFalse(self.paths.root.exists())
        self.assertFalse(self.paths.root.is_symlink())
        self.assertFalse(self.paths.alacritty.exists())

    def test_existing_configuration_directory_is_not_replaced(self):
        self.paths.root.mkdir(parents=True)
        personal = self.paths.root / 'personal.txt'
        personal.write_text('keep me')
        with self.assertRaisesRegex(ValueError, 'directory'):
            self.install()
        self.assertEqual(personal.read_text(), 'keep me')
        self.assertFalse(self.paths.alacritty.exists())

    def test_ssh_configuration_is_untouched(self):
        config = self.paths.home_dir / '.ssh/config'
        config.parent.mkdir()
        config.write_text('Host github.com\n User git\n')
        self.install()
        self.assertEqual(config.read_text(), 'Host github.com\n User git\n')

    def test_imports_keep_relative_paths_missing_files_and_array_merging(self):
        self.paths.config_dir.mkdir()
        base = self.paths.config_dir / 'base.toml'
        base.write_text('[font]\nsize = 9.0\n[keyboard]\nbindings = [{key="T", action="None"}]\n')
        config = self.paths.config_dir / 'main.toml'
        config.write_text('[general]\nimport = ["base.toml", "missing.toml"]\n'
                          '[font]\nsize = 11.0\n[keyboard]\nbindings = [{key="H", action="None"}]\n')
        result = alacritty_config.load(config)
        self.assertEqual(result['font']['size'], 11.0)
        self.assertEqual([item['key'] for item in result['keyboard']['bindings']], ['T', 'H'])

    def test_shortcut_guide_reads_shared_and_local_bindings(self):
        self.install()
        local = self.paths.config_dir / 'alacritty/local.toml'
        local.write_text('[keyboard]\nbindings = [{key="F10", mods="Alt", action="None"}]\n')
        with patch.object(shortcuts, 'config_path', return_value=self.paths.alacritty):
            with patch.object(shortcuts.subprocess, 'run', side_effect=FileNotFoundError('no test server')):
                content = shortcuts.render()
        self.assertIn('Alt+F10', content)
        self.assertNotIn('Cannot read Alacritty bindings', content)

    def test_recursive_imports_are_reported_before_installing(self):
        local = self.paths.config_dir / 'alacritty/local.toml'
        local.parent.mkdir(parents=True)
        local.write_text('[general]\nimport = ["local.toml"]\n')
        with self.assertRaisesRegex(ValueError, 'Recursive'):
            self.install()
        self.assertFalse(self.paths.root.exists())


class RelocationTests(DisposableSetup):
    def command_environment(self):
        command_dir = self.directory / "commands 'quoted' $bin"
        command_dir.mkdir()
        (command_dir / 'tmux').write_text(
            '#!/bin/sh\n'
            'case "$*" in\n'
            '  "-V") echo "tmux 3.4" ;;\n'
            '  "list-keys") echo "bind-key -T prefix F1 display-popup help" ;;\n'
            '  *"has-session"*) echo "no server running" >&2; exit 1 ;;\n'
            'esac\n')
        for name in ('less', 'git'):
            (command_dir / name).write_text('#!/bin/sh\nexit 0\n')
        (command_dir / 'python3').symlink_to(sys.executable)
        for command in command_dir.iterdir():
            if not command.is_symlink():
                command.chmod(0o755)
        outside = self.directory / "outside 'quoted' $cwd"
        outside.mkdir()
        environment = dict(os.environ, HOME=str(self.paths.home_dir),
                           XDG_CONFIG_HOME=str(self.paths.config_dir),
                           XDG_STATE_HOME=str(self.paths.state_dir),
                           PATH=str(command_dir) + os.pathsep + os.environ['PATH'])
        environment.pop('PYTHONPATH', None)
        return environment, outside

    def install_from_copied_checkout(self):
        environment, outside = self.command_environment()
        result = subprocess.run([str(self.repo / 'install'), '--tmux-only'], cwd=outside,
                                env=environment, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return environment, outside

    def test_default_installation_root_is_the_copied_checkout(self):
        self.install_from_copied_checkout()
        self.assertTrue(self.paths.root.is_symlink())
        self.assertEqual(self.paths.root.resolve(), self.repo)

    def test_installed_shortcut_launcher_works_outside_checkout_without_pythonpath(self):
        environment, outside = self.install_from_copied_checkout()
        guide = self.paths.config_dir / 'tmux/shortcuts.py'
        self.assertEqual(guide.resolve(), self.repo / 'shortcuts.py')
        result = subprocess.run([sys.executable, str(guide), '--tmux-only', '--print'], cwd=outside,
                                env=environment, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Ctrl+B → c', result.stdout)
        self.assertIn('LIVE TMUX BINDINGS / PREFIX', result.stdout)
        self.assertNotIn('ALACRITTY CUSTOM BINDINGS', result.stdout)

    def test_reload_entrypoint_works_outside_checkout(self):
        environment, outside = self.install_from_copied_checkout()
        socket = self.directory / "socket 'quoted' $tmux"
        result = subprocess.run([str(self.repo / 'reload'), '--socket', str(socket)], cwd=outside,
                                env=environment, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('tmux is not running', result.stdout)


@unittest.skipUnless(shutil.which('tmux'), 'tmux is required')
class TmuxFixture(DisposableSetup):
    """Exercise the actual loader and reload against a private tmux server."""
    profile = 'desktop'

    def setUp(self):
        super().setUp()
        self.install(profile=self.profile)
        self.socket = self.directory / 'tmux.socket'
        self.env = dict(os.environ)
        self.env.pop('TMUX', None)
        self.env.pop('TMUX_PANE', None)
        self.command = ['tmux', '-N', '-S', str(self.socket)]

    def tmux(self, *args):
        result = subprocess.run([*self.command, *args], capture_output=True, text=True,
                                env=self.env, timeout=15)
        if result.returncode or result.stderr.strip():
            self.fail(result.stderr.strip() or result.stdout.strip() or f'tmux failed: {args}')
        return result.stdout.strip()

    def start(self):
        result = subprocess.run(['tmux', '-S', str(self.socket), '-f', '/dev/null',
                                 'new-session', '-d', '-s', 'verify', 'sleep 600'],
                                capture_output=True, text=True, env=self.env, timeout=15)
        if result.returncode:
            self.fail(result.stderr.strip())
        self.addCleanup(subprocess.run, [*self.command, 'kill-server'], capture_output=True, env=self.env)

    def do_reload(self):
        with redirect_stdout(io.StringIO()):
            setup.reload_config(self.paths, socket=self.socket)

class TmuxTests(TmuxFixture):
    def test_runtime_reload_keeps_sessions_status_and_capability_counts(self):
        self.start()
        self.tmux('set-option', '-g', '@cctab_window_strip', '🔵')
        before = self.tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}')
        self.do_reload()
        features = self.tmux('show-options', '-s', 'terminal-features')
        overrides = self.tmux('show-options', '-s', 'terminal-overrides')
        self.do_reload()
        self.assertEqual(self.tmux('show-options', '-s', 'terminal-features'), features)
        self.assertEqual(self.tmux('show-options', '-s', 'terminal-overrides'), overrides)
        self.assertEqual(self.tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}'), before)
        self.assertEqual(self.tmux('show-options', '-gv', '@cctab_window_strip'), '🔵')
        rendered = self.tmux('display-message', '-p', '#{E:@claude_tab_active_strip}')
        self.assertIn('#[fg=#1565c0]⬤', rendered)
        self.assertIn('bg=#e5e7eb', self.tmux('show-options', '-gv', 'window-status-current-format'))
        for key, filename in [('F1', 'shortcuts.py'), ('F2', 'ssh-picker.py')]:
            binding = next(line for line in self.tmux('list-keys', '-T', 'prefix').splitlines()
                           if shlex.split(line)[3] == key)
            self.assertIn(filename, binding)
            self.assertIn('@dalftui_root', binding)
        self.assertEqual(Path(self.tmux('show-options', '-gv', '@dalftui_root')).resolve(), self.repo)

    def test_runtime_update_and_local_override_require_no_install(self):
        self.start()
        self.do_reload()
        config = self.repo / 'config/tmux.conf'
        config.write_text(config.read_text().replace('history-limit 100000', 'history-limit 76543'))
        self.do_reload()
        self.assertEqual(self.tmux('show-options', '-gv', 'history-limit'), '76543')
        local = self.paths.config_dir / 'tmux/local.conf'
        local.write_text('set -g history-limit 3210\n')
        self.do_reload()
        self.assertEqual(self.tmux('show-options', '-gv', 'history-limit'), '3210')

    def test_reload_does_not_start_a_tmux_server(self):
        self.do_reload()
        self.assertFalse(self.socket.exists())


class ServerInstallationTests(DisposableSetup):
    def test_server_install_never_reads_or_changes_existing_alacritty_files(self):
        self.paths.alacritty.parent.mkdir(parents=True)
        self.paths.alacritty.write_text('invalid TOML: keep this file')
        local = self.paths.config_dir / 'alacritty/local.toml'
        local.write_text('another invalid TOML file')
        files = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                 for path in (self.paths.alacritty, local)}
        with patch.object(setup, 'load', side_effect=AssertionError('Alacritty was read')):
            self.install(profile='tmux-only')
        self.assertEqual(setup.installed_profile(self.paths), 'tmux-only')
        self.assertEqual(files, {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files})

    def test_server_mode_and_overrides_survive_install_without_flags(self):
        self.install(profile='tmux-only')
        local = self.paths.config_dir / 'tmux/local.conf'
        local.write_text('set -g history-limit 5678\n')
        before = {path: path.stat().st_mtime_ns for path in (local, self.paths.tmux)}
        self.assertIsNone(self.install())
        self.assertEqual(setup.installed_profile(self.paths), 'tmux-only')
        self.assertEqual(before, {path: path.stat().st_mtime_ns for path in before})
        self.assertFalse(self.paths.alacritty.parent.exists())

    def test_old_desktop_loader_is_migrated_with_a_backup(self):
        previous = setup.loaders(self.paths, legacy=True)[1]
        self.paths.tmux.write_bytes(previous)
        self.assertEqual(setup.installed_profile(self.paths), 'desktop')
        backup = self.install()
        records = json.loads((backup / 'manifest.json').read_text())
        item = next(item for item in records if item['original'] == str(self.paths.tmux))
        self.assertEqual((backup / item['backup']).read_bytes(), previous)
        self.assertEqual(setup.installed_profile(self.paths), 'desktop')

    def test_edited_loader_is_preserved_when_switching_mode(self):
        self.install()
        self.paths.tmux.write_text(self.paths.tmux.read_text() + 'set -g status off\n')
        before = self.paths.tmux.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Managed loader was edited'):
            self.install(profile='tmux-only')
        self.assertEqual(self.paths.tmux.read_bytes(), before)

    def test_cli_installs_and_repeats_with_no_alacritty_or_ssh_in_path(self):
        server_bin = self.directory / 'server-bin'
        server_bin.mkdir()
        for command in ('tmux', 'git', 'less'):
            executable = shutil.which(command)
            if not executable:
                self.skipTest(f'{command} is required for this CLI test')
            (server_bin / command).symlink_to(executable)
        loader = SourceFileLoader('installer_entry', str(ROOT / 'install'))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with patch.dict(os.environ, {'PATH': str(server_bin)}):
            self.assertIsNone(shutil.which('alacritty'))
            self.assertIsNone(shutil.which('ssh'))
            with patch.object(setup.Paths, 'current', return_value=self.paths):
                for flags in [['--tmux-only'], []]:
                    with patch.object(sys, 'argv', ['install', *flags]):
                        with redirect_stdout(io.StringIO()):
                            self.assertEqual(installer.main(), 0)
        self.assertEqual(setup.installed_profile(self.paths), 'tmux-only')
        self.assertFalse(self.paths.alacritty.parent.exists())

    def test_server_dry_run_does_not_offer_alacritty_changes(self):
        output = io.StringIO()
        with redirect_stdout(output):
            setup.install(self.paths, self.repo, profile='tmux-only', dry_run=True)
        self.assertNotIn('alacritty', output.getvalue().lower())
        self.assertFalse(self.paths.config_dir.exists())

    def test_server_guide_uses_tmux_keys_without_reading_alacritty(self):
        live = subprocess.CompletedProcess(['tmux'], 0, stdout='bind-key -T prefix F1 display-popup help\n')
        with patch.object(shortcuts, 'load', side_effect=AssertionError('Alacritty was read')):
            with patch.object(shortcuts.subprocess, 'run', return_value=live):
                content = shortcuts.render(tmux_only=True)
        self.assertIn('Ctrl+B → c', content)
        self.assertIn('Live tmux bindings'.upper(), content)
        self.assertNotIn('ALACRITTY CUSTOM BINDINGS', content)
        self.assertNotIn('Ctrl+B → F2', content)
        self.assertNotIn('Cannot read Alacritty', content)


class ServerTmuxTests(TmuxFixture):
    profile = 'tmux-only'

    def prefix_bindings(self):
        return {shlex.split(line)[3]: line
                for line in self.tmux('list-keys', '-T', 'prefix').splitlines()}

    def test_server_reload_preserves_panes_claude_status_and_adapts_popups(self):
        self.start()
        before = self.tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}')
        self.tmux('set-option', '-g', '@cctab_window_strip', '🟣')
        with patch.object(setup, 'load', side_effect=AssertionError('Alacritty was read')):
            self.do_reload()
            self.do_reload()
        self.assertEqual(self.tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}'), before)
        self.assertIn('#[fg=#8e24aa]⬤', self.tmux('display-message', '-p', '#{E:@claude_tab_active_strip}'))
        self.assertEqual(self.tmux('show-options', '-gv', '@dalftui_profile'), 'tmux-only')
        bindings = self.prefix_bindings()
        self.assertNotIn('F2', bindings)
        self.assertIn('shortcuts.py --tmux-only', bindings['F1'])
        self.assertFalse(self.paths.alacritty.parent.exists())
        env = dict(self.env, TMUX=f'{self.socket},{self.tmux("display-message", "-p", "#{pid}")},0')
        result = subprocess.run([sys.executable, str(self.repo / 'shortcuts.py'), '--tmux-only', '--print'],
                                capture_output=True, text=True, env=env, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('LIVE TMUX BINDINGS', result.stdout)
        self.assertNotIn('Cannot read', result.stdout)

    def test_switching_modes_removes_and_restores_the_desktop_picker(self):
        self.start()
        self.do_reload()
        self.assertNotIn('F2', self.prefix_bindings())
        self.install(profile='desktop')
        self.do_reload()
        self.assertIn('ssh-picker.py', self.prefix_bindings()['F2'])
        self.install(profile='tmux-only')
        self.do_reload()
        self.assertNotIn('F2', self.prefix_bindings())
        self.assertIn('--tmux-only', self.prefix_bindings()['F1'])

    def test_server_git_update_and_local_override_need_only_reload(self):
        self.start()
        self.do_reload()
        config = self.repo / 'config/tmux.conf'
        config.write_text(config.read_text().replace('history-limit 100000', 'history-limit 87654'))
        self.do_reload()
        self.assertEqual(self.tmux('show-options', '-gv', 'history-limit'), '87654')
        local = self.paths.config_dir / 'tmux/local.conf'
        local.write_text('set -g history-limit 8765\n')
        self.do_reload()
        self.assertEqual(self.tmux('show-options', '-gv', 'history-limit'), '8765')
        self.assertEqual(setup.installed_profile(self.paths), 'tmux-only')


if __name__ == '__main__':
    unittest.main()
