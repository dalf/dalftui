"""Exercise the local and remote tmux session-start policy without a live server."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
STARTER = ROOT / 'tmux-start.sh'


@unittest.skipIf(sys.platform == 'win32', 'The tmux entrypoint runs in a POSIX shell')
class TmuxStartTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='dalftui-tmux-start-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.bin = self.directory / 'bin'
        self.bin.mkdir()
        self.log = self.directory / 'command'

        tmux = self.bin / 'tmux'
        tmux.write_text(
            '#!/bin/sh\n'
            'case "$1" in\n'
            '  list-sessions) printf "%b" "$TEST_SESSION_ROWS"; exit 0 ;;\n'
            '  has-session) [ "$3" = "$TEST_VALID_SESSION" ]; exit ;;\n'
            'esac\n'
            'printf "%s\\n" "$@" > "$TEST_COMMAND_LOG"\n'
            '[ "${TMUX-unset}" = unset ] && [ "${TMUX_PANE-unset}" = unset ] || exit 99\n'
            'exit "${TEST_TMUX_STATUS:-0}"\n')
        tmux.chmod(0o755)

        shell = self.bin / 'test-shell'
        shell.write_text('#!/bin/sh\nprintf "shell\\n%s\\n" "$@" > "$TEST_COMMAND_LOG"\n'
                         'exit "${TEST_SHELL_STATUS:-0}"\n')
        shell.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.defpath,
                        SHELL=str(shell), TEST_COMMAND_LOG=str(self.log),
                        TEST_SESSION_ROWS='', TEST_VALID_SESSION='',
                        TMUX='stale', TMUX_PANE='%9')

    def run_starter(self, rows, selection='', valid_session=''):
        env = dict(self.env, TEST_SESSION_ROWS=rows, TEST_VALID_SESSION=valid_session)
        return subprocess.run(['/bin/sh', str(STARTER)], input=selection, env=env,
                              cwd=self.directory, capture_output=True, text=True, timeout=5)

    def command(self):
        return self.log.read_text().splitlines()

    def test_no_session_creates_zero(self):
        result = self.run_starter('')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.command(), ['new-session', '-A', '-s', '0'])

    def test_one_detached_session_attaches_it(self):
        result = self.run_starter('$5 0\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.command(), ['attach-session', '-t', '$5'])

    def test_one_attached_session_creates_an_independent_session(self):
        result = self.run_starter('$5 1\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.command(), ['new-session'])

    def test_multiple_sessions_default_to_new(self):
        result = self.run_starter('$5 0\n$9 1\n', '\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.command(), ['new-session'])
        self.assertIn('[s] shell', result.stdout)

    def test_multiple_sessions_can_attach_by_id(self):
        result = self.run_starter('$5 0\n$9 1\n', '$5\n', '$5')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.command(), ['attach-session', '-t', '$5'])

    def test_multiple_sessions_can_start_a_plain_login_shell(self):
        result = self.run_starter('$5 0\n$9 1\n', 's\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.command(), ['shell', '-l'])

    def test_invalid_session_returns_to_the_prompt(self):
        result = self.run_starter('$5 0\n$9 1\n', 'missing\nq\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.log.exists())
        self.assertIn('No such tmux session: missing', result.stderr)

    def test_copied_and_installed_entrypoints_forward_arguments_from_an_unrelated_directory(self):
        checkout = self.directory / "checkout's $cash ; & é $(probe)"
        policy = checkout / 'dalftui/linux/tmux-start.sh'
        policy.parent.mkdir(parents=True)
        shutil.copy2(STARTER, checkout / 'tmux-start.sh')
        shutil.copy2(ROOT / 'dalftui/linux/tmux-start.sh', policy)
        policy.write_text('printf "%s\\0" "$@" > "$TEST_FORWARD_ARGS"\n' + policy.read_text())
        installed = self.directory / 'home/.config/dalftui'
        installed.parent.mkdir(parents=True)
        installed.symlink_to(checkout, target_is_directory=True)
        outside = self.directory / 'unrelated directory'
        outside.mkdir()
        argument_log = self.directory / 'forward-arguments'
        arguments = ['with spaces', '', "apostrophe's", '$cash ; & é $(probe)', '*?[]']
        env = dict(self.env, TEST_FORWARD_ARGS=str(argument_log), TEST_TMUX_STATUS='23')
        for entrypoint in (checkout / 'tmux-start.sh', installed / 'tmux-start.sh'):
            with self.subTest(entrypoint=entrypoint):
                result = subprocess.run(['/bin/sh', str(entrypoint), *arguments],
                                        cwd=outside, env=env, capture_output=True,
                                        text=True, timeout=5)
                self.assertEqual(result.returncode, 23, result.stderr)
                self.assertEqual(result.stdout + result.stderr, '')
                self.assertEqual(argument_log.read_bytes().split(b'\0')[:-1],
                                 [argument.encode('utf-8') for argument in arguments])
                self.assertEqual(self.command(), ['new-session', '-A', '-s', '0'])

    def test_entrypoint_propagates_attach_and_plain_shell_status(self):
        self.env['TEST_TMUX_STATUS'] = '17'
        result = self.run_starter('$5 0\n')
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertEqual(self.command(), ['attach-session', '-t', '$5'])
        self.env['TEST_SHELL_STATUS'] = '23'
        result = self.run_starter('$5 0\n$9 1\n', 's\n')
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual(self.command(), ['shell', '-l'])

    def test_cancel_and_eof_keep_their_exit_statuses(self):
        for selection, status in (('q\n', 0), ('', 1)):
            with self.subTest(selection=selection):
                result = self.run_starter('$5 0\n$9 1\n', selection)
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertFalse(self.log.exists())

    def test_missing_tmux_keeps_the_local_error_and_status(self):
        (self.bin / 'tmux').unlink()
        for command in ('dirname', 'sh'):
            (self.bin / command).symlink_to(shutil.which(command))
        self.env['PATH'] = str(self.bin)
        result = self.run_starter('')
        self.assertEqual(result.returncode, 127)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, 'tmux is not installed on this host.\n')
        self.assertFalse(self.log.exists())


if __name__ == '__main__':
    unittest.main()
