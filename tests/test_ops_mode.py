"""Run generated Debian/Ubuntu programs with fake tools and a private tmux server."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dalftui import ssh
from dalftui.linux import ops, remote_bootstrap


@unittest.skipIf(sys.platform == 'win32', 'Generated programs run on Linux servers')
class OpsProgramsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='dalftui-ops-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.bin = self.directory / 'bin'
        self.bin.mkdir()
        self.home = self.directory / 'home'
        self.home.mkdir()
        self.log = self.directory / 'commands.jsonl'
        self.shell_log = self.directory / 'shells'
        for name in ('sh', 'timeout', 'sleep', 'date'):
            target = shutil.which(name)
            if target:
                (self.bin / name).symlink_to(target)
        self.shell = self.tool('login-shell', 'printf "%s\\n" "$*" >> "$SHELL_LOG"\nexit 0\n')
        self.env = dict(os.environ, HOME=str(self.home), PATH=str(self.bin), SHELL=str(self.shell),
                        COMMAND_LOG=str(self.log), SHELL_LOG=str(self.shell_log),
                        TMUX='stale', TMUX_PANE='%old', DALFTUI_EDITOR_TOKEN='stale',
                        DALFTUI_EDITOR_SOCKET='stale')
        self.tmux = self.bin / 'tmux'
        self.tmux.write_text(f'#!{sys.executable}\n' + '''import json, os, sys
with open(os.environ['COMMAND_LOG'], 'a', encoding='utf-8') as log:
    log.write(json.dumps(sys.argv[1:]) + '\\n')
assert 'TMUX' not in os.environ and 'TMUX_PANE' not in os.environ
if os.environ.get('FAIL_TMUX_COMMAND') == sys.argv[1]:
    sys.exit(1)
if sys.argv[1] == 'new-session':
    print('$42 %70')
elif sys.argv[1] == 'split-window':
    print('%71' if '-v' in sys.argv else '%72')
''', encoding='utf-8')
        self.tmux.chmod(0o755)
        self.tool('apt-get', 'printf "%s\\n" "$*" > "$APT_LOG"\nprintf "%s\\n" "0 upgraded (cached)"\n')
        self.env['APT_LOG'] = str(self.directory / 'apt-command')

    def tool(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/sh\n' + body, encoding='utf-8')
        path.chmod(0o755)
        return path

    def run_script(self, script, **env):
        try:
            return subprocess.run(['/bin/sh', '-c', script], env=dict(self.env, **env),
                                  cwd=self.directory, input='', capture_output=True, text=True, timeout=12)
        except subprocess.TimeoutExpired as error:
            raise AssertionError(f'Remote program timed out: stdout={error.stdout!r}; stderr={(error.stderr or b"")[-3000:]!r}') from None

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_plain_bypasses_tmux_and_clears_stale_editor_credentials(self):
        self.shell.write_text('#!/bin/sh\nprintf "%s:%s:%s:%s" "${TMUX-unset}" "${TMUX_PANE-unset}" '
                              '"${DALFTUI_EDITOR_TOKEN-unset}" "${DALFTUI_EDITOR_SOCKET-unset}"\n')
        result = self.run_script(remote_bootstrap.session_script(mode='plain'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'unset:unset:unset:unset')
        self.assertFalse(self.log.exists())

    def test_saved_check_quotes_exact_command_and_keeps_shell_after_failure(self):
        literal = "quoted ' \" ; $value"
        for command, expected in (("printf '%s' " + shlex.quote(literal) + '; exit 23', 'Check exit status: 23'),
                                  ('sleep 30 & wait', 'Check timed out.')):
            with self.subTest(command=command):
                check = ssh.SavedCheck("check's name", command, 1)
                result = self.run_script(remote_bootstrap.session_script(mode='check', check=check))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(expected, result.stdout)
                if 'exit 23' in command:
                    self.assertIn(literal, result.stdout)
                self.assertTrue(self.shell_log.exists())
                self.assertFalse(self.log.exists())

    def test_missing_timeout_skips_check_and_opens_shell(self):
        (self.bin / 'timeout').unlink()
        result = self.run_script(ops.check_script('unsafe without timeout', 'echo SHOULD_NOT_RUN', 30))
        self.assertIn('check was not run', result.stdout)
        self.assertNotIn('SHOULD_NOT_RUN', result.stdout)
        self.assertTrue(self.shell_log.exists())

    def test_overview_hides_success_status_but_reports_failures_before_opening_shell(self):
        for command, expected in (('true', ''), ('exit 1', 'Some status information is unavailable.'),
                                  ('exit 23', 'System overview could not finish (exit 23).'),
                                  ('sleep 30 & wait', 'System overview timed out; some sections may be missing.')):
            with self.subTest(command=command):
                self.shell_log.unlink(missing_ok=True)
                result = self.run_script(ops.check_script('system overview', command, 1, overview=True))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, 'ERR  ' + expected + '\n' if expected else '')
                self.assertTrue(self.shell_log.exists())
        (self.bin / 'timeout').unlink()
        result = self.run_script(ops.check_script('system overview', 'echo SHOULD_NOT_RUN', 1, overview=True))
        self.assertEqual(result.stdout, 'ERR  System overview unavailable: timeout is missing.\n')

    def test_package_status_only_simulates_and_labels_cached_metadata(self):
        result = self.run_script(ops.package_status_script())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(self.env['APT_LOG']).read_text(encoding='utf-8').strip(), '--simulate -o Debug::NoLocking=1 upgrade')
        self.assertIn('Cached metadata only; no online refresh performed.', result.stdout)
        self.assertNotIn('up to date', result.stdout.lower())
        self.tool('apt-get', 'exit 17\n')
        result = self.run_script(ops.package_status_script())
        self.assertEqual(result.returncode, 17)
        self.assertIn('could not determine', result.stdout)

    def test_ops_creates_three_panes_and_focuses_shell_without_touching_other_sessions(self):
        result = self.run_script(remote_bootstrap.session_script(mode='ops'))
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.commands()
        self.assertEqual(commands[0][0], 'new-session')
        self.assertNotIn('-A', commands[0])
        self.assertEqual([command[0] for command in commands].count('split-window'), 2)
        self.assertEqual(commands[-2:], [['select-pane', '-t', '%71'], ['attach-session', '-t', '$42']])
        self.assertFalse(any(command[0] in ('kill-session', 'kill-server', 'list-sessions') for command in commands))
        for command in commands[1:]:
            if '-t' in command:
                self.assertIn(command[command.index('-t') + 1], ('$42', '%70', '%71', '%72'))

    def test_pane_commands_fall_back_from_htop_and_report_journal_permission_errors(self):
        result = self.run_script(remote_bootstrap.session_script(mode='ops'))
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.commands()
        self.tool('top', 'printf "%s\\n" TOP_STARTED\n')
        monitor = self.run_script(commands[0][-1])
        self.assertIn('using top', monitor.stdout)
        self.assertIn('TOP_STARTED', monitor.stdout)
        self.tool('journalctl', 'printf "%s\\n" "Permission denied" >&2\nexit 1\n')
        journal_command = next(command[-1] for command in commands if command[0] == 'split-window' and '-h' in command)
        journal = self.run_script(journal_command)
        self.assertIn('Permission denied', journal.stderr)
        self.assertIn('Journal ended with status 1', journal.stdout)
        shell_command = next(command[-1] for command in commands if command[0] == 'split-window' and '-v' in command)
        shell = self.run_script(shell_command)
        self.assertIn('System overview', shell.stdout)
        self.assertNotIn('Cached metadata only', shell.stdout)
        self.assertFalse(Path(self.env['APT_LOG']).exists())
        self.assertEqual(len(self.shell_log.read_text().splitlines()), 3)

    def test_partial_setup_failure_cleans_up_only_the_new_session(self):
        result = self.run_script(remote_bootstrap.session_script(mode='ops'), FAIL_TMUX_COMMAND='split-window')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commands()[-1], ['kill-session', '-t', '$42'])
        self.assertIn('opening a shell', result.stdout)
        self.assertTrue(self.shell_log.exists())

    def test_creation_failure_does_not_kill_an_existing_session(self):
        result = self.run_script(remote_bootstrap.session_script(mode='ops'), FAIL_TMUX_COMMAND='new-session')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.commands()), 1)
        self.assertIn('opening a shell', result.stdout)

    def test_missing_tmux_and_small_terminal_use_a_shell(self):
        self.tool('stty', 'printf "10 30\\n"\n')
        result = self.run_script(remote_bootstrap.session_script(mode='ops'))
        self.assertIn('at least 40 columns', result.stdout)
        self.assertFalse(self.log.exists())
        self.tmux.unlink()
        result = self.run_script(remote_bootstrap.session_script(mode='ops'))
        self.assertIn('tmux is unavailable', result.stdout)
        self.assertTrue(self.shell_log.exists())

    @unittest.skipUnless(shutil.which('tmux'), 'tmux is required for the private-server layout test')
    def test_real_tmux_layout_preserves_existing_pane_and_selects_full_width_shell(self):
        executable = shutil.which('tmux')
        socket = str(self.directory / 'private-tmux.sock')
        env = dict(self.env, TMUX_TMPDIR=str(self.directory))
        env.pop('TMUX', None)
        env.pop('TMUX_PANE', None)
        command = [executable, '-S', socket, '-f', '/dev/null']

        def tmux(*args):
            return subprocess.run([*command, *args], env=env, capture_output=True, text=True, timeout=5)

        self.addCleanup(tmux, 'kill-server')
        self.shell.write_text('#!/bin/sh\nexec /bin/sleep 60\n')
        created = tmux('new-session', '-d', '-s', 'existing', '-P', '-F', '#{pane_id}:#{pane_pid}', '/bin/sleep 60')
        self.assertEqual(created.returncode, 0, created.stderr)
        tmux('set-option', '-g', 'default-shell', '/bin/sh')
        self.tmux.write_text('#!/bin/sh\n'
                             'if [ "$1" = attach-session ]; then\n'
                             f'  exec {shlex.join(command)} list-panes -t "$3" '
                             "-F '#{pane_left} #{pane_top} #{pane_width} #{pane_height} #{pane_active}'\n"
                             'fi\n' + f'exec {shlex.join(command)} "$@"\n')
        result = self.run_script(remote_bootstrap.session_script(mode='ops'))
        self.assertEqual(result.returncode, 0, result.stderr)
        panes = [list(map(int, line.split())) for line in result.stdout.splitlines()]
        self.assertEqual(len(panes), 3)
        bottom = max(panes, key=lambda pane: pane[1])
        self.assertEqual((bottom[0], bottom[2], bottom[4]), (0, 120, 1))
        top_row = min(pane[1] for pane in panes)
        self.assertEqual(sum(pane[1] == top_row for pane in panes), 2)
        existing = tmux('list-panes', '-t', 'existing', '-F', '#{pane_id}:#{pane_pid}')
        self.assertEqual(existing.stdout, created.stdout)


if __name__ == '__main__':
    unittest.main()
