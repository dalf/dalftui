"""Exercise the local and remote tmux session-start policy without a live server."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
STARTER = ROOT / 'tmux-start.sh'


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
            'printf "%s\\n" "$@" > "$TEST_COMMAND_LOG"\n')
        tmux.chmod(0o755)

        shell = self.bin / 'test-shell'
        shell.write_text('#!/bin/sh\nprintf "shell\\n%s\\n" "$@" > "$TEST_COMMAND_LOG"\n')
        shell.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.defpath,
                        SHELL=str(shell), TEST_COMMAND_LOG=str(self.log),
                        TEST_SESSION_ROWS='', TEST_VALID_SESSION='')

    def run_starter(self, rows, selection='', valid_session=''):
        env = dict(self.env, TEST_SESSION_ROWS=rows, TEST_VALID_SESSION=valid_session)
        return subprocess.run(['/bin/sh', str(STARTER)], input=selection, env=env,
                              capture_output=True, text=True, timeout=5)

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


if __name__ == '__main__':
    unittest.main()
