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
from dalftui.linux import tmux_editor
from dalftui.windows import terminal_settings as terminal


class DependencyTests(unittest.TestCase):
    def test_server_accepts_supported_tmux_versions(self):
        for version in ('3.2', '3.2a', '3.3a', '3.4', '3.7c'):
            with self.subTest(version=version):
                result = subprocess.CompletedProcess(['tmux', '-V'], 0, f'tmux {version}\n', '')
                with patch.object(setup.shutil, 'which', return_value='/test/bin'):
                    with patch.object(setup.subprocess, 'run', return_value=result):
                        setup.dependencies('server')

    def test_server_rejects_older_tmux_and_reports_its_version(self):
        result = subprocess.CompletedProcess(['tmux', '-V'], 0, 'tmux 3.1c\n', '')
        with patch.object(setup.shutil, 'which', return_value='/test/bin'):
            with patch.object(setup.subprocess, 'run', return_value=result):
                with self.assertRaisesRegex(RuntimeError, r'tmux 3\.2.*Detected 3\.1'):
                    setup.dependencies('server')

    def test_both_profiles_require_oh_my_posh(self):
        def which(name):
            return None if name == 'oh-my-posh' else '/test/bin'
        for profile in setup.PROFILES:
            with self.subTest(profile=profile):
                platform = 'darwin' if profile == 'macos' else 'linux'
                with patch.object(setup.sys, 'platform', platform), \
                        patch.object(setup.shutil, 'which', side_effect=which):
                    with self.assertRaisesRegex(RuntimeError, 'Install the missing dependencies first: oh-my-posh'):
                        setup.dependencies(profile)

    def test_macos_refuses_alacritty_and_suggests_homebrew(self):
        with patch.object(setup.sys, 'platform', 'darwin'):
            with self.assertRaisesRegex(RuntimeError, 'desktop mode is Linux-only'):
                setup.dependencies('desktop')
            with patch.object(setup.shutil, 'which', side_effect=lambda name: None if name == 'tmux' else '/x'):
                with self.assertRaisesRegex(RuntimeError, 'tmux .Homebrew: brew install'):
                    setup.dependencies('macos')
        with patch.object(setup.sys, 'platform', 'linux'):
            with self.assertRaisesRegex(RuntimeError, 'macOS only'):
                setup.dependencies('macos')


class DisposableSetup(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='dalftui-install-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()  # macOS: /var is a link to /private/var.
        # Both spaces and shell metacharacters must work in checkout and XDG paths.
        self.repo = self.directory / "checkout 'quoted' $repo"
        shutil.copytree(ROOT, self.repo, ignore=shutil.ignore_patterns('.git', '__pycache__'))
        self.paths = setup.Paths(self.directory / 'user', self.directory / "custom config 'quoted' $xdg",
                                 self.directory / 'state')
        self.paths.home_dir.mkdir()
        # Never query or download real fonts; FontTests cover this step.
        font = patch.object(setup, 'install_font')
        self.install_font = font.start()
        self.addCleanup(font.stop)
        # Ignore a VS Code installed on the test machine; VSCodeTests enable it.
        self.vscode_patch = patch.object(setup, 'vscode_present', return_value=False)
        self.vscode_present = self.vscode_patch.start()
        self.addCleanup(self.vscode_patch.stop)
        # These tests cover the Linux default; MacTests cover the macOS one.
        default = patch.object(setup, 'DEFAULT_PROFILE', 'desktop')
        default.start()
        self.addCleanup(default.stop)
        zdotdir = patch.dict(os.environ)
        zdotdir.start()
        self.addCleanup(zdotdir.stop)
        os.environ.pop('ZDOTDIR', None)

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
        self.assertEqual(guide.resolve(), self.repo / 'bin/shortcuts.py')

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
        self.assertEqual(self.paths.root.resolve(), self.repo)

    def test_alacritty_starts_the_shared_tmux_session_policy(self):
        self.install()
        config = alacritty_config.load(self.paths.alacritty)
        self.assertIs(config['selection']['save_to_clipboard'], True)
        shell = config['terminal']['shell']
        self.assertEqual(shell['program'], 'sh')
        self.assertEqual(shell['args'][0], '-c')
        self.assertIn('/dalftui/bin/tmux-start.sh', shell['args'][1])
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
        with patch.object(alacritty_config, 'config_path', return_value=self.paths.alacritty):
            with patch.object(shortcuts.subprocess, 'run', side_effect=FileNotFoundError('no test server')):
                content = shortcuts.render()
        self.assertIn('Alt+F10', content)
        self.assertNotIn('Cannot read Alacritty bindings', content)
        self.assertIn('SELECT / COPY / PASTE', content)
        self.assertIn('Ctrl+B → z to zoom', content)
        self.assertIn('in Windows Terminal, select before', content)
        self.assertIn('Shift+Insert', content)

    def test_recursive_imports_are_reported_before_installing(self):
        local = self.paths.config_dir / 'alacritty/local.toml'
        local.parent.mkdir(parents=True)
        local.write_text('[general]\nimport = ["local.toml"]\n')
        with self.assertRaisesRegex(ValueError, 'Recursive'):
            self.install()
        self.assertFalse(self.paths.root.exists())


class PromptTests(DisposableSetup):
    def test_block_is_appended_once_and_preserves_bashrc(self):
        self.paths.bashrc.write_text('alias ll="ls -l"')
        self.paths.bashrc.chmod(0o600)
        backup = self.install()
        content = self.paths.bashrc.read_text()
        self.assertTrue(content.startswith('alias ll="ls -l"\n' + setup.PROMPT_MARKER + '\n'))
        self.assertEqual(content.count(setup.PROMPT_MARKER), 1)
        self.assertEqual(stat.S_IMODE(self.paths.bashrc.stat().st_mode), 0o600)
        records = json.loads((backup / 'manifest.json').read_text())
        item = next(item for item in records if item['original'] == str(self.paths.bashrc))
        self.assertEqual((backup / item['backup']).read_text(), 'alias ll="ls -l"')
        before = self.paths.bashrc.stat().st_mtime_ns
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertIsNone(setup.install(self.paths, self.repo))
        self.assertIn('Already installed', output.getvalue())
        self.assertEqual(self.paths.bashrc.stat().st_mtime_ns, before)

    def test_missing_bashrc_is_created(self):
        self.install(profile='server')
        self.assertIn(setup.PROMPT_MARKER, self.paths.bashrc.read_text())

    def test_symlinked_bashrc_is_replaced_and_its_target_left_alone(self):
        store = self.directory / 'store'
        store.mkdir()
        (store / 'bashrc').write_text('alias ll="ls -l"\n')
        store.chmod(0o555)
        self.addCleanup(store.chmod, 0o755)
        self.paths.bashrc.symlink_to(store / 'bashrc')
        self.install(profile='server')
        self.assertFalse(self.paths.bashrc.is_symlink())
        self.assertTrue(self.paths.bashrc.read_text().startswith('alias ll="ls -l"\n' + setup.PROMPT_MARKER))
        self.assertEqual((store / 'bashrc').read_text(), 'alias ll="ls -l"\n')

    def test_dry_run_reports_without_changing_bashrc(self):
        self.paths.bashrc.write_text('export EDITOR=vi\n')
        output = io.StringIO()
        with redirect_stdout(output):
            setup.install(self.paths, self.repo, dry_run=True)
        self.assertIn(f'Back up and replace: {self.paths.bashrc}', output.getvalue())
        self.assertEqual(self.paths.bashrc.read_text(), 'export EDITOR=vi\n')
        self.install_font.assert_called_once_with(True)

    def test_server_gets_the_prompt_but_no_font(self):
        self.install(profile='server')
        self.assertIn(setup.PROMPT_MARKER, self.paths.bashrc.read_text())
        self.install_font.assert_not_called()
        self.install(profile='desktop')
        self.install_font.assert_called_once_with(False)
        self.assertEqual(self.paths.bashrc.read_text().count(setup.PROMPT_MARKER), 1)

    def test_loader_runs_init_before_job_counts_in_interactive_shells(self):
        self.install(profile='server')
        command_dir = self.directory / 'commands'
        command_dir.mkdir()
        # The real init defines an empty set_poshcontext; the loader must replace it.
        fake = command_dir / 'oh-my-posh'
        fake.write_text('#!/bin/sh\n'
                        'printf "%s\\n" "$@" > "$TEST_ARGUMENTS"\n'
                        'echo "set_poshcontext() { :; }"\n')
        fake.chmod(0o755)
        arguments = self.directory / 'arguments'
        env = dict(os.environ, HOME=str(self.paths.home_dir), TEST_ARGUMENTS=str(arguments),
                   PATH=str(command_dir) + os.pathsep + os.environ['PATH'])
        script = 'sleep 30 & set_poshcontext; kill %1; echo "$OMP_JOBS_RUNNING"'
        result = subprocess.run(['bash', '--rcfile', str(self.paths.bashrc), '-i', '-c', script],
                                env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '1')
        init, shell, flag, theme = arguments.read_text().splitlines()
        self.assertEqual([init, shell, flag], ['init', 'bash', '--config'])
        self.assertEqual(Path(theme).resolve(), self.repo / 'config/oh-my-posh.omp.json')
        arguments.unlink()
        result = subprocess.run(['bash', '-c', f'. {shlex.quote(str(self.paths.bashrc))}'],
                                env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(arguments.exists())


class FontTests(unittest.TestCase):
    def fonts(self, families):
        return subprocess.CompletedProcess(['fc-list'], 0, families, '')

    def test_font_is_skipped_when_present(self):
        with patch.object(setup.shutil, 'which', return_value='/usr/bin/fc-list'):
            with patch.object(setup.subprocess, 'run',
                              return_value=self.fonts('DejaVu Sans\nHack Nerd Font,Hack Nerd Font Mono\n')) as run:
                setup.install_font(False)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][0], 'fc-list')

    def test_missing_font_is_installed_or_only_reported(self):
        with patch.object(setup.shutil, 'which', return_value='/usr/bin/fc-list'):
            with patch.object(setup.subprocess, 'run', return_value=self.fonts('Hack Nerd Font Mono\n')) as run:
                output = io.StringIO()
                with redirect_stdout(output):
                    setup.install_font(True)
                self.assertIn('Install font: Hack Nerd Font', output.getvalue())
                self.assertEqual(run.call_count, 1)
                setup.install_font(False)
        self.assertEqual(run.call_args.args[0], ['oh-my-posh', 'font', 'install', 'Hack'])

    def test_mac_font_in_library_is_detected_without_fc_list(self):
        with tempfile.TemporaryDirectory() as home:
            fonts = Path(home) / 'Library/Fonts'
            with patch.object(setup.sys, 'platform', 'darwin'), \
                    patch.object(setup.Path, 'home', return_value=Path(home)), \
                    patch.object(setup.shutil, 'which', return_value=None), \
                    patch.object(setup.subprocess, 'run') as run:
                fonts.mkdir(parents=True)  # Other families of the same download do not count.
                (fonts / 'HackNerdFontMono-Regular.ttf').touch()
                (fonts / 'HackNerdFontPropo-Regular.ttf').touch()
                output = io.StringIO()
                with redirect_stdout(output):
                    setup.install_font(True)
                self.assertIn('Install font', output.getvalue())
                (fonts / 'HackNerdFont-Regular.ttf').touch()
                setup.install_font(False)
            run.assert_not_called()


class VSCodeTests(DisposableSetup):
    def setUp(self):
        super().setUp()
        self.vscode_present.return_value = True

    def test_settings_are_created_then_left_alone(self):
        output = io.StringIO()
        with redirect_stdout(output):
            setup.install(self.paths, self.repo, dry_run=True)
        self.assertIn(f'Create: {self.paths.vscode_settings}', output.getvalue())
        self.assertFalse(self.paths.config_dir.exists())
        self.install()
        self.assertEqual(json.loads(self.paths.vscode_settings.read_text()), terminal.VSCODE_SETTINGS)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertIsNone(setup.install(self.paths, self.repo))
        self.assertIn('Already installed', output.getvalue())

    def test_existing_settings_are_backed_up_and_overwritten(self):
        self.paths.vscode_settings.parent.mkdir(parents=True)
        original = b'\xef\xbb\xbf{\r\n  // mine\r\n  "terminal.integrated.fontFamily": "Consolas",\r\n}\r\n'
        self.paths.vscode_settings.write_bytes(original)
        backup = self.install()
        records = json.loads((backup / 'manifest.json').read_text())
        saved = [backup / item['backup'] for item in records if item['original'] == str(self.paths.vscode_settings)]
        self.assertEqual([path.read_bytes() for path in saved], [original])
        installed = self.paths.vscode_settings.read_bytes()
        self.assertTrue(installed.startswith(b'\xef\xbb\xbf{\r\n  // mine\r\n'))
        self.assertEqual(json.loads(terminal.clean_jsonc(installed.decode('utf-8-sig'))), terminal.VSCODE_SETTINGS)

    def test_malformed_settings_stop_before_any_change(self):
        self.paths.vscode_settings.parent.mkdir(parents=True)
        self.paths.vscode_settings.write_text('{broken')
        with self.assertRaisesRegex(ValueError, 'Fix the VS Code settings first'):
            self.install()
        self.assertEqual(self.paths.vscode_settings.read_text(), '{broken')
        self.assertFalse(self.paths.tmux.exists())

    def test_servers_and_desktops_without_vscode_get_no_settings(self):
        self.install(profile='server')
        self.vscode_present.return_value = False
        self.install(profile='desktop')
        self.assertFalse(self.paths.vscode_settings.exists())

    def test_vscode_is_detected_by_command_or_configuration(self):
        self.vscode_patch.stop()
        with patch.object(setup.shutil, 'which', return_value=None):
            self.assertFalse(setup.vscode_present(self.paths))
            self.paths.vscode_settings.parents[1].mkdir(parents=True)
            self.assertTrue(setup.vscode_present(self.paths))
        self.paths.vscode_settings.parents[1].rmdir()
        with patch.object(setup.shutil, 'which', return_value='/usr/bin/code'):
            self.assertTrue(setup.vscode_present(self.paths))


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
        for name in ('less', 'git', 'oh-my-posh', 'uv'):
            (command_dir / name).write_text('#!/bin/sh\nexit 0\n')
        (command_dir / 'python3').symlink_to(sys.executable)
        for command in command_dir.iterdir():
            if not command.is_symlink():
                command.chmod(0o755)
        outside = self.directory / "outside 'quoted' $cwd"
        outside.mkdir()
        environment = dict(os.environ, HOME=str(self.paths.home_dir),
                           XDG_CONFIG_HOME=str(self.paths.config_dir),
                           XDG_STATE_HOME=str(self.paths.state_dir), TMUX_TMPDIR=str(self.directory),
                           PATH=str(command_dir) + os.pathsep + os.environ['PATH'])
        environment.pop('PYTHONPATH', None)
        return environment, outside

    def install_from_copied_checkout(self):
        environment, outside = self.command_environment()
        result = subprocess.run([str(self.repo / 'install'), '--server'], cwd=outside,
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
        self.assertEqual(guide.resolve(), self.repo / 'bin/shortcuts.py')
        result = subprocess.run([sys.executable, str(guide), '--tmux-only', '--print'], cwd=outside,
                                env=environment, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Ctrl+B → c', result.stdout)
        self.assertIn('LIVE TMUX BINDINGS / PREFIX', result.stdout)
        self.assertNotIn('ALACRITTY CUSTOM BINDINGS', result.stdout)

    def test_reload_entrypoint_works_outside_checkout(self):
        environment, outside = self.install_from_copied_checkout()
        socket = self.directory / "socket 'quoted' $tmux"
        result = subprocess.run([str(self.repo / 'bin/reload'), '--socket', str(socket)], cwd=outside,
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
        for key, filename in [('F1', 'bin/shortcuts.py'), ('F2', 'bin/ssh_picker.py')]:
            binding = next(line for line in self.tmux('list-keys', '-T', 'prefix').splitlines()
                           if shlex.split(line)[3] == key)
            self.assertIn(filename, binding)
            self.assertIn('@dalftui_root', binding)
        root_output = self.tmux('display-message', '-p',
                                tmux_editor.PATH_OUTPUT_PREFIX + '#{@dalftui_root}')
        self.assertEqual(Path(tmux_editor.decode_path_output(root_output)).resolve(), self.repo)

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
            self.install(profile='server')
        self.assertEqual(setup.installed_profile(self.paths), 'server')
        self.assertEqual(files, {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files})

    def test_server_mode_and_overrides_survive_install_without_flags(self):
        self.install(profile='server')
        local = self.paths.config_dir / 'tmux/local.conf'
        local.write_text('set -g history-limit 5678\n')
        before = {path: path.stat().st_mtime_ns for path in (local, self.paths.tmux)}
        self.assertIsNone(self.install())
        self.assertEqual(setup.installed_profile(self.paths), 'server')
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
            self.install(profile='server')
        self.assertEqual(self.paths.tmux.read_bytes(), before)

    def test_cli_installs_and_repeats_with_no_alacritty_or_ssh_in_path(self):
        server_bin = self.directory / 'server-bin'
        server_bin.mkdir()
        for command in ('tmux', 'git', 'less'):
            executable = shutil.which(command)
            if not executable:
                self.skipTest(f'{command} is required for this CLI test')
            (server_bin / command).symlink_to(executable)
        for command in ('oh-my-posh', 'uv'):
            (server_bin / command).write_text('#!/bin/sh\n')
            (server_bin / command).chmod(0o755)
        loader = SourceFileLoader('installer_entry', str(ROOT / 'install'))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with patch.dict(os.environ, {'PATH': str(server_bin)}):
            self.assertIsNone(shutil.which('alacritty'))
            self.assertIsNone(shutil.which('ssh'))
            with patch.object(setup.Paths, 'current', return_value=self.paths):
                for flags in [['--server'], []]:
                    with patch.object(sys, 'argv', ['install', *flags, '--socket', str(self.directory / 'tmux.socket')]):
                        with redirect_stdout(io.StringIO()):
                            self.assertEqual(installer.main(), 0)
        self.assertEqual(setup.installed_profile(self.paths), 'server')
        self.assertFalse(self.paths.alacritty.parent.exists())

    def test_server_dry_run_does_not_offer_alacritty_changes(self):
        output = io.StringIO()
        with redirect_stdout(output):
            setup.install(self.paths, self.repo, profile='server', dry_run=True)
        self.assertNotIn('alacritty', output.getvalue().lower())
        self.assertFalse(self.paths.config_dir.exists())

    def test_server_guide_uses_tmux_keys_without_reading_alacritty(self):
        live = subprocess.CompletedProcess(['tmux'], 0, stdout='bind-key -T prefix F1 display-popup help\n')
        with patch.object(alacritty_config, 'load', side_effect=AssertionError('Alacritty was read')), \
                patch.object(shortcuts.sys, 'platform', 'linux'), \
                patch.object(shortcuts.subprocess, 'run', return_value=live):
            content = shortcuts.render(tmux_only=True)
        self.assertIn('Ctrl+B → c', content)
        self.assertIn('Live tmux bindings'.upper(), content)
        self.assertIn('SELECT / COPY / PASTE', content)
        self.assertIn('Ctrl+B → z to zoom', content)
        self.assertIn('in Windows Terminal, select before', content)
        self.assertIn('Ctrl+B → Page Up, then Shift+drag', content)
        self.assertNotIn('Shift+Page Up', content)
        self.assertNotIn('Shift+Insert', content)
        self.assertNotIn('Ctrl+Shift+F / Ctrl+Shift+B', content)
        self.assertNotIn('Copy selection / paste using your local terminal', content)
        self.assertNotIn('ALACRITTY CUSTOM BINDINGS', content)
        self.assertNotIn('Ctrl+B → F2', content)
        self.assertNotIn('Cannot read Alacritty', content)


class ServerTmuxTests(TmuxFixture):
    profile = 'server'

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
        self.assertEqual(self.tmux('show-options', '-gv', '@dalftui_profile'), 'server')
        bindings = self.prefix_bindings()
        self.assertNotIn('F2', bindings)
        self.assertIn('bin/shortcuts.py --tmux-only', bindings['F1'])
        self.assertFalse(self.paths.alacritty.parent.exists())
        env = dict(self.env, TMUX=f'{self.socket},{self.tmux("display-message", "-p", "#{pid}")},0')
        result = subprocess.run([sys.executable, str(self.repo / 'bin/shortcuts.py'), '--tmux-only', '--print'],
                                capture_output=True, text=True, env=env, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('LIVE TMUX BINDINGS', result.stdout)
        self.assertNotIn('Cannot read', result.stdout)

    def test_selection_uses_terminal_and_clipboard_writes_are_allowed(self):
        self.start()
        self.do_reload()
        self.do_reload()
        self.assertEqual(self.tmux('show-options', '-sv', 'set-clipboard'), 'on')
        self.assertIn('alacritty*:clipboard', self.tmux('show-options', '-s', 'terminal-features'))
        self.assertIn('#e5e7eb', self.tmux('show-options', '-gv', 'mode-style'))
        root = {shlex.split(line)[3]: line
                for line in self.tmux('list-keys', '-T', 'root').splitlines()}
        self.assertIn('send-keys -M', root['MouseDrag1Pane'])
        self.assertIn('Hold Shift', root['MouseDrag1Pane'])
        self.assertNotIn('copy-mode -M', root['MouseDrag1Pane'])
        for key in ('DoubleClick1Pane', 'TripleClick1Pane'):
            self.assertIn('send-keys -M', root[key])
            self.assertNotIn('copy-pipe', root[key])

    def test_switching_modes_removes_and_restores_the_desktop_picker(self):
        self.start()
        self.do_reload()
        self.assertNotIn('F2', self.prefix_bindings())
        self.install(profile='desktop')
        self.do_reload()
        self.assertIn('bin/ssh_picker.py', self.prefix_bindings()['F2'])
        self.install(profile='server')
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
        self.assertEqual(setup.installed_profile(self.paths), 'server')


class MacTests(DisposableSetup):
    """The macOS mode, with the platform patched so it also runs on Linux."""
    def setUp(self):
        super().setUp()
        platform = patch.object(setup.sys, 'platform', 'darwin')
        platform.start()
        self.addCleanup(platform.stop)

    def test_new_mac_installation_defaults_to_macos_and_writes_only_zshrc(self):
        self.assertEqual(setup.installed_profile(self.paths), 'desktop')  # Patched in setUp.
        with patch.object(setup, 'DEFAULT_PROFILE', 'macos'):
            self.assertEqual(setup.installed_profile(self.paths), 'macos')
        self.paths.zshrc.write_text('setopt autocd\n')
        self.install(profile='macos')
        self.assertEqual(setup.installed_profile(self.paths), 'macos')
        content = self.paths.zshrc.read_text()
        self.assertTrue(content.startswith('setopt autocd\n' + setup.PROMPT_MARKER + '\n'))
        self.assertIn('config/prompt.zsh', content)
        self.assertFalse(self.paths.bashrc.exists())
        self.assertFalse(self.paths.alacritty.parent.exists())
        self.install_font.assert_called_once_with(False)
        self.assertIsNone(self.install())
        self.assertEqual(self.paths.zshrc.read_text(), content)

    def test_zdotdir_is_honored(self):
        zdotdir = self.directory / 'zdotdir'
        with patch.dict(os.environ, {'ZDOTDIR': str(zdotdir)}):
            self.install(profile='macos')
            self.assertEqual(self.paths.zshrc, zdotdir / '.zshrc')
            self.assertIn(setup.PROMPT_MARKER, self.paths.zshrc.read_text())
        self.assertFalse((self.paths.home_dir / '.zshrc').exists())

    @unittest.skipUnless(shutil.which('zsh'), 'zsh is required')
    def test_unexported_zdotdir_from_zshenv_is_honored_and_uninstalled(self):
        (self.paths.home_dir / '.zshenv').write_text('ZDOTDIR=$HOME/zd\n')
        self.assertEqual(self.paths.zshrc, self.paths.home_dir / 'zd/.zshrc')
        self.install(profile='macos')
        self.assertIn(setup.PROMPT_MARKER, (self.paths.home_dir / 'zd/.zshrc').read_text())
        with redirect_stdout(io.StringIO()):
            setup.uninstall(self.paths)
        self.assertEqual((self.paths.home_dir / 'zd/.zshrc').read_text(), '')

    @unittest.skipUnless(shutil.which('zsh'), 'zsh is required')
    def test_unexported_zdotdir_from_zprofile_is_honored(self):
        # Terminal.app and iTerm2 start login shells, which also read ~/.zprofile.
        (self.paths.home_dir / '.zprofile').write_text('ZDOTDIR=$HOME/zp\n')
        self.assertEqual(self.paths.zshrc, self.paths.home_dir / 'zp/.zshrc')

    def test_vscode_settings_use_the_library_path_and_are_removed(self):
        self.vscode_present.return_value = True
        self.assertEqual(self.paths.vscode_settings,
                         self.paths.home_dir / 'Library/Application Support/Code/User/settings.json')
        self.install(profile='macos')
        self.assertEqual(json.loads(self.paths.vscode_settings.read_text()), terminal.VSCODE_SETTINGS)
        with redirect_stdout(io.StringIO()):
            setup.uninstall(self.paths)
        self.assertEqual(json.loads(self.paths.vscode_settings.read_text()), {})
        self.assertEqual(self.paths.zshrc.read_text(), '')
        self.assertFalse(self.paths.tmux.exists())
        self.assertFalse(self.paths.root.is_symlink())

    def test_tmux_editor_uses_the_server_environment(self):
        with patch.object(tmux_editor.Path, 'read_bytes', side_effect=AssertionError('/proc was read')):
            self.assertEqual(tmux_editor.client_environment(1), dict(os.environ))

    def test_guide_names_mac_keys_and_never_imports_tomllib(self):
        with patch.object(shortcuts.subprocess, 'run', side_effect=FileNotFoundError('no test server')):
            content = shortcuts.render(tmux_only=True)
        self.assertIn('Cmd+C / Cmd+V', content)
        self.assertIn('Option+drag', content)
        self.assertIn('Ctrl+B → Fn+F1', content)
        self.assertNotIn('Alacritty', content)
        # The F1 popup may run an older python3; the server guide must not need tomllib.
        script = ('import sys; sys.path.insert(0, sys.argv[1]); import dalftui.linux.shortcuts as s\n'
                  'def run(*args, **kwargs): raise OSError("no test server")\n'
                  's.subprocess.run = run; s.render(tmux_only=True)\n'
                  'print("dalftui.linux.alacritty_config" in sys.modules)')
        result = subprocess.run([sys.executable, '-c', script, str(ROOT)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.stdout.strip(), 'False', result.stderr)

    @unittest.skipUnless(shutil.which('zsh'), 'zsh is required')
    def test_zsh_loader_runs_init_before_job_counts(self):
        self.install(profile='macos')
        command_dir = self.directory / 'commands'
        command_dir.mkdir()
        fake = command_dir / 'oh-my-posh'
        fake.write_text('#!/bin/sh\n'
                        'printf "%s\\n" "$@" > "$TEST_ARGUMENTS"\n'
                        'echo "set_poshcontext() { :; }"\n')
        fake.chmod(0o755)
        arguments = self.directory / 'arguments'
        env = dict(os.environ, HOME=str(self.paths.home_dir), ZDOTDIR=str(self.paths.home_dir),
                   TEST_ARGUMENTS=str(arguments), PATH=str(command_dir) + os.pathsep + os.environ['PATH'])
        script = 'sleep 30 & set_poshcontext; kill %1; echo "$OMP_JOBS_RUNNING"'
        result = subprocess.run(['zsh', '-i', '-c', script], env=env, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip().splitlines()[-1], '1')
        init, shell, flag, theme = arguments.read_text().splitlines()
        self.assertEqual([init, shell, flag], ['init', 'zsh', '--config'])
        self.assertEqual(Path(theme).resolve(), self.repo / 'config/oh-my-posh.omp.json')


class MacTmuxTests(TmuxFixture):
    profile = 'macos'

    def keys(self, table):
        return {shlex.split(line)[3]: line for line in self.tmux('list-keys', '-T', table).splitlines()}

    def test_mac_copies_with_pbcopy_and_switching_back_removes_mac_keys(self):
        self.start()
        self.tmux('set-option', '-s', 'terminal-overrides[100]', '*:Tc')  # From the older configuration.
        removed = ['C-S-F1', 'C-S-F3', *(f'C-M-{shift}{arrow}' for shift in ('', 'S-')
                                         for arrow in ('Up', 'Down', 'Left', 'Right'))]
        for key in removed:  # Root keys bound by earlier versions.
            self.tmux('bind-key', '-n', key, 'display-message', 'old')
        self.do_reload()
        self.assertEqual(self.tmux('show-options', '-sv', 'copy-command'), 'pbcopy')
        self.assertEqual(self.tmux('show-options', '-sv', 'terminal-overrides[100]'), 'alacritty*:Tc')
        prefix, root = self.keys('prefix'), self.keys('root')
        self.assertNotIn('F2', prefix)
        self.assertIn('bin/shortcuts.py --tmux-only', prefix['F1'])
        self.assertFalse(set(removed) & set(root))
        self.assertIn('Hold Fn', root['MouseDrag1Pane'])
        self.install(profile='server')
        self.do_reload()
        self.assertEqual(self.tmux('show-options', '-sv', 'copy-command'), '')
        self.assertEqual(self.tmux('show-options', '-sv', 'terminal-overrides[100]'), 'alacritty*:Tc')
        self.assertIn('Hold Shift', self.keys('root')['MouseDrag1Pane'])


class UninstallTests(DisposableSetup):
    def uninstall(self, **kwargs):
        output = io.StringIO()
        with redirect_stdout(output):
            setup.uninstall(self.paths, **kwargs)
        return output.getvalue()

    def tree(self):
        """Every path under the disposable directory with its content or link target."""
        result = {}
        for path in sorted(self.directory.rglob('*')):
            if path.is_relative_to(self.repo):
                continue
            result[path] = (os.readlink(path) if path.is_symlink() else
                            path.read_bytes() if path.is_file() else None)
        return result

    def test_install_then_uninstall_leaves_only_user_content(self):
        self.paths.bashrc.write_text('alias ll="ls -l"\n')
        self.paths.bashrc.chmod(0o600)
        self.paths.tmux.write_text('set -g mouse off\n')
        self.install()
        local_tmux = self.paths.config_dir / 'tmux/local.conf'
        local_tmux.write_text('set -g history-limit 4321\n')
        output = self.uninstall()
        self.assertEqual(self.paths.bashrc.read_text(), 'alias ll="ls -l"\n')
        self.assertEqual(stat.S_IMODE(self.paths.bashrc.stat().st_mode), 0o600)
        self.assertEqual(self.paths.tmux.read_text(), 'set -g mouse off\n')
        self.assertIn(f'Restore {self.paths.tmux} from ', output)
        for path in (self.paths.root, self.paths.alacritty, self.paths.config_dir / 'tmux/shortcuts.py',
                     self.paths.config_dir / 'alacritty/local.toml'):
            self.assertFalse(path.exists() or path.is_symlink(), path)
        self.assertEqual(local_tmux.read_text(), 'set -g history-limit 4321\n')
        self.assertIn(f'Kept personal settings: {local_tmux}', output)
        self.assertIn('keep their current configuration until restarted', output)
        backups = list((self.paths.state_dir / 'dalftui/backups').iterdir())
        self.assertEqual(len(backups), 2)  # Install, then uninstall.

        before = self.tree()
        self.assertIn('Nothing to uninstall.', self.uninstall())
        self.assertEqual(self.tree(), before)
        self.install()
        self.assertEqual(self.paths.root.resolve(), self.repo)
        self.assertEqual(self.paths.bashrc.read_text().count(setup.PROMPT_MARKER), 1)
        self.assertEqual(setup.installed_profile(self.paths), 'desktop')

    def test_uninstall_without_earlier_files_removes_everything_created(self):
        self.install(profile='server')
        self.uninstall()
        self.assertEqual(self.paths.bashrc.read_text(), '')
        self.assertFalse(self.paths.tmux.exists())
        self.assertEqual([path for path in self.paths.config_dir.rglob('*') if not path.is_dir()], [])

    def test_dry_run_changes_nothing(self):
        self.install()
        before = self.tree()
        output = self.uninstall(dry_run=True)
        self.assertIn(f'Back up and remove: {self.paths.root}', output)
        self.assertIn(f'Back up and replace: {self.paths.bashrc}', output)
        self.assertIn('Dry run: no files changed.', output)
        self.assertEqual(self.tree(), before)

    def test_edited_and_user_files_are_kept(self):
        self.install()
        self.paths.alacritty.write_text(self.paths.alacritty.read_text() + '[font]\nsize = 9.0\n')
        bashrc = self.paths.bashrc.read_text().replace('] && .', '] && source')
        self.paths.bashrc.write_text(bashrc)
        guide = self.paths.config_dir / 'tmux/shortcuts.py'
        guide.unlink()
        guide.symlink_to('/my/own/guide.py')
        output = self.uninstall()
        self.assertIn(f'Kept edited loader: {self.paths.alacritty}', output)
        self.assertIn('[font]\nsize = 9.0\n', self.paths.alacritty.read_text())
        self.assertEqual(self.paths.bashrc.read_text(), bashrc)
        self.assertIn('Kept an edited', output)
        self.assertEqual(os.readlink(guide), '/my/own/guide.py')
        self.assertFalse(self.paths.tmux.exists())
        self.assertIn(f'Kept {self.paths.root}: the edited loader still sources it', output)
        self.assertEqual(self.paths.root.resolve(), self.repo)

    def test_newest_original_is_restored_even_when_it_is_a_link(self):
        self.paths.tmux.write_text('OLD FILE\n')
        self.install(profile='server')
        self.uninstall()
        self.paths.tmux.unlink()
        self.paths.tmux.symlink_to('dotfiles/tmux.conf')
        self.install(profile='server')
        self.uninstall()
        self.assertEqual(os.readlink(self.paths.tmux), 'dotfiles/tmux.conf')

    def test_user_owned_tmux_conf_and_directory_root_are_kept(self):
        self.paths.tmux.write_text('set -g mouse on\n')
        self.paths.root.mkdir(parents=True)
        self.assertIn(f'Kept, not a dalftui link: {self.paths.root}', self.uninstall())
        self.assertEqual(self.paths.tmux.read_text(), 'set -g mouse on\n')

    def test_failure_rolls_back_removed_files(self):
        self.install()
        original_write = setup.write

        def fail_on_bashrc(path, item):
            if path == self.paths.bashrc:
                raise OSError('simulated uninstall failure')
            original_write(path, item)

        def outside_state(tree):
            return {path: value for path, value in tree.items() if not path.is_relative_to(self.paths.state_dir)}
        before = outside_state(self.tree())
        with patch.object(setup, 'write', side_effect=fail_on_bashrc):
            with self.assertRaisesRegex(OSError, 'simulated'):
                self.uninstall()
        self.assertEqual(outside_state(self.tree()), before)

    def test_vscode_values_are_removed_only_while_they_are_dalftui_values(self):
        self.vscode_present.return_value = True
        self.paths.vscode_settings.parent.mkdir(parents=True)
        original = b'\xef\xbb\xbf{\r\n  // mine\r\n  "editor.fontSize": 14,\r\n}\r\n'
        self.paths.vscode_settings.write_bytes(original)
        self.install()
        installed = self.paths.vscode_settings.read_bytes()
        self.paths.vscode_settings.write_bytes(installed.replace(b'": 12', b'": 15'))
        output = self.uninstall()
        updated = self.paths.vscode_settings.read_bytes()
        self.assertTrue(updated.startswith(b'\xef\xbb\xbf{\r\n  // mine\r\n'))
        self.assertEqual(json.loads(terminal.clean_jsonc(updated.decode('utf-8-sig'))),
                         {'editor.fontSize': 14, 'terminal.integrated.fontSize': 15})
        self.assertIn('Earlier VS Code font settings', output)

    def test_cli_uninstalls_without_dependencies_and_rejects_modes(self):
        self.install()
        loader = SourceFileLoader('installer_entry', str(ROOT / 'install'))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with patch.dict(os.environ, {'PATH': str(self.directory / 'empty')}):
            with patch.object(setup.Paths, 'current', return_value=self.paths):
                for flags in [['--uninstall', '--dry-run'], ['--uninstall']]:
                    with patch.object(sys, 'argv', ['install', *flags]):
                        with redirect_stdout(io.StringIO()) as output:
                            self.assertEqual(installer.main(), 0)
                    self.assertNotIn('reload', output.getvalue())
                    self.assertEqual(self.paths.root.is_symlink(), '--dry-run' in flags)
                with patch.object(sys, 'argv', ['install', '--uninstall', '--server']):
                    with redirect_stdout(io.StringIO()), patch('sys.stderr', io.StringIO()):
                        with self.assertRaises(SystemExit):
                            installer.main()


if __name__ == '__main__':
    unittest.main()
