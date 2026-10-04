"""Windows-compatible connection tests; no curses, tmux, or desktop GUI required."""
import importlib.util
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
        self.local_app_data = self.root / 'local application data'

    def make_code_installation(self, name="VS Code with spaces \u00e9"):
        installation = self.root / name
        cli = installation / 'resources/app/out/cli.js'
        cli.parent.mkdir(parents=True)
        cli.touch()
        application = installation / 'Code.exe'
        application.touch()
        return application, cli

    def configured_editor_env(self, application):
        config = self.local_app_data / vscode.WINDOWS_CONFIG
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps({'code': str(application)}, ensure_ascii=False),
                          encoding='utf-8')
        return dict(os.environ, LOCALAPPDATA=str(self.local_app_data))

    def test_connect_cli_imports_without_curses(self):
        with patch.dict(sys.modules, {'curses': None}):
            module = load_picker('no_curses_picker')
        self.assertIsNone(module.curses)
        with patch.object(module, 'connect', return_value=0) as connect:
            with patch.object(sys, 'argv', ['ssh-picker.py', '--connect', 'vm-alias']):
                self.assertEqual(module.main(), 0)
        connect.assert_called_once_with('vm-alias', None)

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

    def test_local_editor_cli_does_not_require_tmux_and_reports_failures_locally(self):
        folder = str(self.root)
        with patch.object(sys, 'argv', ['vscode.py', '--folder', folder]):
            with patch.object(vscode, 'launch') as launch:
                self.assertEqual(vscode.main(), 0)
                launch.assert_called_once_with(folder)
            with patch.object(vscode, 'launch', side_effect=RuntimeError('test editor missing')):
                with patch.object(vscode.subprocess, 'run') as run:
                    self.assertEqual(vscode.main(), 1)
                run.assert_not_called()

    def test_windows_picker_connects_selected_host_without_curses_or_alacritty(self):
        with patch.object(picker.sys, 'platform', 'win32'):
            with patch.object(picker, 'pick_fzf', return_value='vm-alias') as choose:
                with patch.object(picker, 'connect', return_value=17) as connect:
                    with patch.object(picker, 'open_window') as window:
                        with patch.object(sys, 'argv', ['ssh-picker.py']):
                            self.assertEqual(picker.main(), 17)
        choose.assert_called_once_with()
        connect.assert_called_once_with('vm-alias', None)
        window.assert_not_called()

    def test_cancelled_picker_does_not_open_ssh(self):
        with patch.object(picker, 'pick_fzf', return_value=None):
            with patch.object(picker, 'connect') as connect:
                with patch.object(sys, 'argv', ['ssh-picker.py', '--pick']):
                    self.assertEqual(picker.main(), 0)
        connect.assert_not_called()

    def test_fzf_receives_only_tagged_hosts_and_ignores_personal_output_settings(self):
        result = subprocess.CompletedProcess(['fzf'], 0, 'server-two\r\n')
        with patch.object(picker.shutil, 'which', return_value='fzf.exe'):
            with patch.object(picker, 'target_hosts', return_value=['server-one', 'server-two']):
                with patch.dict(os.environ, {'FZF_DEFAULT_OPTS': '--multi --print-query',
                                              'FZF_DEFAULT_OPTS_FILE': 'personal-options'}):
                    with patch.object(picker.subprocess, 'run', return_value=result) as run:
                        self.assertEqual(picker.pick_fzf(), 'server-two')
        self.assertEqual(run.call_args.kwargs['input'], 'server-one\nserver-two\n')
        self.assertNotIn('FZF_DEFAULT_OPTS', run.call_args.kwargs['env'])
        self.assertNotIn('FZF_DEFAULT_OPTS_FILE', run.call_args.kwargs['env'])
        self.assertFalse(run.call_args.kwargs.get('shell', False))

    def test_fzf_cancel_no_match_and_unexpected_output(self):
        with patch.object(picker.shutil, 'which', return_value='fzf.exe'):
            for code in (1, 130):
                with self.subTest(code=code):
                    with patch.object(picker.subprocess, 'run',
                                      return_value=subprocess.CompletedProcess(['fzf'], code, '')):
                        self.assertIsNone(picker.pick_fzf(['server']))
            for code, output in ((2, ''), (0, 'github.com\n'), (0, 'server\nother\n')):
                with self.subTest(code=code, output=output):
                    with patch.object(picker.subprocess, 'run',
                                      return_value=subprocess.CompletedProcess(['fzf'], code, output)):
                        with self.assertRaises(RuntimeError):
                            picker.pick_fzf(['server'])

    def test_missing_fzf_or_empty_host_list_has_actionable_error(self):
        with patch.object(picker.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'setup-windows.ps1'):
                picker.pick_fzf(['server'])
        with patch.object(picker.shutil, 'which', return_value='fzf.exe'):
            with self.assertRaisesRegex(RuntimeError, 'Tag dalftui'):
                picker.pick_fzf([])

    def test_picker_tag_evaluation_uses_real_windows_ssh_and_include_config(self):
        if not shutil.which(picker.ssh_executable()):
            self.skipTest('OpenSSH is not installed')
        probe = subprocess.run([picker.ssh_executable(), '-G', '-F', os.devnull,
                                '-o', 'Tag=dalftui', '--', 'localhost'],
                               capture_output=True, text=True, timeout=10)
        if probe.returncode:
            self.skipTest('OpenSSH 9.4+ is required for SSH tags')
        picker.secure_ssh_directory(self.root)
        config = self.root / 'config'
        included = self.root / 'servers included.conf'
        included.write_text('Host vm-alias\n Tag dalftui\n User alice\n'
                            'Host github.com gitlab.com\n User git\n')
        config.write_text(f'Include "{included.as_posix()}"\n')
        with patch.object(picker, 'SSH_CONFIG', config):
            self.assertEqual(picker.target_hosts(), ['vm-alias'])
            self.assertEqual(picker.configured_login('vm-alias'), 'alice')

    def test_native_fzf_filters_unicode_hosts_using_picker_options(self):
        if not shutil.which('fzf'):
            self.skipTest('fzf is not installed')
        real_run = subprocess.run

        def noninteractive(command, **kwargs):
            return real_run([*command, '--filter=prod'], **kwargs)

        with patch.object(picker.subprocess, 'run', side_effect=noninteractive):
            self.assertEqual(picker.pick_fzf(['dev-vm', 'prod-é']), 'prod-é')

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
        env = self.configured_editor_env(app)
        local_folder = str(self.root / "local project's %cash & #?\u00e9")
        remote_folder = "/home/alice/project.with.dot 'quoted' %PATH% & #?é"
        result = subprocess.CompletedProcess(['Code.exe'], 0, '', '')
        with patch.object(vscode, 'WINDOWS', True):
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
                                            'configured VS Code installation is missing.*setup-windows.ps1.*VSCodePath'):
                    vscode.launch(str(self.root), env=env)
            run.assert_not_called()
            with self.assertRaisesRegex(RuntimeError, 'VS Code is not configured.*setup-windows.ps1'):
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
            except BaseException as error:
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
                def cleanup_after_stop(*args):
                    self.assertTrue(bridge.stopped.is_set())
                    self.assertEqual(bridge.listener.fileno(), -1)
                output = io.StringIO()
                with (patch.object(picker, 'configured_login', return_value='alice'),
                      patch.object(picker, 'EditorBridge', return_value=bridge),
                      patch.object(picker, 'prepare_editor_credentials', side_effect=prepare_error) as prepare,
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
                self.assertTrue(bridge.stopped.is_set())
                self.assertEqual(bridge.listener.fileno(), -1)
                self.assertTrue(all(not worker.is_alive() for worker in bridge.workers))

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
