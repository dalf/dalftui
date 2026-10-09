"""Open picked SSH hosts in Terminal.app or iTerm2 windows on macOS."""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import test_install as install_tests
from dalftui import host_picker
from dalftui.linux import ssh_picker

RUN, MKDTEMP = subprocess.run, tempfile.mkdtemp
PRINT_ARGUMENTS = 'import json, sys; print(json.dumps(sys.argv[1:]))'


@unittest.skipIf(sys.platform == 'win32', 'The .command file is a POSIX shell program')
class MacWindowTests(unittest.TestCase):
    def test_iterm2_clients_open_iterm_and_others_open_terminal(self):
        expected = [sys.executable, str(ROOT / 'bin/ssh_picker.py'), '--connect', 'prod', '--ops']
        for terminal_type, app in (('iTerm2 3.6.11', 'iTerm'), ('', 'Terminal'), ('xterm', 'Terminal')):
            with (self.subTest(terminal_type=terminal_type), patch.object(sys, 'platform', 'darwin'),
                  patch.object(ssh_picker, 'open_mac_window') as launch):
                ssh_picker.open_window(host_picker.HostAction('prod', 'ops'), terminal_type)
                launch.assert_called_once_with(expected, app)

    def test_command_file_is_private_quoted_and_removes_itself(self):
        command = [sys.executable, '-c', PRINT_ARGUMENTS, "alice@prod-é;$host'\"\\", '--check', 'a check']
        seen = {}

        def run_window(args, **kwargs):
            script = Path(args[-1])
            seen.update(args=args[:-1], suffix=script.suffix, kwargs=kwargs,
                        modes=[stat.S_IMODE(path.stat().st_mode) for path in (script.parent, script)],
                        output=RUN([str(script)], capture_output=True, text=True, check=True, timeout=15).stdout)
            seen['left'] = script.parent.exists()
            return subprocess.CompletedProcess(args, 0, '', '')

        with patch.object(ssh_picker.subprocess, 'run', side_effect=run_window):
            ssh_picker.open_mac_window(command, 'Terminal')
        self.assertEqual(seen['args'], ['open', '-a', 'Terminal'])
        self.assertEqual(seen['suffix'], '.command')
        self.assertEqual(seen['modes'], [0o700, 0o700])
        self.assertEqual(json.loads(seen['output']), command[3:])
        self.assertFalse(seen['left'])
        self.assertEqual(seen['kwargs']['stdin'], subprocess.DEVNULL)

    def test_failed_open_reports_the_error_and_removes_the_file(self):
        scripts = []

        def missing_app(args, **_):
            scripts.append(Path(args[-1]))
            return subprocess.CompletedProcess(args, 1, '', "Unable to find application named 'iTerm'\n")

        with patch.object(ssh_picker.subprocess, 'run', side_effect=missing_app):
            with self.assertRaisesRegex(RuntimeError, "^Unable to find application named 'iTerm'$"):
                ssh_picker.open_mac_window(['true'], 'iTerm')
        self.assertFalse(scripts[0].parent.exists())


class MacPickerKeyTests(install_tests.TmuxFixture):
    profile = 'macos'

    def prefix(self):
        return {shlex.split(line)[3]: line for line in self.tmux('list-keys', '-T', 'prefix').splitlines()}

    def test_macos_binds_h_and_other_profiles_remove_it(self):
        self.start()
        self.do_reload()
        self.assertNotIn('F2', self.prefix())
        self.assertRegex(self.prefix()['h'], 'bin/ssh_picker.py --terminal-type .*client_termtype')
        for profile in ('server', 'desktop'):  # Profile switches keep earlier bindings.
            with self.subTest(profile=profile):
                self.install(profile='macos')
                self.do_reload()
                self.install(profile=profile)
                self.do_reload()
                self.assertNotIn('h', self.prefix())

    @unittest.skipIf(sys.platform == 'win32', 'Needs a pseudo-terminal')
    def test_prefix_h_passes_the_pressing_clients_terminal_type_to_the_picker(self):
        import pty  # pylint: disable=import-outside-toplevel
        import select  # pylint: disable=import-outside-toplevel
        self.start()
        self.do_reload()
        record, recorder = self.directory / 'picker.json', self.directory / 'record.py'
        recorder.write_text('import json, os, sys\n'
                            'open(sys.argv[1], "w").write(json.dumps([os.getcwd(), *sys.argv[2:]]))\n')
        # The popup runs this instead of uv and the picker.
        self.tmux('set-environment', '-gh', 'DALFTUI_PYTHON',
                  shlex.join([sys.executable, str(recorder), str(record)]))
        pid, client = pty.fork()
        if not pid:
            os.execvpe('tmux', [*self.command, 'attach', '-t', 'verify'], dict(self.env, TERM='xterm-256color'))
        self.addCleanup(os.waitpid, pid, 0)
        self.addCleanup(os.close, client)

        def answer(seconds, keys=b''):
            os.write(client, keys)
            until = time.monotonic() + seconds
            while time.monotonic() < until and not record.exists():
                if select.select([client], [], [], 0.1)[0] and b'\x1b[>q' in os.read(client, 65536):
                    os.write(client, b'\x1bP>|iTerm2 3.6.11 \'$x\x1b\\')  # XTVERSION reply.
        answer(2)
        answer(0.3, b'\x02')
        answer(10, b'h')
        # Only letters, digits, '-', '.' and spaces reach the shell; older tmux also escapes the reply.
        expected = re.sub(r'[^-.0-9A-Za-z ]', '', self.tmux('list-clients', '-F', '#{client_termtype}'))
        self.assertEqual(json.loads(record.read_text()),
                         [str(self.repo), 'bin/ssh_picker.py', '--terminal-type', expected])


@unittest.skipUnless(os.environ.get('DALFTUI_TEST_MACOS_GUI') == '1' and sys.platform == 'darwin',
                     'Set DALFTUI_TEST_MACOS_GUI=1 on macOS to open a real Terminal.app window')
class RealTerminalWindowTests(unittest.TestCase):
    def test_terminal_app_runs_the_command_and_the_file_is_removed(self):
        directory = Path(MKDTEMP(prefix='dalftui-gui-'))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        marker = directory / 'marker'
        created = []

        def mkdtemp(**kwargs):
            created.append(Path(MKDTEMP(**kwargs)))
            return str(created[-1])

        with patch.object(ssh_picker.tempfile, 'mkdtemp', side_effect=mkdtemp):
            ssh_picker.open_mac_window([sys.executable, '-c', 'import pathlib, sys; pathlib.Path(sys.argv[1]).touch()',
                                        str(marker)], 'Terminal')
        until = time.monotonic() + 60
        while not marker.exists() and time.monotonic() < until:
            time.sleep(0.2)
        self.assertTrue(marker.exists(), 'Terminal.app did not run the command')
        self.assertFalse(created[0].exists())


if __name__ == '__main__':
    unittest.main()
