"""Windows-compatible connection tests; no curses, tmux, or desktop GUI required."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dalftui import vscode
from dalftui import ssh as picker
from dalftui.windows import ssh as windows_ssh
from dalftui.windows import vscode as windows_vscode


class SharedLauncherTests(unittest.TestCase):
    """Exercise copied entrypoints without relying on the development checkout."""
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='dalftui-launchers-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.checkout = self.root / "checkout's $cash ; & é"
        for relative in ('bin/ssh_picker.py', 'bin/vscode.py', 'bridge_protocol.py', 'bin/tmux-start.sh',
                         'dalftui/__init__.py', 'dalftui/ssh.py', 'dalftui/vscode.py', 'dalftui/host_picker.py',
                         'dalftui/linux/__init__.py', 'dalftui/linux/ssh_picker.py',
                         'dalftui/linux/remote_bootstrap.py', 'dalftui/linux/tmux-start.sh',
                         'dalftui/linux/ops.py', 'dalftui/linux/package-status.sh', 'dalftui/linux/system-status.sh',
                         'dalftui/linux/tmux_editor.py', 'dalftui/windows/__init__.py',
                         'dalftui/windows/ssh.py', 'dalftui/windows/vscode.py', 'dalftui/windows/host_picker.py'):
            destination = self.checkout / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        self.outside = self.root / 'unrelated directory'
        self.outside.mkdir()
        self.env = dict(os.environ)
        self.env.pop('PYTHONPATH', None)
        self.env.pop('PYTHONDONTWRITEBYTECODE', None)

    def command(self, script, *args):
        return subprocess.run([sys.executable, str(self.checkout / script), *args],
                              cwd=self.outside, env=self.env, capture_output=True,
                              text=True, timeout=10)

    def test_copied_commands_import_and_validate_arguments_outside_checkout(self):
        for script, description in (
                ('bin/ssh_picker.py', 'Pick an SSH host'),
                ('bin/vscode.py', "Open a pane's folder")):
            with self.subTest(script=script):
                result = self.command(script, '--help')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f'usage: {Path(script).name} ', result.stdout)
                self.assertIn(description, result.stdout)
                self.assertEqual(result.stderr, '')
        cases = (
            ('bin/ssh_picker.py', ('--fzf',), 'unrecognized arguments: --fzf'),
            ('bin/ssh_picker.py', ('--pick', '--list'), 'not allowed with argument'),
            ('bin/ssh_picker.py', ('--connect', 'host', '--list'), 'not allowed with argument'),
            ('bin/ssh_picker.py', ('--connect', 'host', '--refresh-hosts'),
             '--refresh-hosts cannot be used with --connect'),
            ('bin/ssh_picker.py', ('--bridge', 'invalid'), 'invalid choice'),
            ('bin/vscode.py', (), 'required'),
            ('bin/vscode.py', ('--pane', '%7'), '--client is required with --pane'),
            ('bin/vscode.py', ('--pane', '%7', '--client', 'invalid'), 'invalid int value'),
            ('bin/vscode.py', ('--pane', '%7', '--folder', str(self.outside)),
             'not allowed with argument'),
        )
        for script, args, message in cases:
            with self.subTest(script=script, args=args):
                result = self.command(script, *args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(f'usage: {Path(script).name} ', result.stderr)
                self.assertIn(message, result.stderr)
        self.assertEqual(list(self.checkout.rglob('__pycache__')), [])

    def test_launchers_dispatch_to_their_own_package_and_propagate_status(self):
        cases = (
            ('bin/ssh_picker.py', 'ssh', ('--connect', "alice@prod-é;$host'", '--bridge', 'tcp'), 17),
            ('bin/ssh_picker.py', 'ssh', ('--pick', '--bridge', 'unix'), 17),
            ('bin/vscode.py', 'vscode', ('--folder', str(self.outside / "project's $cash & é")), 23),
            ('bin/vscode.py', 'vscode', ('--pane', '%7', '--client', '123',
                                   '--client-tty', '/dev/pts/7'), 23),
        )
        for script, module, args, status in cases:
            with self.subTest(script=script, args=args):
                implementation = self.checkout / 'dalftui' / (module + '.py')
                implementation.write_text('import json, sys\n'
                                          'assert sys.dont_write_bytecode\n'
                                          'def main():\n'
                                          '    print(json.dumps({"argv": sys.argv, "module": __file__}))\n'
                                          f'    return {status}\n', encoding='utf-8')
                result = self.command(script, *args)
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertEqual(result.stderr, '')
                observation = json.loads(result.stdout)
                self.assertEqual(observation['argv'], [str(self.checkout / script), *args])
                self.assertEqual(Path(observation['module']).resolve(), implementation.resolve())
                # Importing either launcher must not call main().
                result = subprocess.run(
                    [sys.executable, '-I', '-c',
                     'import runpy, sys; runpy.run_path(sys.argv[1], run_name="imported_launcher")',
                     str(self.checkout / script)], cwd=self.outside, env=self.env,
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertEqual(result.stderr, '')
        self.assertEqual(list(self.checkout.rglob('__pycache__')), [])

    def test_alacritty_launches_the_copied_bin_picker_as_separate_arguments(self):
        host = "alice@prod-é;$host'\"\\🛰"
        program = '''import json, subprocess, sys
from unittest.mock import patch
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
from dalftui import ssh as picker
from dalftui.linux import ssh_picker
with patch.object(ssh_picker.shutil, 'which', return_value='alacritty-probe'):
    with patch.object(ssh_picker.subprocess, 'Popen') as start:
        start.return_value.wait.side_effect = subprocess.TimeoutExpired('alacritty-probe', 0.4)
        host = sys.argv[2]
        with patch.object(ssh_picker, 'curses') as curses:
            curses.wrapper.return_value = host
            with patch.object(picker, 'target_hosts', return_value=[host]):
                with patch.object(sys, 'platform', 'linux'), patch.object(sys, 'argv', ['bin/ssh_picker.py']):
                    assert picker.main() == 0
            curses.wrapper.assert_called_once_with(ssh_picker.pick, [host])
        args, kwargs = start.call_args
        assert kwargs['stdin'] == subprocess.DEVNULL
        assert kwargs['stdout'] is kwargs['stderr']
        start.return_value.wait.assert_called_once_with(timeout=0.4)
        print(json.dumps({'args': args[0],
                          'tmux': [name for name in ('TMUX', 'TMUX_PANE') if name in kwargs['env']],
                          'detached': kwargs['start_new_session']}))
'''
        result = subprocess.run([sys.executable, '-I', '-c', program,
                                 str(self.checkout), host], cwd=self.outside,
                                env=dict(self.env, TMUX='stale', TMUX_PANE='%3'),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        observation = json.loads(result.stdout)
        self.assertEqual(observation['args'][:2], ['alacritty-probe', '--option'])
        self.assertEqual(tomllib.loads('\n'.join(observation['args'][2:4])),
                         {'window': {'title': f'SSH · {host}', 'dynamic_title': True}})
        self.assertEqual(observation['args'][4:],
                         ['-e', sys.executable,
                          str(self.checkout.resolve() / 'bin/ssh_picker.py'), '--connect', host])
        self.assertTrue(observation['detached'])
        self.assertEqual(observation['tmux'], [])

    def test_windows_generates_remote_programs_without_local_linux_integrations_or_execution(self):
        program = '''import importlib.abc, shlex, shutil, socket, subprocess, sys
from types import SimpleNamespace
from unittest.mock import patch
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
blocked = {'curses', 'dalftui.linux.ssh_picker', 'dalftui.linux.tmux_editor',
           'dalftui.linux.setup'}
class BlockPlatformImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in blocked:
            raise AssertionError('Unexpected platform import: ' + fullname)
sys.meta_path.insert(0, BlockPlatformImports())
with patch.object(sys, 'platform', 'win32'), \
     patch.object(subprocess, 'Popen', side_effect=AssertionError('Local program execution')), \
     patch.object(socket, 'socket', side_effect=AssertionError('Local socket creation')):
    from dalftui.linux import ops, remote_bootstrap
    from dalftui import ssh
    for transport in ('unix', 'tcp'):
        bridge = SimpleNamespace(transport=transport,
                                 remote_directory="/tmp/credentials' $cash ; é",
                                 remote_owner_file="/tmp/credentials' $cash ; é/claim.owner",
                                 remote_token_file="/tmp/credentials' $cash ; é/token",
                                 remote_socket=('/tmp/editor.sock' if transport == 'unix'
                                                else 'tcp:127.0.0.1:49152'),
                                 forward_spec='forward-probe')
        assert remote_bootstrap.prepare_credentials_script(bridge, check_installation=True)
        assert remote_bootstrap.cleanup_script(bridge)
        command = ssh.ssh_command('vm-alias', 'alice', bridge)
        assert shlex.split(command[-1]) == ['sh', '-c', remote_bootstrap.session_script(bridge)]
        assert '-S' not in command
        check = SimpleNamespace(name='system', command=ops.system_status_script(), timeout=20)
        for mode in ('plain', 'check', 'ops'):
            command = ssh.ssh_command('vm-alias', 'alice', bridge, mode=mode, check=check)
            assert shlex.split(command[-1]) == ['sh', '-c', remote_bootstrap.session_script(bridge, mode=mode, check=check)]
            assert '-S' not in command
            assert len(subprocess.list2cmdline(command).encode('utf-16-le')) // 2 < 32767
    assert remote_bootstrap.session_script()
assert not blocked.intersection(sys.modules)
'''
        # Remove the local shell forwarder to make the generator's independence
        # from that entrypoint explicit, even in a copied Windows checkout.
        (self.checkout / 'bin/tmux-start.sh').unlink()
        result = subprocess.run([sys.executable, '-I', '-c', program, str(self.checkout)],
                                cwd=self.outside, env=dict(self.env, PATH=''),
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout + result.stderr, '')


class WindowsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='dalftui-windows-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.local_app_data = self.root / 'local application data'
        self.enterContext(patch.object(picker, 'host_cache_path', return_value=self.root / 'hosts-cache.json'))

    def make_code_installation(self, name="VS Code with spaces \u00e9", *, version=''):
        installation = self.root / name
        cli = installation / version / 'resources/app/out/cli.js'
        cli.parent.mkdir(parents=True, exist_ok=True)
        cli.touch()
        application = installation / 'Code.exe'
        application.touch()
        if version:
            launcher = installation / 'bin/code.cmd'
            launcher.parent.mkdir(exist_ok=True)
            launcher.write_text('@echo off\nset ELECTRON_RUN_AS_NODE=1\n'
                                f'"%~dp0..\\Code.exe" "%~dp0..\\{version}\\resources\\app\\out\\cli.js" %*\n',
                                encoding='utf-8')
        return application, cli

    def configured_editor_env(self, application):
        config = self.local_app_data / windows_vscode.WINDOWS_CONFIG
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps({'code': str(application)}, ensure_ascii=False),
                          encoding='utf-8')
        return dict(os.environ, LOCALAPPDATA=str(self.local_app_data))

    def test_shared_imports_and_cli_dispatch_without_linux_adapters(self):
        # A cached package import would miss the optional-import boundary. Keep
        # both the blocked import and all module patches inside a fresh process.
        app, cli = self.make_code_installation()
        env = self.configured_editor_env(app)
        program = '''import importlib.abc, subprocess, sys
from unittest.mock import patch
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
blocked = {'curses', 'dalftui.linux.ssh_picker', 'dalftui.linux.tmux_editor'}
class BlockPlatformImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in blocked:
            raise AssertionError('Unexpected platform import: ' + fullname)
sys.meta_path.insert(0, BlockPlatformImports())
from dalftui import ssh as picker
from dalftui import vscode
case, folder, application, cli = sys.argv[2:]
with patch.object(picker, 'connect', return_value=17) as connect, \
     patch.object(picker, 'pick_host', return_value='vm-alias') as choose, \
     patch.object(picker, 'target_hosts', return_value=['vm-alias']), \
     patch.object(picker.shutil, 'which', return_value='harmless-probe'):
    if case in ('folder', 'windows-folder'):
        sys.argv = ['bin/vscode.py', '--folder', folder]
        with patch.object(vscode, 'WINDOWS', case == 'windows-folder'), \
             patch.object(vscode.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            status = vscode.main()
            run.assert_called_once()
            command = [application, cli] if case == 'windows-folder' else ['harmless-probe']
            assert run.call_args.args[0] == [*command, '--new-window', '--folder-uri',
                                            vscode.folder_uri(folder)]
            if case == 'windows-folder':
                assert run.call_args.kwargs['env']['ELECTRON_RUN_AS_NODE'] == '1'
        connect.assert_not_called()
    else:
        arguments = {'connect': ['--connect', 'vm-alias'], 'list': ['--list'],
                     'pick': ['--pick'], 'windows': []}[case]
        sys.argv = ['bin/ssh_picker.py', *arguments]
        with patch.object(picker.sys, 'platform', 'win32' if case == 'windows' else 'linux'), \
             patch.object(picker.subprocess, 'run',
                          return_value=subprocess.CompletedProcess([], 0)) as run:
            status = picker.main()
        if case == 'list':
            connect.assert_not_called()
        else:
            connect.assert_called_once_with('vm-alias', None)
        if case in ('pick', 'windows'):
            choose.assert_called_once_with()
            run.assert_not_called()
        else:
            choose.assert_not_called()
assert not blocked.intersection(sys.modules)
raise SystemExit(status)
'''
        for case, status in (('connect', 17), ('list', 0), ('pick', 17),
                             ('windows', 17), ('folder', 0), ('windows-folder', 0)):
            with self.subTest(case=case):
                result = subprocess.run([sys.executable, '-I', '-c', program, str(ROOT),
                                         case, str(self.root), str(app), str(cli)], cwd=self.root, env=env,
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertEqual(result.stdout, 'vm-alias\n' if case == 'list' else '')
                self.assertEqual(result.stderr, '')

    def test_local_folder_uri_handles_native_drive_unc_and_special_characters(self):
        folder = self.root / "project's %cash #?\u00e9"
        self.assertEqual(vscode.folder_uri(str(folder)), folder.as_uri())
        if sys.platform == 'win32':
            from pathlib import PureWindowsPath
            share = r'\\server\share\project with spaces'
            self.assertEqual(vscode.folder_uri(share), PureWindowsPath(share).as_uri())
        for invalid in ('relative', '', None, str(self.root) + '\0bad'):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    vscode.folder_uri(invalid)

    def test_shared_ssh_executable_selects_native_windows_helper(self):
        system_root = self.root / 'Windows'
        native = system_root / 'System32/OpenSSH/ssh.exe'
        native.parent.mkdir(parents=True)
        native.touch()
        with (patch.dict(os.environ, {'SystemRoot': str(system_root)}),
              patch.object(windows_ssh, 'ssh_executable', wraps=windows_ssh.ssh_executable) as select):
            with patch.object(sys, 'platform', 'win32'):
                self.assertEqual(picker.ssh_executable(), str(native))
                native.unlink()
                self.assertEqual(picker.ssh_executable(), 'ssh')
            self.assertEqual(select.call_count, 2)
            with patch.object(sys, 'platform', 'linux'):
                self.assertEqual(picker.ssh_executable(), 'ssh')
            self.assertEqual(select.call_count, 2)

    def test_shared_login_prepares_windows_acl_before_writing_config(self):
        system = self.root / 'Windows/System32'
        native = system / 'OpenSSH/ssh.exe'
        native.parent.mkdir(parents=True)
        native.touch()
        sid = 'S-1-5-21-123-456-789-1001'
        observations = []

        def run(command, **kwargs):
            observations.append((command, kwargs))
            if command[0] == str(system / 'whoami.exe'):
                return subprocess.CompletedProcess(command, 0,
                                                   f'"DOMAIN\\user","{sid}"\r\n'.encode('utf-16le'))
            if command[0] == str(system / 'icacls.exe'):
                self.assertFalse((Path(command[1]) / 'config').exists())
                return subprocess.CompletedProcess(command, 0, b'')
            self.assertEqual(command[0], str(native))
            wrapper = Path(command[command.index('-F') + 1])
            self.assertTrue(wrapper.read_text(encoding='utf-8').startswith('Host *\n    User '))
            return subprocess.CompletedProcess(command, 0, 'user alice\n', '')

        with (patch.object(sys, 'platform', 'win32'),
              patch.dict(os.environ, {'SystemRoot': str(system.parent)}),
              patch.object(picker, 'SSH_CONFIG', self.root / 'absent-config'),
              patch.object(windows_ssh.subprocess, 'run', side_effect=run)):
            self.assertEqual(picker.configured_login('vm-alias'), 'alice')
        self.assertEqual(len(observations), 3)
        self.assertEqual(observations[0],
                         ([str(system / 'whoami.exe'), '/user', '/fo', 'csv', '/nh'],
                          {'capture_output': True, 'check': True, 'timeout': 5}))
        directory = observations[1][0][1]
        self.assertEqual(observations[1],
                         ([str(system / 'icacls.exe'), directory, '/inheritance:r', '/grant:r',
                           f'*{sid}:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F',
                           '/remove:g', '*S-1-3-4'],
                          {'capture_output': True, 'check': True, 'timeout': 5}))
        self.assertFalse(Path(directory).exists())
        self.assertEqual(observations[2][1],
                         {'capture_output': True, 'text': True, 'timeout': 10})

    def test_windows_acl_errors_stop_shared_login_preparation(self):
        failures = (
            (subprocess.CompletedProcess([], 0, b'no SID'), 'determine the Windows account SID'),
            (OSError('whoami unavailable'), 'secure the temporary Windows SSH configuration'),
            (subprocess.TimeoutExpired('whoami', 5), 'secure the temporary Windows SSH configuration'),
        )
        for result, message in failures:
            with self.subTest(result=result):
                with (patch.object(sys, 'platform', 'win32'),
                      patch.object(windows_ssh.subprocess, 'run',
                                   side_effect=result if isinstance(result, Exception) else None,
                                   return_value=result) as run):
                    with self.assertRaisesRegex(RuntimeError, message):
                        picker.configured_login('vm-alias')
                run.assert_called_once()
        with (patch.object(sys, 'platform', 'win32'),
              patch.object(windows_ssh.subprocess, 'run', side_effect=[
                  subprocess.CompletedProcess([], 0, b'S-1-5-21-1001'),
                  subprocess.CalledProcessError(1, 'icacls')]) as run):
            with self.assertRaisesRegex(RuntimeError, 'secure the temporary Windows SSH configuration'):
                picker.configured_login('vm-alias')
        self.assertEqual(run.call_count, 2)

    def test_non_windows_login_skips_acl_preparation(self):
        with (patch.object(sys, 'platform', 'linux'),
              patch.object(windows_ssh, 'secure_ssh_directory') as secure,
              patch.object(picker.subprocess, 'run',
                           return_value=subprocess.CompletedProcess([], 0, 'user alice\n', ''))):
            self.assertEqual(picker.configured_login('vm-alias'), 'alice')
        secure.assert_not_called()

    def test_local_editor_cli_does_not_require_tmux_and_reports_failures_locally(self):
        folder = str(self.root)
        with patch.object(sys, 'argv', ['bin/vscode.py', '--folder', folder]):
            with patch.object(vscode, 'launch') as launch:
                self.assertEqual(vscode.main(), 0)
                launch.assert_called_once_with(folder)
            with patch.object(vscode, 'launch', side_effect=RuntimeError('test editor missing')):
                with patch.object(vscode.subprocess, 'run') as run:
                    self.assertEqual(vscode.main(), 1)
                run.assert_not_called()

    def test_windows_picker_connects_selected_host_without_curses_or_alacritty(self):
        with patch.object(picker.sys, 'platform', 'win32'):
            with patch.object(picker, 'pick_host', return_value='vm-alias') as choose:
                with patch.object(picker, 'connect', return_value=17) as connect:
                    with patch.dict(sys.modules, {'dalftui.linux.ssh_picker': None}):
                        with patch.object(sys, 'argv', ['bin/ssh_picker.py']):
                            self.assertEqual(picker.main(), 17)
        choose.assert_called_once_with()
        connect.assert_called_once_with('vm-alias', None)

    def test_cancelled_picker_does_not_open_ssh(self):
        with patch.object(picker, 'pick_host', return_value=None):
            with patch.object(picker, 'connect') as connect:
                with patch.object(sys, 'argv', ['bin/ssh_picker.py', '--pick']):
                    self.assertEqual(picker.main(), 0)
        connect.assert_not_called()

    def test_picker_tag_evaluation_uses_real_windows_ssh_and_include_config(self):
        if not shutil.which(picker.ssh_executable()):
            self.skipTest('OpenSSH is not installed')
        probe = subprocess.run([picker.ssh_executable(), '-G', '-F', os.devnull,
                                '-o', 'Tag=dalftui', '--', 'localhost'],
                               capture_output=True, text=True, timeout=10)
        if probe.returncode:
            self.skipTest('OpenSSH 9.4+ is required for SSH tags')
        if sys.platform == 'win32':
            windows_ssh.secure_ssh_directory(self.root)
        config = self.root / 'config'
        included = self.root / 'servers included.conf'
        included.write_text('Host vm-alias\n Tag dalftui\n User alice\n'
                            'Host github.com gitlab.com\n User git\n')
        config.write_text(f'Include "{included.as_posix()}"\n')
        with patch.object(picker, 'SSH_CONFIG', config):
            self.assertEqual(picker.target_hosts(), ['vm-alias'])
            with patch.object(picker.subprocess, 'run', side_effect=AssertionError('Cached listing started SSH')):
                self.assertEqual(picker.target_hosts(), ['vm-alias'])
            self.assertEqual(picker.configured_login('vm-alias'), 'alice')

    def test_picker_lists_alias_tags_without_canonical_dns_and_keeps_final_matches(self):
        if not shutil.which(picker.ssh_executable()):
            self.skipTest('OpenSSH is not installed')
        probe = subprocess.run([picker.ssh_executable(), '-G', '-F', os.devnull,
                                '-o', 'Tag=dalftui', '--', 'localhost'],
                               capture_output=True, text=True, timeout=10)
        if probe.returncode:
            self.skipTest('OpenSSH 9.4+ is required for SSH tags')
        if sys.platform == 'win32':
            windows_ssh.secure_ssh_directory(self.root)
        config = self.root / 'config'
        config.write_text('CanonicalizeHostname always\n'
                          'CanonicalDomains dalftui.invalid\n'
                          'CanonicalizeFallbackLocal no\n'
                          'Host vm-alias final-alias git-service\n'
                          'Host vm-alias\n Tag dalftui\n'
                          'Host git-service\n Tag git\n'
                          'Match final originalhost final-alias\n Tag dalftui\n')
        with patch.object(picker, 'SSH_CONFIG', config):
            self.assertEqual(picker.target_hosts(), ['final-alias', 'vm-alias'])
        # Only listing disables canonicalization; connections retain the user's
        # SSH configuration so short aliases still work with private DNS.
        self.assertNotIn('CanonicalizeHostname=no', picker.ssh_command('vm-alias'))

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
        with patch.object(vscode, 'launch', side_effect=lambda *args, **kwargs: opened.append(args)):
            with vscode.EditorBridge('vm-alias', transport='tcp') as bridge:
                for token in (None, 'wrong', 123, 'é'):
                    with self.subTest(token=token):
                        with socket.create_connection(('127.0.0.1', bridge.local_port), timeout=5) as connection:
                            vscode.send_message(connection, {'folder': '/project', 'token': token})
                            self.assertIn('error', vscode.read_message(connection))
                self.assertFalse(opened)
                vscode.request(f'tcp:127.0.0.1:{bridge.local_port}', '/project', bridge.token)
                self.assertEqual(opened[0][:2], ('/project', 'vm-alias'))

    def test_tcp_protocol_mismatch_never_launches_and_preserves_existing_bridge(self):
        with patch.object(vscode, 'launch') as launch:
            with vscode.EditorBridge('vm-alias', transport='tcp') as bridge:
                endpoint = f'tcp:127.0.0.1:{bridge.local_port}'
                vscode.request(endpoint, '/before-update', bridge.token)
                launch.assert_called_once()
                with socket.create_connection(('127.0.0.1', bridge.local_port), timeout=5) as connection:
                    vscode.send_message(connection, {'folder': '/after-update',
                                                     'token': bridge.token,
                                                     'protocol_version': 999})
                    response = vscode.read_message(connection)
                    self.assertIn('protocol', response['error'].lower())
                    self.assertNotIn(bridge.token, response['error'])
                launch.assert_called_once()
                vscode.request(endpoint, '/still-supported', bridge.token)
                self.assertEqual(launch.call_count, 2)
                self.assertEqual(launch.call_args.args[:2], ('/still-supported', 'vm-alias'))

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

    def test_configured_windows_cli_preserves_local_and_bridge_uri_arguments(self):
        app, cli = self.make_code_installation('VS Code with spaces %percent% \u00e9')
        env = dict(self.configured_editor_env(app), VSCODE_DEV='1', TMUX='stale',
                   TMUX_PANE='%3', VSCODE_IPC_HOOK_CLI='stale')
        original_env = dict(env)
        local_folder = str(self.root / "local project's %cash & #?\u00e9")
        remote_folder = "/home/alice/project.with.dot 'quoted' %PATH% & #?é"
        result = subprocess.CompletedProcess(['Code.exe'], 0, '', '')
        with (patch.object(vscode, 'WINDOWS', True),
              patch.object(windows_vscode, 'windows_code_command',
                           wraps=windows_vscode.windows_code_command) as select):
            with patch.object(vscode.shutil, 'which', side_effect=AssertionError('unsafe discovery')):
                with patch.object(vscode.subprocess, 'run', return_value=result) as run:
                    vscode.launch(local_folder, env=dict(env, VSCODE_DEV='1'))
                    with vscode.EditorBridge('alice@vm-alias', env, transport='tcp') as bridge:
                        with patch.object(bridge, 'run_editor', side_effect=run):
                            vscode.request(f'tcp:127.0.0.1:{bridge.local_port}',
                                           remote_folder, bridge.token)
        self.assertEqual(run.call_args_list[0].args[0],
                         [str(app), str(cli), '--new-window', '--folder-uri',
                          vscode.folder_uri(local_folder)])
        self.assertEqual(run.call_args_list[1].args[0],
                         [str(app), str(cli), '--new-window', '--folder-uri',
                          vscode.folder_uri(remote_folder, 'alice@vm-alias')])
        self.assertFalse(run.call_args.kwargs.get('shell', False))
        self.assertEqual(run.call_args.kwargs['env']['ELECTRON_RUN_AS_NODE'], '1')
        self.assertNotIn('VSCODE_DEV', run.call_args.kwargs['env'])
        for name in ('TMUX', 'TMUX_PANE', 'VSCODE_IPC_HOOK_CLI'):
            self.assertNotIn(name, run.call_args.kwargs['env'])
        self.assertEqual(select.call_count, 2)
        self.assertEqual(env, original_env)

    def test_windows_configuration_helper_reads_utf8_bom(self):
        app, cli = self.make_code_installation()
        env = self.configured_editor_env(app)
        config = self.local_app_data / windows_vscode.WINDOWS_CONFIG
        config.write_text(json.dumps({'code': str(app)}, ensure_ascii=False), encoding='utf-8-sig')
        env['VSCODE_DEV'] = '1'
        self.assertEqual(windows_vscode.windows_code_command(env), [str(app), str(cli)])
        self.assertEqual(env['ELECTRON_RUN_AS_NODE'], '1')
        self.assertNotIn('VSCODE_DEV', env)

    def test_versioned_windows_cli_follows_active_launcher_across_updates(self):
        # A flat tree and a staged update may coexist with the running version.
        app, _ = self.make_code_installation()
        self.make_code_installation(version='07f806f999')
        env = self.configured_editor_env(app)
        folder = "/home/alice/project 'quoted' %PATH% & #?\u00e9"
        result = subprocess.CompletedProcess(['Code.exe'], 0, '', '')
        with (patch.object(vscode, 'WINDOWS', True),
              patch.object(vscode.shutil, 'which', side_effect=AssertionError('unsafe discovery')),
              patch.object(vscode.subprocess, 'run', return_value=result) as run):
            for version in ('04c0d99f4f', '07f806f999'):
                with self.subTest(version=version):
                    _, cli = self.make_code_installation(version=version)
                    vscode.launch(folder, 'alice@vm-alias', env=env)
                    self.assertEqual(run.call_args.args[0],
                                     [str(app), str(cli), '--new-window', '--folder-uri',
                                      vscode.folder_uri(folder, 'alice@vm-alias')])
                    self.assertFalse(run.call_args.kwargs.get('shell', False))

    def test_versioned_windows_cli_missing_active_version_never_uses_leftovers(self):
        self.make_code_installation()
        self.make_code_installation(version='07f806f999')
        app, cli = self.make_code_installation(version='04c0d99f4f')
        cli.unlink()
        env = self.configured_editor_env(app)
        with (patch.object(vscode, 'WINDOWS', True),
              patch.object(vscode.subprocess, 'run') as run):
            with self.assertRaisesRegex(RuntimeError, 'configured VS Code installation is missing'):
                vscode.launch(str(self.root), env=env)
            run.assert_not_called()

    def test_versioned_windows_cli_does_not_follow_paths_outside_installation(self):
        app, cli = self.make_code_installation(version='04c0d99f4f')
        outside = self.root / 'resources/app/out/cli.js'
        outside.parent.mkdir(parents=True)
        outside.touch()
        launcher = app.parent / 'bin/code.cmd'
        launcher.write_text('"%~dp0..\\Code.exe" '
                            '"%~dp0..\\..\\resources\\app\\out\\cli.js" %*\n', encoding='utf-8')
        env = self.configured_editor_env(app)
        self.assertTrue(cli.is_file())
        with (patch.object(vscode, 'WINDOWS', True),
              patch.object(vscode.subprocess, 'run') as run):
            with self.assertRaisesRegex(RuntimeError, 'configured VS Code installation is missing'):
                vscode.launch(str(self.root), env=env)
            run.assert_not_called()

    def test_invalid_windows_configuration_never_executes_or_discovers_an_alternative(self):
        app, cli = self.make_code_installation()
        env = self.configured_editor_env(app)
        config = self.local_app_data / windows_vscode.WINDOWS_CONFIG
        cases = (
            (None, 'not configured'),
            (b'\xff', 'Cannot read'),
            (b'{broken', 'Cannot read'),
            (json.dumps([]).encode(), 'is invalid'),
            (json.dumps({}).encode(), 'is invalid'),
            (json.dumps({'code': 42}).encode(), 'is invalid'),
            (json.dumps({'code': 'relative/Code.exe'}).encode(), 'is invalid'),
            (json.dumps({'code': str(app) + '\0'}).encode(), 'is invalid'),
            (json.dumps({'code': str(app.with_name('other.exe'))}).encode(), 'is invalid'),
        )
        with (patch.object(vscode, 'WINDOWS', True),
              patch.object(vscode.subprocess, 'run') as run,
              patch.object(vscode.shutil, 'which', side_effect=AssertionError('unsafe discovery'))):
            for content, message in cases:
                with self.subTest(content=content):
                    if content is None:
                        config.unlink()
                    else:
                        config.write_bytes(content)
                    with self.assertRaisesRegex(RuntimeError, message + '.*install.cmd'):
                        vscode.launch('relative-folder', env=env)
                    run.assert_not_called()
            self.configured_editor_env(app)
            cli.unlink()
            with self.assertRaisesRegex(RuntimeError, 'configured VS Code installation is missing'):
                vscode.launch(str(self.root), env=env)
            run.assert_not_called()

    @unittest.skipIf(sys.platform == 'win32', 'POSIX executable is the simulated Windows probe')
    def test_simulated_windows_never_executes_project_code_even_with_unsafe_path_entries(self):
        project = self.root / 'untrusted project'
        fake_cli = project / 'resources/app/out/cli.js'
        fake_cli.parent.mkdir(parents=True)
        fake_cli.touch()
        attacker_log = self.root / 'attacker-ran'
        fake_app = project / 'Code.exe'
        fake_app.write_text(f'#!{sys.executable}\nfrom pathlib import Path\n'
                            f'Path({str(attacker_log)!r}).touch()\n')
        fake_app.chmod(0o755)

        app, _ = self.make_code_installation('trusted VS Code \u00e9')
        editor_log = self.root / 'configured-editor.json'
        app.write_text(f'#!{sys.executable}\nimport json, os, pathlib, sys\n'
                       'pathlib.Path(os.environ["EDITOR_TEST_LOG"]).write_text('
                       'json.dumps(sys.argv[1:]))\n')
        app.chmod(0o755)
        env = self.configured_editor_env(app)
        env.update(PATH=os.pathsep.join(('', '.', 'relative-bin', str(project))),
                   EDITOR_TEST_LOG=str(editor_log))
        previous = Path.cwd()
        os.chdir(project)
        try:
            with patch.object(vscode, 'WINDOWS', True):
                with patch.object(vscode.shutil, 'which',
                                  side_effect=AssertionError('unsafe discovery')):
                    vscode.launch(str(project), env=env)
        finally:
            os.chdir(previous)
        self.assertFalse(attacker_log.exists())
        self.assertEqual(json.loads(editor_log.read_text())[1:],
                         ['--new-window', '--folder-uri', project.as_uri()])

    def test_missing_or_invalid_windows_configuration_fails_before_execution(self):
        app, _ = self.make_code_installation()
        env = self.configured_editor_env(app)
        app.unlink()
        with patch.object(vscode, 'WINDOWS', True):
            with patch.object(vscode.subprocess, 'run') as run:
                with self.assertRaisesRegex(RuntimeError,
                                            'configured VS Code installation is missing.*install.cmd.*VSCodePath'):
                    vscode.launch(str(self.root), env=env)
            run.assert_not_called()
            with self.assertRaisesRegex(RuntimeError, 'VS Code is not configured.*install.cmd'):
                vscode.code_command({'LOCALAPPDATA': 'relative'})

    @unittest.skipUnless(sys.platform == 'win32', 'native Windows executable search test')
    def test_native_windows_cannot_execute_code_from_current_directory(self):
        project = self.root / 'untrusted project'
        cli = project / 'resources/app/out/cli.js'
        cli.parent.mkdir(parents=True)
        marker = self.root / 'attacker-ran'
        cli.write_text('var shell = new ActiveXObject("WScript.Shell");\n'
                       'var fso = new ActiveXObject("Scripting.FileSystemObject");\n'
                       'fso.CreateTextFile(shell.ExpandEnvironmentStrings('
                       '"%EDITOR_TEST_LOG%"), true).Close();\n')
        shutil.copyfile(Path(os.environ['SystemRoot']) / 'System32/cscript.exe',
                        project / 'Code.exe')
        ordinary_path = os.environ.get('PATH', '')
        previous = Path.cwd()
        os.chdir(project)
        try:
            for path in (ordinary_path,
                         os.pathsep.join(('', '.', 'relative-bin', ordinary_path))):
                with self.subTest(path=path):
                    marker.unlink(missing_ok=True)
                    env = dict(os.environ, PATH=path, LOCALAPPDATA=str(self.local_app_data),
                               EDITOR_TEST_LOG=str(marker))
                    with self.assertRaisesRegex(RuntimeError, 'VS Code is not configured'):
                        vscode.launch(str(project), env=env)
                    self.assertFalse(marker.exists())
        finally:
            os.chdir(previous)

    @unittest.skipUnless(sys.platform == 'win32', 'native Windows executable launch test')
    def test_native_configured_portable_installation_preserves_uri_arguments(self):
        app, cli = self.make_code_installation('portable VS Code spaces \u00e9')
        shutil.copyfile(Path(os.environ['SystemRoot']) / 'System32/cscript.exe', app)
        log = self.root / 'native editor arguments.txt'
        cli.write_text('var shell = new ActiveXObject("WScript.Shell");\n'
                       'var fso = new ActiveXObject("Scripting.FileSystemObject");\n'
                       'var output = fso.CreateTextFile(shell.ExpandEnvironmentStrings('
                       '"%EDITOR_TEST_LOG%"), true, true);\n'
                       'for (var i = 0; i < WScript.Arguments.length; i++) '
                       'output.WriteLine(WScript.Arguments.Item(i));\n'
                       'output.Close();\n')
        env = self.configured_editor_env(app)
        env['EDITOR_TEST_LOG'] = str(log)
        cases = [(str(self.root / "local project's é"), None),
                 ("/home/alice/remote project's é", 'alice@vm-alias')]
        for folder, destination in cases:
            with self.subTest(destination=destination):
                vscode.launch(folder, destination, env)
                self.assertEqual(log.read_text(encoding='utf-16').splitlines(),
                                 ['--new-window', '--folder-uri',
                                  vscode.folder_uri(folder, destination)])

    def test_token_setup_sends_secret_on_stdin_and_not_in_process_arguments(self):
        result = subprocess.CompletedProcess(['ssh'], 0)
        with vscode.EditorBridge('vm-alias', transport='tcp') as bridge:
            with patch.object(picker.subprocess, 'run', return_value=result) as run:
                picker.prepare_editor_credentials('vm-alias', 'alice', bridge, {})
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

    @unittest.skipUnless(sys.platform == 'win32', 'native Windows cleanup timeout test')
    def test_native_cleanup_times_out_while_proxy_child_keeps_output_handles_open(self):
        # Model ProxyCommand's inherited stderr with real native subprocesses.
        # Releasing the child in finally also bounds a failing pre-fix test.
        helper = self.root / 'ssh cleanup helper.py'
        ready = self.root / 'child-ready'
        released = self.root / 'release-child'
        exited = self.root / 'child-exited'
        helper.write_text('''import subprocess, sys, time
from pathlib import Path

directory = Path(sys.argv[2])
if sys.argv[1] == 'ssh':
    subprocess.Popen([sys.executable, __file__, 'holder', str(directory)],
                     stdin=subprocess.DEVNULL, stdout=sys.stdout, stderr=sys.stderr)
    time.sleep(60)
else:
    (directory / 'child-ready').touch()
    deadline = time.monotonic() + 30
    while not (directory / 'release-child').exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    (directory / 'child-exited').touch()
''', encoding='utf-8')
        real_run = subprocess.run
        timed_out = threading.Event()
        finished = threading.Event()
        errors = []

        def observe_timeout(*args, **kwargs):
            try:
                return real_run(*args, **kwargs)
            except subprocess.TimeoutExpired:
                timed_out.set()
                raise

        def cleanup():
            try:
                bridge = vscode.EditorBridge('vm-alias', transport='tcp')
                picker.cleanup_editor_bridge('vm-alias', None, bridge, dict(os.environ))
            # Report any background cleanup failure on the test's main thread.
            except BaseException as error:  # pylint: disable=broad-exception-caught
                errors.append(error)
            finally:
                finished.set()

        with (patch.object(picker, 'ssh_base',
                           return_value=[sys.executable, str(helper), 'ssh', str(self.root)]),
              patch.object(picker.subprocess, 'run', side_effect=observe_timeout)):
            worker = threading.Thread(target=cleanup, daemon=True)
            worker.start()
            try:
                deadline = time.monotonic() + 15
                while not ready.exists():
                    self.assertFalse(finished.wait(0.02),
                                     f'Cleanup finished before the output-holding child started: {errors}')
                    self.assertLess(time.monotonic(), deadline, 'Child did not start')
                self.assertTrue(finished.wait(12),
                                'Cleanup waited for inherited output handles after its ten-second timeout')
                self.assertEqual(errors, [])
                self.assertTrue(timed_out.is_set(), 'Cleanup must reach its real subprocess timeout')
                self.assertFalse(exited.exists(), 'Output-holding child must still be running')
            finally:
                released.touch()
                worker.join(5)
                deadline = time.monotonic() + 5
                while ready.exists() and not exited.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
            self.assertFalse(worker.is_alive(), 'Cleanup worker did not stop')
            self.assertTrue(exited.exists(), 'Output-holding child did not stop')

    def test_connect_cleans_up_setup_failures_cancellation_disconnect_and_normal_exit(self):
        for stage, status in (('setup-failure', 1), ('setup-cancel', 130),
                              ('attach-cancel', 130), ('forward-failure', 255),
                              ('normal-exit', 0)):
            with self.subTest(stage=stage):
                bridge = vscode.EditorBridge('vm-alias', transport='tcp')
                prepare_error = (RuntimeError('setup failed') if stage == 'setup-failure'
                                 else KeyboardInterrupt() if stage == 'setup-cancel' else None)
                def cleanup_after_stop(*_args, stage=stage, bridge=bridge):
                    if stage.startswith('setup-'):
                        self.assertFalse(hasattr(bridge, 'listener'))
                    else:
                        self.assertTrue(bridge.stopped.is_set())
                        self.assertEqual(bridge.listener.fileno(), -1)
                output = io.StringIO()
                with (patch.object(picker, 'configured_login', return_value='alice'),
                      patch.object(picker, 'EditorBridge', return_value=bridge),
                      patch.object(picker, 'prepare_editor_credentials', return_value=True,
                                   side_effect=prepare_error) as prepare,
                      patch.object(picker, 'cleanup_editor_bridge', side_effect=cleanup_after_stop) as cleanup,
                      patch.object(picker.subprocess, 'run',
                                   return_value=subprocess.CompletedProcess(['ssh'], status),
                                   side_effect=KeyboardInterrupt() if stage == 'attach-cancel' else None) as run,
                      patch('builtins.input', return_value=''),
                      patch.dict(os.environ, {vscode.SOCKET_ENV: 'stale-endpoint',
                                              vscode.TOKEN_ENV: 'stale-token'}),
                      redirect_stdout(output), redirect_stderr(output)):
                    self.assertEqual(picker.connect('vm-alias', 'tcp'), status)
                prepare.assert_called_once()
                self.assertTrue(prepare.call_args.kwargs['check_installation'])
                cleanup.assert_called_once()
                self.assertIs(cleanup.call_args.args[2], bridge)
                self.assertNotIn(vscode.SOCKET_ENV, prepare.call_args.args[3])
                self.assertNotIn(vscode.TOKEN_ENV, prepare.call_args.args[3])
                if stage.startswith('setup-'):
                    run.assert_not_called()
                else:
                    self.assertEqual(run.call_args.args[0][run.call_args.args[0].index('-R') + 1],
                                     bridge.forward_spec)
                    self.assertIn('ExitOnForwardFailure=yes', run.call_args.args[0])
                    self.assertNotIn(bridge.token, ' '.join(run.call_args.args[0]))
                self.assertNotIn(bridge.token, output.getvalue())
                if stage.startswith('setup-'):
                    self.assertFalse(hasattr(bridge, 'listener'))
                else:
                    self.assertTrue(bridge.stopped.is_set())
                    self.assertEqual(bridge.listener.fileno(), -1)
                    self.assertTrue(all(not worker.is_alive() for worker in bridge.workers))

    def test_windows_terminal_connection_passes_its_rgb_hint(self):
        output = io.StringIO()
        with (patch.object(sys, 'platform', 'win32'),
              patch.dict(os.environ, {'WT_SESSION': 'terminal-session', 'TERM_PROGRAM': '', 'COLORTERM': ''}),
              patch.object(output, 'isatty', return_value=True) as isatty,
              patch.object(picker, 'configured_login', return_value='alice'),
              patch.object(picker, 'EditorBridge'),
              patch.object(picker, 'prepare_editor_credentials', return_value=False),
              patch.object(windows_ssh, 'set_terminal_title'),
              patch.object(picker, 'ssh_command', return_value=['ssh']) as command,
              patch.object(picker.subprocess, 'run', return_value=subprocess.CompletedProcess(['ssh'], 0)),
              redirect_stdout(output)):
            self.assertEqual(picker.connect('vm-alias', 'tcp'), 0)
        isatty.assert_called_once_with()
        command.assert_called_once_with('vm-alias', None, rgb=True)

    def test_connect_without_remote_dalftui_never_starts_or_forwards_the_bridge(self):
        output = io.StringIO()
        with (patch.object(picker, 'configured_login', return_value='alice'),
              patch.object(picker, 'EditorBridge') as bridge,
              patch.object(picker, 'prepare_editor_credentials', return_value=False) as prepare,
              patch.object(picker, 'cleanup_editor_bridge') as cleanup,
              patch.object(picker.subprocess, 'run',
                           return_value=subprocess.CompletedProcess(['ssh'], 0)) as run,
              patch.dict(os.environ, {vscode.SOCKET_ENV: 'stale-endpoint',
                                      vscode.TOKEN_ENV: 'stale-token',
                                      'TMUX': 'local-session', 'TMUX_PANE': '%9'}),
              redirect_stdout(output), redirect_stderr(output)):
            self.assertEqual(picker.connect('vm-alias', 'tcp'), 0)
        bridge.return_value.__enter__.assert_not_called()
        cleanup.assert_not_called()
        prepare.assert_called_once()
        self.assertTrue(prepare.call_args.kwargs['check_installation'])
        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertEqual(command, picker.ssh_command('vm-alias'))
        self.assertNotIn('-R', command)
        self.assertNotIn('ExitOnForwardFailure=yes', command)
        for name in (vscode.SOCKET_ENV, vscode.TOKEN_ENV, 'TMUX', 'TMUX_PANE'):
            self.assertNotIn(name, run.call_args.kwargs['env'])
        self.assertEqual(output.getvalue(), 'Connecting to vm-alias …\n')

    def test_configured_username_and_unset_username_use_real_ssh_config(self):
        if not shutil.which(picker.ssh_executable()):
            self.skipTest('OpenSSH is not installed')
        if sys.platform == 'win32':
            windows_ssh.secure_ssh_directory(self.root)
        config = self.root / 'ssh config with spaces'
        config.write_text('Host vm-alias\n    HostName 127.0.0.1\n    User alice\n')
        with patch.object(picker, 'SSH_CONFIG', config):
            self.assertEqual(picker.configured_login('vm-alias'), 'alice')
            self.assertIsNone(picker.configured_login('another-alias'))


if __name__ == '__main__':
    unittest.main()
