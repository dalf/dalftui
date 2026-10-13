"""Exercise the local and remote tmux session-start policy."""
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
STARTER = ROOT / 'bin/tmux-start.sh'
# Without an SSH host label the session drops any label an earlier launch left.
UNLABELLED = [';', 'set-option', '-u', '@dalftui_host']
REMOTE = '10.8.0.9 50000 10.8.0.1 22'
TAKEOVER_MESSAGE = "printf '%s\\n' 'Another terminal took over this tmux session.'; sleep 3"

# Make the pseudo-terminal the child's controlling terminal, so Ctrl+C sends SIGINT.
CONTROLLING_TERMINAL = ('import fcntl, os, sys, termios\n'
                        'fcntl.ioctl(0, termios.TIOCSCTTY, 0)\n'
                        'os.execvp(sys.argv[1], sys.argv[1:])\n')

FAKE_TMUX = '''import json, os, sys
args = sys.argv[1:]
if 'TMUX' in os.environ or 'TMUX_PANE' in os.environ:
    sys.exit(99)
rows = os.environ.get('TEST_SESSION_ROWS', '')
if args[0] == 'list-sessions':
    print(rows, end='')
    sys.exit(0)
if args[0] == 'list-clients':
    print(os.environ.get('TEST_CLIENT_ROWS', ''), end='')
    sys.exit(0)
def current(target):
    """Return a listed session's current client count, or None once it is gone."""
    if target in os.environ.get('TEST_GONE', '').split():
        return None
    for row in rows.splitlines():
        session, attached = row.split(' ')[:2]
        if session == target:
            return os.environ.get('TEST_CURRENT_CLIENTS', attached)
    return None
if args[0] == 'has-session':
    sys.exit(0 if current(args[args.index('-t') + 1]) is not None else 1)
if args[0] == 'display-message':
    if '-t' not in args:
        print('vm')
        sys.exit(0)
    # Like tmux, a missing target prints nothing and still succeeds.
    clients = current(args[args.index('-t') + 1])
    if clients is not None:
        print(clients)
    sys.exit(0)
if args[0] == 'detach-client':
    with open(os.environ['TEST_DETACH_LOG'], 'a', encoding='utf-8') as log:
        log.write(json.dumps(args) + '\\n')
    sys.exit(0)
with open(os.environ['TEST_COMMAND_LOG'], 'wb') as log:
    log.write(b''.join(os.fsencode(arg) + b'\\n' for arg in args))
# Stand in for the pane: record what reaches the terminal once tmux starts.
if 'TEST_PANE_INPUT' in os.environ:
    import select, time
    received = b''
    deadline = time.monotonic() + 0.6
    while (remaining := deadline - time.monotonic()) > 0:
        if select.select([0], [], [], remaining)[0]:
            received += os.read(0, 1024)
    with open(os.environ['TEST_PANE_INPUT'], 'wb') as log:
        log.write(received)
sys.exit(int(os.environ.get('TEST_TMUX_STATUS', '0')))
'''


class Terminal:
    """Run a command on a pseudo-terminal and type into it like a user."""
    def __init__(self, test, command, *, env, cwd, size=None):
        # These modules exist only on POSIX; this file is also imported on Windows.
        import pty
        import termios
        self.test = test
        self.master, self.slave = pty.openpty()
        test.addCleanup(os.close, self.master)
        test.addCleanup(os.close, self.slave)
        if size:
            termios.tcsetwinsize(self.slave, size)
        self.process = subprocess.Popen(
            [sys.executable, '-c', CONTROLLING_TERMINAL, *command],
            stdin=self.slave, stdout=self.slave, stderr=self.slave,
            env=env, cwd=cwd, start_new_session=True)
        test.addCleanup(self.stop)
        self.output = b''
        self.position = 0

    def stop(self):
        if self.process.poll() is None:
            self.process.kill()
        self.wait(5)

    def wait(self, timeout):
        """Wait for the child while reading its output.

        On macOS an exiting session leader waits until its terminal output has
        been read, so waiting without reading can time out even after SIGKILL.
        """
        deadline = time.monotonic() + timeout
        while (status := self.process.poll()) is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(self.process.args, timeout)
            self.read(min(remaining, 0.05))
        return status

    def read(self, timeout):
        ready, _, _ = select.select([self.master], [], [], timeout)
        if not ready:
            return False
        try:
            data = os.read(self.master, 65536)
        except OSError:
            return False
        self.output += data
        return bool(data)

    def expect(self, text, timeout=5):
        """Wait for text after the previous expectation."""
        expected = text.encode()
        deadline = time.monotonic() + timeout
        while (found := self.output.find(expected, self.position)) < 0:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or (not self.read(remaining) and self.process.poll() is not None):
                self.test.fail(f'{text!r} not shown; output: {self.text()!r}')
        self.position = found + len(expected)

    def send(self, data):
        os.write(self.master, data.encode() if isinstance(data, str) else data)

    def finish(self, timeout=5):
        status = self.wait(timeout)
        while self.read(0.1):
            pass
        return status

    def text(self):
        return self.output.decode(errors='replace').replace('\r\n', '\n')

    def line_mode_restored(self):
        import termios
        flags = termios.tcgetattr(self.slave)[3]
        return bool(flags & termios.ICANON and flags & termios.ECHO)


@unittest.skipIf(sys.platform == 'win32', 'The tmux entrypoint runs in a POSIX shell')
class TmuxStartTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='dalftui-tmux-start-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.bin = self.directory / 'bin'
        self.bin.mkdir()
        self.log = self.directory / 'command'
        self.detach_log = self.directory / 'detach'

        tmux = self.bin / 'tmux'
        tmux.write_text(f'#!{sys.executable}\n' + FAKE_TMUX, encoding='utf-8')
        tmux.chmod(0o755)

        # No installed agent-alias helper unless a test adds one.
        self.config = self.directory / 'config'
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.defpath,
                        TEST_COMMAND_LOG=str(self.log), TEST_DETACH_LOG=str(self.detach_log),
                        TEST_SESSION_ROWS='', TMUX='stale', TMUX_PANE='%9',
                        XDG_CONFIG_HOME=str(self.config))
        for name in ('SSH_CONNECTION', 'SSH_CLIENT', 'dalftui_host_label'):
            self.env.pop(name, None)

    def run_starter(self, rows, selection='', **env):
        env = dict(self.env, TEST_SESSION_ROWS=rows, **env)
        return subprocess.run(['/bin/sh', str(STARTER)], input=selection, env=env,
                              cwd=self.directory, capture_output=True, text=True, timeout=5)

    def terminal(self, rows, **env):
        return Terminal(self, ['/bin/sh', str(STARTER)],
                        env=dict(self.env, TEST_SESSION_ROWS=rows, **env), cwd=self.directory)

    def command(self):
        return self.log.read_text().splitlines()

    def detached(self):
        return [json.loads(line) for line in self.detach_log.read_text().splitlines()]

    def assert_nothing_started(self):
        self.assertFalse(self.log.exists())
        self.assertFalse(self.detach_log.exists())

    def test_no_session_creates_zero_without_mirroring_a_racing_first_client(self):
        for env in ({}, {'SSH_CONNECTION': REMOTE}):
            with self.subTest(env=env):
                result = self.run_starter('', **env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.command(), ['new-session', '-A', '-D', '-s', '0', *UNLABELLED])

    def test_one_detached_session_attaches_it_and_detaches_late_clients(self):
        for env in ({}, {'SSH_CONNECTION': REMOTE}):
            with self.subTest(env=env):
                result = self.run_starter('$5 0 work\n', **env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.command(), ['attach-session', '-d', '-t', '$5', *UNLABELLED])
                self.assertEqual(result.stdout, '')

    def test_ops_sessions_never_count(self):
        ops = '$7 0 dalftui-ops-123\n$8 1 dalftui-ops-456\n'
        for rows, expected in ((ops, ['new-session', '-A', '-D', '-s', '0']),
                               ('$5 0 work\n' + ops, ['attach-session', '-d', '-t', '$5'])):
            with self.subTest(rows=rows):
                result = self.run_starter(rows, SSH_CONNECTION=REMOTE)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.command(), expected + UNLABELLED)

    def test_one_attached_session_creates_an_independent_session_only_locally(self):
        result = self.run_starter('$5 1 0\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.command(), ['new-session', *UNLABELLED])
        self.log.unlink()
        # Over SSH the attached client may be a connection that died while its laptop slept.
        terminal = self.terminal('$5 1 0\n', SSH_CONNECTION=REMOTE)
        terminal.expect('[1] attach   [n] new session (default)   [q] cancel')
        terminal.expect('Choice [n]: ')
        self.assertFalse(self.log.exists())
        terminal.send('\r')
        self.assertEqual(terminal.finish(), 0, terminal.text())
        self.assertEqual(self.command(), ['new-session', *UNLABELLED])
        self.assertFalse(self.detach_log.exists())

    def test_without_a_terminal_the_menu_refuses_and_never_takes_over(self):
        for rows, env in (('$5 1 0\n', {'SSH_CONNECTION': REMOTE}),
                          ('$5 0 work\n$9 1 0\n', {}),
                          ('$5 0 work\n$9 1 0\n', {'SSH_CONNECTION': REMOTE})):
            with self.subTest(rows=rows, env=env):
                result = self.run_starter(rows, '1\ny\n', **env)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, '')
                self.assertEqual(result.stderr,
                                 'Choosing a tmux session needs a terminal; nothing was started.\n')
                self.assert_nothing_started()

    def test_menu_lists_sessions_and_client_details_without_a_shell_option(self):
        if not Path('/proc/self/environ').exists():
            self.skipTest('Client origins are read from /proc')
        remote_env = dict(self.env, SSH_CONNECTION='10.8.0.2 51000 10.8.0.1 22')
        local_env = dict(self.env)
        clients = []
        for env in (remote_env, local_env):
            process = subprocess.Popen(['sleep', '30'], env=env)
            self.addCleanup(process.wait)
            self.addCleanup(process.kill)
            clients.append(process.pid)
        now = int(time.time())
        client_rows = (f'$5 {clients[0]} {now - 11130} {now - 7990} /dev/pts/4\n'
                       f'$9 {clients[1]} {now - 200000} {now - 330} /dev/pts/7\n'
                       f'$9 999999999 {now - 150} {now - 150} /dev/pts/8\n'
                       '$7 1 1 1 /dev/pts/9\n')
        terminal = self.terminal('$5 1 0\n$6 0 work\n$9 2 long name\n$7 1 dalftui-ops-1\n',
                                 TEST_CLIENT_ROWS=client_rows, SSH_CONNECTION=REMOTE)
        terminal.expect('Choice [n]: ')
        terminal.send('q')
        self.assertEqual(terminal.finish(), 0, terminal.text())
        lines = terminal.text().splitlines()
        start = lines.index('tmux sessions on vm:')
        self.assertEqual(lines[start + 1:start + 6], [
            '  1  0          attached  pts/4 from 10.8.0.2, connected 3h05m ago, last key 2h13m ago',
            '  2  work       detached',
            '  3  long name  attached  pts/7 local, connected 2d07h ago, last key 5m ago',
            '                          pts/8, connected 2m ago, last key 2m ago',
            '[1-3] attach   [n] new session (default)   [q] cancel'])
        self.assertNotIn('dalftui-ops', terminal.text())
        self.assertNotIn('[s]', terminal.text())
        self.assert_nothing_started()

    def test_single_keystrokes_attach_a_detached_session_with_d(self):
        terminal = self.terminal('$5 0 work\n$9 1 0\n', SSH_CONNECTION=REMOTE)
        terminal.expect('[1-2] attach')
        terminal.expect('Choice [n]: ')
        terminal.send('1')
        self.assertEqual(terminal.finish(), 0, terminal.text())
        self.assertEqual(self.command(), ['attach-session', '-d', '-t', '$5', *UNLABELLED])
        self.assertFalse(self.detach_log.exists())
        self.assertTrue(terminal.line_mode_restored())

    def test_declining_a_takeover_returns_to_the_list(self):
        terminal = self.terminal('$5 0 work\n$9 1 0\n', SSH_CONNECTION=REMOTE)
        terminal.expect('Choice [n]: ')
        terminal.send('2')
        terminal.expect('Session 0 has a client. Take it over (its window closes)? [y/N] ')
        terminal.send('\r')
        terminal.expect('tmux sessions on vm:')
        terminal.expect('Choice [n]: ')
        terminal.send('2')
        terminal.expect('[y/N] ')
        terminal.send('x')
        terminal.expect('Choice [n]: ')
        terminal.send('q')
        self.assertEqual(terminal.finish(), 0, terminal.text())
        self.assert_nothing_started()

    def test_takeover_detaches_only_that_sessions_clients_with_a_message(self):
        label = "alice@prod-é;$x #{host}"
        terminal = self.terminal('$5 0 work\n$9 2 0\n', SSH_CONNECTION=REMOTE,
                                 dalftui_host_label=label)
        terminal.expect('Choice [n]: ')
        terminal.send('2')
        terminal.expect('Session 0 has 2 clients. Take it over (their windows close)? [y/N] ')
        terminal.send('Y')
        self.assertEqual(terminal.finish(), 0, terminal.text())
        self.assertEqual(self.detached(), [['detach-client', '-s', '$9', '-E', TAKEOVER_MESSAGE]])
        self.assertEqual(self.command(), ['attach-session', '-d', '-t', '$9',
                                          ';', 'set-option', '@dalftui_host', label])

    def test_current_state_decides_between_attach_and_takeover(self):
        # The list said detached, but another terminal attached meanwhile.
        terminal = self.terminal('$5 0 work\n$9 0 0\n', SSH_CONNECTION=REMOTE,
                                 TEST_CURRENT_CLIENTS='1')
        terminal.expect('Choice [n]: ')
        terminal.send('1')
        terminal.expect('Session work has a client.')
        terminal.send('n')
        terminal.expect('Choice [n]: ')
        terminal.send('q')
        self.assertEqual(terminal.finish(), 0, terminal.text())
        self.assert_nothing_started()

    def test_vanished_session_returns_to_the_list(self):
        terminal = self.terminal('$5 0 work\n$9 1 0\n', SSH_CONNECTION=REMOTE, TEST_GONE='$5')
        terminal.expect('Choice [n]: ')
        terminal.send('1')
        terminal.expect('Session work no longer exists.')
        terminal.expect('Choice [n]: ')
        terminal.send('q')
        self.assertEqual(terminal.finish(), 0, terminal.text())
        self.assert_nothing_started()

    def test_keys_typed_just_after_a_choice_never_reach_the_pane(self):
        pane = self.directory / 'pane'
        many = ''.join(f'${number} 0 s{number}\n' for number in range(1, 13))
        # Each choice is followed by an Enter typed out of habit: at once, in the
        # same write, or later, as over a slow SSH connection.
        for rows, keys, expected, delay in (
                ('$5 0 work\n$9 1 0\n', ['1'], ['attach-session', '-d', '-t', '$5'], 0.1),
                ('$5 0 work\n$9 1 0\n', ['1'], ['attach-session', '-d', '-t', '$5'], 0.3),
                ('$5 0 work\n$9 1 0\n', ['1'], ['attach-session', '-d', '-t', '$5'], None),
                ('$5 0 work\n$9 1 0\n', ['n'], ['new-session'], 0.1),
                ('$5 0 work\n$9 1 0\n', ['2', 'y'], ['attach-session', '-d', '-t', '$9'], 0.1),
                ('$5 0 work\n$9 1 0\n', ['2', 'y'], ['attach-session', '-d', '-t', '$9'], 0.3),
                ('$5 0 work\n$9 1 0\n', ['2', 'y'], ['attach-session', '-d', '-t', '$9'], None),
                (many, ['12\r'], ['attach-session', '-d', '-t', '$12'], 0.1)):
            with self.subTest(keys=keys, delay=delay):
                for path in (self.log, self.detach_log, pane):
                    path.unlink(missing_ok=True)
                terminal = self.terminal(rows, SSH_CONNECTION=REMOTE, TEST_PANE_INPUT=str(pane))
                for prompt, key in zip(('Choice [n]: ', '[y/N] '), keys):
                    terminal.expect(prompt)
                    if delay is None:
                        terminal.send(key + '\r')
                        continue
                    terminal.send(key)
                    time.sleep(delay)
                    terminal.send('\r')
                deadline = time.monotonic() + 5
                while not self.log.exists():
                    self.assertLess(time.monotonic(), deadline, terminal.text())
                    terminal.read(0.05)
                # Later keys belong to the pane.
                terminal.send('z\r')
                self.assertEqual(terminal.finish(), 0, terminal.text())
                self.assertEqual(self.command(), expected + UNLABELLED)
                self.assertEqual(pane.read_bytes(), b'z\n')

    def test_an_enter_after_declining_does_not_create_a_session(self):
        terminal = self.terminal('$5 0 work\n$9 1 0\n', SSH_CONNECTION=REMOTE)
        terminal.expect('Choice [n]: ')
        terminal.send('2')
        terminal.expect('[y/N] ')
        terminal.send('n')
        time.sleep(0.1)
        terminal.send('\r')
        terminal.expect('Choice [n]: ')
        # A q typed at once would join an unread Enter as one answer.
        time.sleep(0.5)
        terminal.send('q')
        self.assertEqual(terminal.finish(), 0, terminal.text())
        self.assert_nothing_started()

    def test_enter_and_n_create_a_new_session(self):
        for key in ('\r', 'n', 'N'):
            with self.subTest(key=key):
                terminal = self.terminal('$5 0 work\n$9 1 0\n')
                terminal.expect('Choice [n]: ')
                terminal.send(key)
                self.assertEqual(terminal.finish(), 0, terminal.text())
                self.assertEqual(self.command(), ['new-session', *UNLABELLED])
                self.assertTrue(terminal.line_mode_restored())

    def test_q_and_ctrl_c_cancel_and_restore_the_terminal(self):
        for key, prompt in (('q', 'Choice [n]: '), ('\x03', 'Choice [n]: '),
                            ('\x03', '[y/N] ')):
            with self.subTest(key=key, prompt=prompt):
                terminal = self.terminal('$5 0 work\n$9 1 0\n', SSH_CONNECTION=REMOTE)
                terminal.expect('Choice [n]: ')
                if prompt != 'Choice [n]: ':
                    terminal.send('2')
                    terminal.expect(prompt)
                terminal.send(key)
                self.assertEqual(terminal.finish(), 0, terminal.text())
                self.assertTrue(terminal.line_mode_restored())
                self.assert_nothing_started()

    def test_end_of_input_exits_with_an_error(self):
        terminal = self.terminal('$5 0 work\n$9 1 0\n')
        terminal.expect('Choice [n]: ')
        terminal.send('\x04')
        self.assertEqual(terminal.finish(), 1, terminal.text())
        self.assert_nothing_started()

    def test_invalid_keys_return_to_the_list(self):
        terminal = self.terminal('$5 0 work\n$9 1 0\n')
        for key, message in (('x', 'Not a choice: x'), ('7', 'Not a choice: 7'),
                             ('0', 'Not a choice: 0'), ('\x1b[A', 'Not a choice.'),
                             # Shells differ on whether a multi-byte letter is printable.
                             ('é', 'Not a choice')):
            with self.subTest(key=key):
                terminal.expect('Choice [n]: ')
                terminal.send(key)
                terminal.expect(message)
        terminal.expect('Choice [n]: ')
        terminal.send('q')
        self.assertEqual(terminal.finish(), 0, terminal.text())
        self.assertEqual(terminal.text().count('tmux sessions on vm:'), 6)
        self.assert_nothing_started()

    def test_more_than_nine_sessions_use_a_typed_line(self):
        rows = ''.join(f'${number} 0 s{number}\n' for number in range(1, 13))
        # Leading zeros name the same row; the number never reaches tmux as a target.
        for typed, expected in (('12\n', ['attach-session', '-d', '-t', '$12']),
                                ('01\n', ['attach-session', '-d', '-t', '$1']),
                                ('0012\n', ['attach-session', '-d', '-t', '$12']),
                                (' n \n', ['new-session'])):
            with self.subTest(typed=typed):
                terminal = self.terminal(rows)
                terminal.expect('[1-12] attach')
                terminal.expect('Choice [n]: ')
                terminal.send(typed)
                self.assertEqual(terminal.finish(), 0, terminal.text())
                self.assertEqual(self.command(), expected + UNLABELLED)
                self.assertIn(' 12  s12  detached', terminal.text())
        terminal = self.terminal(rows)
        for typed in ('13', '00', '013'):
            terminal.expect('Choice [n]: ')
            terminal.send(typed + '\n')
            terminal.expect(f'Not a choice: {typed}\r\n')
        terminal.expect('Choice [n]: ')
        terminal.send('\x04')
        self.assertEqual(terminal.finish(), 1, terminal.text())

    def test_ssh_host_label_is_set_on_the_new_or_attached_session(self):
        label = "alice@prod-é;$x #{host}"
        suffix = [';', 'set-option', '@dalftui_host', label]
        self.env['dalftui_host_label'] = label
        for rows, expected in (('', ['new-session', '-A', '-D', '-s', '0']),
                               ('$5 0 work\n', ['attach-session', '-d', '-t', '$5']),
                               ('$5 1 0\n', ['new-session'])):
            with self.subTest(rows=rows):
                result = self.run_starter(rows)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.command(), expected + suffix)

    def install_alias_helper(self, output, status=0):
        helper = self.config / 'dalftui/bin/session_owner.py'
        helper.parent.mkdir(parents=True)
        helper.write_text('import os, sys\n'
                          'assert sys.argv[1:] == ["new"] and "TMUX" not in os.environ\n'
                          f'print({output!r})\nsys.exit({status})\n')

    def test_ssh_sessions_on_installed_hosts_start_with_an_agent_alias(self):
        if not Path('/proc/self/environ').exists():
            self.skipTest('Agent aliases need /proc')
        alias = '/run/user/1000/dalftui-agent/' + '0123456789abcdef' * 2
        self.install_alias_helper(alias)
        # The first pane inherits the alias; the option records it unless -A
        # attached an existing session that already has one.
        record = [';', 'if-shell', '-F', '#{?@dalftui_agent_alias,,1}',
                  f'set-option @dalftui_agent_alias {alias}']
        for rows, expected in (('', ['new-session', '-e', f'SSH_AUTH_SOCK={alias}',
                                     '-A', '-D', '-s', '0', *record]),
                               ('$5 0 work\n', ['attach-session', '-d', '-t', '$5'])):
            with self.subTest(rows=rows):
                result = self.run_starter(rows, SSH_CONNECTION=REMOTE)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.command(), expected + UNLABELLED)
        terminal = self.terminal('$5 1 0\n', SSH_CONNECTION=REMOTE)
        terminal.expect('Choice [n]: ')
        terminal.send('n')
        self.assertEqual(terminal.finish(), 0, terminal.text())
        self.assertEqual(self.command(), ['new-session', '-e', f'SSH_AUTH_SOCK={alias}', *record,
                                          *UNLABELLED])
        # Local terminals keep tmux's usual handling.
        result = self.run_starter('$5 1 0\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.command(), ['new-session', *UNLABELLED])

    def test_unavailable_or_unsafe_aliases_keep_the_raw_socket(self):
        if not Path('/proc/self/environ').exists():
            self.skipTest('Agent aliases need /proc')
        for output, status in (('/run/user/1000/dalftui-agent/' + 'a' * 32, 1), ('', 0),
                               ('relative/path', 0), ('/tmp/x y', 0), ("/tmp/$(probe);'", 0)):
            with self.subTest(output=output, status=status):
                shutil.rmtree(self.config, ignore_errors=True)
                self.install_alias_helper(output, status)
                result = self.run_starter('', SSH_CONNECTION=REMOTE)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.command(), ['new-session', '-A', '-D', '-s', '0', *UNLABELLED])

    def test_copied_and_installed_entrypoints_forward_arguments_from_an_unrelated_directory(self):
        checkout = self.directory / "checkout's $cash ; & é $(probe)"
        policy = checkout / 'dalftui/linux/tmux-start.sh'
        policy.parent.mkdir(parents=True)
        (checkout / 'bin').mkdir()
        shutil.copy2(STARTER, checkout / 'bin/tmux-start.sh')
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
        for entrypoint in (checkout / 'bin/tmux-start.sh', installed / 'bin/tmux-start.sh'):
            with self.subTest(entrypoint=entrypoint):
                result = subprocess.run(['/bin/sh', str(entrypoint), *arguments],
                                        cwd=outside, env=env, capture_output=True,
                                        text=True, timeout=5)
                self.assertEqual(result.returncode, 23, result.stderr)
                self.assertEqual(result.stdout + result.stderr, '')
                self.assertEqual(argument_log.read_bytes().split(b'\0')[:-1],
                                 [argument.encode('utf-8') for argument in arguments])
                self.assertEqual(self.command(), ['new-session', '-A', '-D', '-s', '0', *UNLABELLED])

    def test_entrypoint_propagates_attach_and_menu_statuses(self):
        self.env['TEST_TMUX_STATUS'] = '17'
        result = self.run_starter('$5 0 work\n')
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertEqual(self.command(), ['attach-session', '-d', '-t', '$5', *UNLABELLED])
        terminal = self.terminal('$5 0 work\n$9 1 0\n')
        terminal.expect('Choice [n]: ')
        terminal.send('1')
        self.assertEqual(terminal.finish(), 17, terminal.text())

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


@unittest.skipIf(sys.platform == 'win32', 'The tmux entrypoint runs in a POSIX shell')
@unittest.skipUnless(shutil.which('tmux'), 'tmux is required')
class RealTmuxStartTests(unittest.TestCase):
    """Run the policy against a disposable tmux server with real clients."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='dalftui-tmux-start-real-', dir='/tmp')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.bin = self.directory / 'bin'
        self.bin.mkdir()
        # A private TMUX_TMPDIR keeps the default socket away from real servers;
        # -f /dev/null keeps personal configuration out of the server.
        tmux = self.bin / 'tmux'
        tmux.write_text(f'#!/bin/sh\nexec {shutil.which("tmux")} -f /dev/null "$@"\n')
        tmux.chmod(0o755)
        home = self.directory / 'home'
        home.mkdir()
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.defpath,
                        HOME=str(home), TMUX_TMPDIR=str(self.directory), SHELL='/bin/sh',
                        TERM='xterm-256color')
        for name in ('TMUX', 'TMUX_PANE', 'SSH_CONNECTION', 'SSH_CLIENT', 'dalftui_host_label',
                     'XDG_CONFIG_HOME'):
            self.env.pop(name, None)
        self.addCleanup(self.tmux, 'kill-server')

    def tmux(self, *args):
        return subprocess.run(['tmux', *args], env=self.env, capture_output=True, text=True,
                              timeout=5).stdout

    def wait_for(self, predicate, message):
        deadline = time.monotonic() + 5
        while not predicate():
            if time.monotonic() > deadline:
                self.fail(message)
            time.sleep(0.05)

    def clients(self, session):
        return self.tmux('list-clients', '-t', session, '-F', '#{client_pid}').split()

    def test_takeover_replaces_the_old_client_and_leaves_other_sessions_alone(self):
        self.tmux('new-session', '-d', '-s', 'work', 'sleep 600')
        self.tmux('new-session', '-d', '-s', 'other', 'sleep 600')
        laptop = Terminal(self, [shutil.which('tmux'), '-f', '/dev/null', 'attach-session', '-t', 'work'],
                          env=dict(self.env, SSH_CONNECTION='10.8.0.2 51000 10.8.0.1 22'),
                          cwd=self.directory)
        other = Terminal(self, [shutil.which('tmux'), '-f', '/dev/null', 'attach-session', '-t', 'other'],
                         env=self.env, cwd=self.directory)
        self.wait_for(lambda: self.clients('work') and self.clients('other'), 'clients did not attach')
        box = Terminal(self, ['/bin/sh', str(STARTER)],
                       env=dict(self.env, SSH_CONNECTION='10.8.0.3 52000 10.8.0.1 22'),
                       cwd=self.directory)
        box.expect('work')
        box.expect('attached  ')
        if Path('/proc/self/environ').exists():
            box.expect('from 10.8.0.2, connected ')
        box.expect('Choice [n]: ')
        lines = box.text().splitlines()
        number = next(line.split()[0] for line in lines if ' work ' in line)
        box.send(number)
        box.expect('Session work has a client. Take it over (its window closes)? [y/N] ')
        box.send('y')
        # The message stays on screen for 3 s before the terminal closes.
        laptop.expect('Another terminal took over this tmux session.', timeout=10)
        started = time.monotonic()
        self.assertEqual(laptop.finish(10), 0, laptop.text())
        self.assertGreater(time.monotonic() - started, 2)
        self.assertIn('Another terminal took over this tmux session.', laptop.text())
        # The policy shell starts the new client as its child.
        self.wait_for(lambda: len(self.clients('work')) == 1 and
                      self.clients('work') != [str(laptop.process.pid)],
                      'the new client did not take over')
        self.assertEqual(self.clients('other'), [str(other.process.pid)])
        self.assertIsNone(other.process.poll())

    def menu(self):
        box = Terminal(self, ['/bin/sh', str(STARTER)],
                       env=dict(self.env, SSH_CONNECTION='10.8.0.3 52000 10.8.0.1 22'),
                       cwd=self.directory)
        box.expect('Choice [n]: ')
        return box

    @staticmethod
    def number(box, name):
        return next(line.split()[0] for line in box.text().splitlines()
                    if line.split()[1:2] == [name])

    def test_a_session_closed_while_the_menu_waits_returns_to_the_list(self):
        self.tmux('new-session', '-d', '-s', 'work', 'sleep 600')
        # A name that work prefixes: the check must not match it instead.
        self.tmux('new-session', '-d', '-s', 'workshop', 'sleep 600')
        box = self.menu()
        number = self.number(box, 'work')
        self.tmux('kill-session', '-t', '=work')
        box.send(number)
        box.expect('Session work no longer exists.')
        box.expect('workshop')
        box.expect('Choice [n]: ')
        self.assertNotIn(' work ', box.text()[box.position:])
        box.send('q')
        self.assertEqual(box.finish(), 0, box.text())
        self.assertEqual(self.clients('workshop'), [])

    def test_a_session_closed_while_the_takeover_question_waits_returns_to_the_list(self):
        self.tmux('new-session', '-d', '-s', 'work', 'sleep 600')
        self.tmux('new-session', '-d', '-s', 'other', 'sleep 600')
        laptop = Terminal(self, [shutil.which('tmux'), '-f', '/dev/null', 'attach-session', '-t', 'work'],
                          env=self.env, cwd=self.directory)
        self.wait_for(lambda: self.clients('work'), 'the laptop did not attach')
        box = self.menu()
        box.send(self.number(box, 'work'))
        box.expect('Take it over (its window closes)? [y/N] ')
        self.tmux('kill-session', '-t', '=work')
        self.assertEqual(laptop.finish(), 0, laptop.text())
        box.send('y')
        box.expect('Session work no longer exists.')
        box.expect('Choice [n]: ')
        box.send('q')
        self.assertEqual(box.finish(), 0, box.text())
        self.assertNotIn("can't find session", box.text())
        self.assertEqual(self.clients('other'), [])

    def test_an_enter_typed_after_the_choice_never_reaches_the_pane(self):
        self.tmux('new-session', '-d', '-s', 'other', 'sleep 600')
        # 0.3 s is a typing gap plus SSH latency; None sends both keys in one write.
        for index, delay in enumerate((0.1, 0.3, None)):
            with self.subTest(delay=delay):
                session = f'work{index}'
                typed = self.directory / f'typed-{index}'
                self.tmux('new-session', '-d', '-s', session, f'cat -v > {typed}')
                box = self.menu()
                number = self.number(box, session)
                if delay is None:
                    box.send(number + '\r')
                else:
                    box.send(number)
                    time.sleep(delay)
                    box.send('\r')
                self.wait_for(lambda session=session: len(self.clients(session)) == 1,
                              'the session was not attached')
                box.send('z\r')
                self.wait_for(lambda typed=typed: typed.exists() and typed.read_bytes().endswith(b'z\n'),
                              'the pane got no input')
                self.assertEqual(typed.read_bytes(), b'z\n')

    def test_a_lone_detached_session_is_attached_automatically(self):
        self.tmux('new-session', '-d', '-s', 'work', 'sleep 600')
        self.tmux('new-session', '-d', '-s', 'dalftui-ops-1', 'sleep 600')
        box = Terminal(self, ['/bin/sh', str(STARTER)],
                       env=dict(self.env, SSH_CONNECTION='10.8.0.3 52000 10.8.0.1 22'),
                       cwd=self.directory)
        self.wait_for(lambda: len(self.clients('work')) == 1, 'the session was not attached')
        self.assertEqual(self.clients('dalftui-ops-1'), [])
        self.assertNotIn(b'tmux sessions', box.output)


if __name__ == '__main__':
    unittest.main()
