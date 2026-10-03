"""Test installation, rollback and updates using disposable directories."""
from contextlib import redirect_stdout
import io
import importlib.util
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
import alacritty_config
import dalftui_setup as setup


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
        spec = importlib.util.spec_from_file_location('shortcut_guide', ROOT / 'shortcuts.py')
        guide = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guide)
        with patch.object(guide, 'config_path', return_value=self.paths.alacritty):
            with patch.object(guide.subprocess, 'run', side_effect=FileNotFoundError('no test server')):
                content = guide.render()
        self.assertIn('Alt+F10', content)
        self.assertNotIn('Cannot read Alacritty bindings', content)

    def test_recursive_imports_are_reported_before_installing(self):
        local = self.paths.config_dir / 'alacritty/local.toml'
        local.parent.mkdir(parents=True)
        local.write_text('[general]\nimport = ["local.toml"]\n')
        with self.assertRaisesRegex(ValueError, 'Recursive'):
            self.install()
        self.assertFalse(self.paths.root.exists())


@unittest.skipUnless(shutil.which('tmux'), 'tmux is required')
class TmuxTests(DisposableSetup):
    """Exercise the actual loader and reload against a private tmux server."""
    def setUp(self):
        super().setUp()
        self.install()
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


if __name__ == '__main__':
    unittest.main()
