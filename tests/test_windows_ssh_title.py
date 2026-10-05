"""SSH tab titles are set locally, independently of remote tmux or shell output."""
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dalftui import ssh as picker
from dalftui.linux import ssh_picker as linux_ssh
from dalftui.windows import ssh as windows_ssh


class SshTitleTests(unittest.TestCase):
    def test_windows_terminal_title_preserves_unicode_and_removes_controls(self):
        with (patch.object(windows_ssh.ctypes, 'windll', create=True) as loader,
              patch.object(sys.stdout, 'isatty', return_value=True)):
            windows_ssh.set_terminal_title('alïce@prod-é;$host\x1b\x07\r\n\0')
        loader.kernel32.SetConsoleTitleW.assert_called_once_with('alïce@prod-é;$host')
        self.assertEqual(loader.kernel32.SetConsoleTitleW.argtypes, [windows_ssh.wintypes.LPCWSTR])
        self.assertEqual(loader.kernel32.SetConsoleTitleW.restype, windows_ssh.wintypes.BOOL)

    def test_windows_terminal_title_skips_redirected_output(self):
        output = io.StringIO()
        with (patch.object(windows_ssh.ctypes, 'windll', create=True) as loader,
              redirect_stdout(output)):
            windows_ssh.set_terminal_title('alice@prod')
        loader.kernel32.SetConsoleTitleW.assert_not_called()
        self.assertEqual(output.getvalue(), '')

    def test_windows_terminal_title_failure_is_nonfatal(self):
        for error in (None, OSError('No console')):
            with self.subTest(error=error):
                with (patch.object(windows_ssh.ctypes, 'windll', create=True) as loader,
                      patch.object(sys.stdout, 'isatty', return_value=True)):
                    loader.kernel32.SetConsoleTitleW.return_value = 0
                    loader.kernel32.SetConsoleTitleW.side_effect = error
                    windows_ssh.set_terminal_title('alice@prod')
                loader.kernel32.SetConsoleTitleW.assert_called_once_with('alice@prod')

    def test_linux_terminal_title_preserves_unicode_and_removes_controls(self):
        output = io.StringIO()
        with (redirect_stdout(output), patch.object(output, 'isatty', return_value=True),
              patch.object(output, 'flush', wraps=output.flush) as flush):
            linux_ssh.set_terminal_title('alïce@prod-é;$host\x1b\x07\r\n\0')
        self.assertEqual(output.getvalue(), '\x1b]2;alïce@prod-é;$host\x07')
        flush.assert_called_once()

    def test_linux_terminal_title_skips_redirected_output(self):
        output = io.StringIO()
        with redirect_stdout(output):
            linux_ssh.set_terminal_title('alice@prod')
        self.assertEqual(output.getvalue(), '')

    def test_linux_terminal_title_output_failure_is_nonfatal(self):
        for error in (OSError('No terminal'), UnicodeError('Unsupported encoding')):
            with self.subTest(error=error):
                output = io.StringIO()
                with (redirect_stdout(output), patch.object(output, 'isatty', return_value=True),
                      patch.object(output, 'write', side_effect=error) as write):
                    linux_ssh.set_terminal_title('alice@prod')
                write.assert_called_once()

    @unittest.skipUnless(sys.platform == 'linux', 'Requires a Linux pseudo-terminal')
    def test_linux_title_reaches_a_real_terminal(self):
        title = 'alïce@prod-é'
        master, slave = os.openpty()
        with os.fdopen(master, 'rb', buffering=0) as output:
            with os.fdopen(slave, 'wb') as terminal:
                result = subprocess.run(
                    [sys.executable, '-B', '-X', 'utf8', '-c',
                     'from dalftui.linux.ssh_picker import set_terminal_title; '
                     f'set_terminal_title({title!r})'],
                    cwd=ROOT, stdout=terminal, stderr=subprocess.PIPE, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read(512), f'\x1b]2;{title}\x07'.encode('utf-8'))

    def test_connect_sets_title_before_ssh_without_changing_connection_arguments(self):
        cases = (
            ('sibils-prod-ai', 'alexandre', None, 'alexandre@sibils-prod-ai'),
            ('alice@prod-alias', 'alice', None, 'alice@prod-alias'),
            ('prod-alias', None, 'entered-user', 'entered-user@prod-alias'),
            ('prod-é;$host', 'alïce', None, 'alïce@prod-é;$host'),
        )
        for host, user, login, title in cases:
            for platform, adapter, prepared in (
                    ('win32', windows_ssh, False), ('win32', windows_ssh, True),
                    ('linux', linux_ssh, False), ('linux', linux_ssh, True)):
                with self.subTest(host=host, platform=platform, bridge=prepared):
                    output = io.StringIO()
                    with (patch.object(sys, 'platform', platform),
                          patch.object(picker, 'configured_login', return_value=user) as lookup,
                          patch.object(adapter, 'set_terminal_title') as set_title,
                          patch('builtins.input', return_value=login or '') as prompt,
                          patch.object(picker, 'EditorBridge') as bridge,
                          patch.object(picker, 'prepare_editor_credentials', return_value=prepared) as prepare,
                          patch.object(picker, 'cleanup_editor_bridge'),
                          patch.object(picker, 'ssh_command', return_value=['ssh', '--', host]) as command,
                          patch.object(picker.subprocess, 'run') as run,
                          redirect_stdout(output)):
                        def run_ssh(command, title=title, set_title=set_title, **_kwargs):
                            set_title.assert_called_once_with(title)
                            return subprocess.CompletedProcess(command, 0)
                        run.side_effect = run_ssh
                        self.assertEqual(picker.connect(host, 'tcp'), 0)
                        run.assert_called_once()
                        self.assertEqual(run.call_args.args[0], command.return_value)
                        expected = (host, login, bridge.return_value) if prepared else (host, login)
                        command.assert_called_once_with(*expected)
                    lookup.assert_called_once_with(host)
                    set_title.assert_called_once_with(title)
                    if login:
                        prompt.assert_called_once_with(f'SSH login for {host}: ')
                    else:
                        prompt.assert_not_called()
                    self.assertEqual(bridge.call_args.args[0], f'{login}@{host}' if login else host)
                    self.assertEqual(prepare.call_args.args[:2], (host, login))
                    self.assertEqual(output.getvalue(), f'Connecting to {host} …\n')

    def test_connect_on_linux_does_not_call_windows_title_api(self):
        output = io.StringIO()
        with (patch.object(sys, 'platform', 'linux'),
              patch.object(picker, 'configured_login', return_value='alice'),
              patch.object(windows_ssh, 'set_terminal_title') as set_title,
              patch.object(picker, 'EditorBridge'),
              patch.object(picker, 'prepare_editor_credentials', return_value=False),
              patch.object(picker.subprocess, 'run',
                           return_value=subprocess.CompletedProcess(['ssh'], 0)),
              redirect_stdout(output), patch.object(output, 'isatty', return_value=True)):
            self.assertEqual(picker.connect('prod'), 0)
        set_title.assert_not_called()
        self.assertEqual(output.getvalue(), '\x1b]2;alice@prod\x07Connecting to prod …\n')


if __name__ == '__main__':
    unittest.main()
