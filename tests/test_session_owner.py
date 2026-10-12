"""One client per tmux session, and the session's stable SSH agent alias.

Real-tmux tests run the installed configuration's hooks on a disposable server
(private TMUX_TMPDIR, HOME and XDG_RUNTIME_DIR) with fake agents that answer
with their own name, so routing is checked without keys or a real agent.
"""
from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import stat
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

from dalftui.linux import session_owner
from dalftui.linux.setup import MARKER, tmux_quote

STARTER = ROOT / 'bin/tmux-start.sh'
HELPER = ROOT / 'bin/session_owner.py'
TAKEOVER_MESSAGE = 'Another terminal took over this tmux session.'

# Make the pseudo-terminal the child's controlling terminal, like an SSH login.
CONTROLLING_TERMINAL = ('import fcntl, os, sys, termios\n'
                        'fcntl.ioctl(0, termios.TIOCSCTTY, 0)\n'
                        'os.execvp(sys.argv[1], sys.argv[1:])\n')

# Typed into a pane: report this shell's PID, its SSH_AUTH_SOCK and which agent answers.
PROBE = '''import os, socket, sys
path = os.environ.get('SSH_AUTH_SOCK', '')
try:
    connection = socket.socket(socket.AF_UNIX)
    connection.settimeout(2)
    connection.connect(path)
    answer = connection.recv(64).decode().strip()
except OSError as error:
    answer = 'unavailable'
with open(sys.argv[2] + '.tmp', 'w', encoding='utf-8') as report:
    report.write(f'{sys.argv[1]} {path} {answer}\\n')
os.replace(sys.argv[2] + '.tmp', sys.argv[2])
'''


class FakeAgent:
    """A Unix socket that answers every connection with the agent's name."""
    def __init__(self, test, directory, name):
        # OpenSSH-like layout: a private directory holding agent.<pid>.
        folder = Path(tempfile.mkdtemp(prefix='ssh-', dir=directory))
        self.path = str(folder / f'agent.{len(name)}{os.getpid()}')
        self.name = name
        self.listener = socket.socket(socket.AF_UNIX)
        self.listener.bind(self.path)
        self.listener.listen(8)
        self.listener.settimeout(0.2)
        self.running = True
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()
        test.addCleanup(self.stop)

    def serve(self):
        while self.running:
            try:
                connection, _ = self.listener.accept()
            except (socket.timeout, OSError):
                continue
            with connection:
                connection.sendall(self.name.encode() + b'\n')

    def stop(self):
        self.running = False
        self.thread.join(5)
        self.listener.close()


class Client:
    """A tmux client, or the launcher, on its own pseudo-terminal."""
    def __init__(self, test, command, env):
        import pty
        import termios
        master, slave = pty.openpty()
        termios.tcsetwinsize(slave, (30, 100))
        self.master = master
        self.process = subprocess.Popen([sys.executable, '-c', CONTROLLING_TERMINAL, *command],
                                        stdin=slave, stdout=slave, stderr=slave, env=env,
                                        start_new_session=True)
        os.close(slave)
        self.output = b''
        self.lock = threading.Lock()
        self.reader = threading.Thread(target=self.drain, daemon=True)
        self.reader.start()
        test.addCleanup(self.stop)

    def drain(self):
        while True:
            try:
                data = os.read(self.master, 65536)
            except OSError:
                return
            if not data:
                return
            with self.lock:
                self.output += data

    def text(self):
        with self.lock:
            return self.output.decode(errors='replace')

    def send(self, data):
        os.write(self.master, data.encode())

    def stop(self):
        # The launcher's tmux client is its child, in the same process group.
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self.process.wait(5)
        self.reader.join(5)
        if self.master is not None:
            os.close(self.master)
            self.master = None


@unittest.skipIf(sys.platform == 'win32', 'Agent aliases are for Linux tmux servers')
class AliasPathTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='dalftui-owner-paths-', dir='/tmp')
        self.addCleanup(temporary.cleanup)
        self.runtime = Path(temporary.name) / 'run'
        self.runtime.mkdir(mode=0o700)
        self.env = {'XDG_RUNTIME_DIR': str(self.runtime) + '/'}

    def test_runtime_directory_is_preferred_and_created_private(self):
        directory = session_owner.ensure_directory(self.env)
        self.assertEqual(directory, str(self.runtime / 'dalftui-agent'))
        info = os.lstat(directory)
        self.assertEqual((stat.S_IMODE(info.st_mode), info.st_uid), (0o700, os.getuid()))
        self.assertEqual(session_owner.candidate_directories(self.env)[-1],
                         f'/tmp/dalftui-agent-{os.getuid()}')

    def test_shared_or_redirected_directories_are_refused(self):
        shared = self.runtime / 'dalftui-agent'
        shared.mkdir(mode=0o755)
        shared.chmod(0o755)
        self.assertFalse(session_owner.private_directory(str(shared)))
        shared.rmdir()
        target = self.runtime / 'elsewhere'
        target.mkdir(mode=0o700)
        shared.symlink_to(target)
        self.assertFalse(session_owner.private_directory(str(shared)))
        self.assertIsNone(session_owner.alias_parts(str(shared / ('a' * 32))))

    def test_alias_paths_are_plain_keys_in_a_private_directory(self):
        directory = session_owner.ensure_directory(self.env)
        key = '0123456789abcdef' * 2
        self.assertEqual(session_owner.alias_parts(f'{directory}/{key}'), (directory, key))
        for alias in ('', 'relative/' + key, f'{directory}/../dalftui-agent/{key}',
                      f'{directory}/{key[:-1]}', f'{directory}/{key.upper()}',
                      f'{directory}/{key} ; rm -rf', f'{self.runtime}/{key}'):
            with self.subTest(alias=alias):
                self.assertIsNone(session_owner.alias_parts(alias))

    def test_agent_socket_refuses_aliases_and_non_sockets(self):
        directory = session_owner.ensure_directory(self.env)
        alias = f'{directory}/{"a" * 32}'
        agent = FakeAgent(self, self.runtime, 'laptop')
        other_alias = f'{directory}/{"b" * 32}'
        os.symlink(agent.path, other_alias)
        regular = self.runtime / 'regular'
        regular.write_text('', encoding='utf-8')
        directories = {directory}

        def environment(path):
            return {b'SSH_AUTH_SOCK': os.fsencode(path)}

        self.assertEqual(session_owner.agent_socket(environment(agent.path), alias, directories),
                         agent.path)
        for path in (alias, other_alias, str(regular), str(self.runtime / 'missing'), 'relative'):
            with self.subTest(path=path):
                self.assertIsNone(session_owner.agent_socket(environment(path), alias, directories))
        self.assertIsNone(session_owner.agent_socket({}, alias, directories))
        self.assertIsNone(session_owner.agent_socket(None, alias, directories))

    def test_loader_marker_matches_the_installer(self):
        # The helper runs on python3 older than setup's 3.11, so it keeps a copy.
        self.assertEqual(session_owner.LOADER_MARKER, MARKER)

    def test_hook_failures_are_kept_for_status(self):
        # Hook output would open the pane in view mode, so failures go to a file.
        with patch.dict(os.environ, self.env):
            session_owner.note_error(session_owner.TmuxError('no server'))
            self.assertRegex(session_owner.last_error(), r'^\S+ \S+ TmuxError: no server$')
            with patch.dict(os.environ, {'TMUX': ''}), redirect_stderr(io.StringIO()) as error:
                self.assertNotEqual(session_owner.main(['sync']), 0)
            self.assertIn('$TMUX is not set', error.getvalue())
            self.assertIn('$TMUX is not set', session_owner.last_error())

    def test_new_alias_reaches_the_launchers_agent_before_its_session_exists(self):
        # The launcher's tmux client inherits its environment, so the first
        # shell's agent works at once; an alias whose session never started is
        # collected once the launcher has had time to create it.
        agent = FakeAgent(self, self.runtime, 'laptop')
        with patch.dict(os.environ, dict(self.env, SSH_AUTH_SOCK=agent.path)), \
                patch.object(session_owner, 'hooks_installed', return_value=True):
            alias = session_owner.new_alias()
            self.assertIsNotNone(session_owner.alias_parts(alias))
            self.assertEqual(os.readlink(alias), agent.path)
            with patch.dict(os.environ, {'SSH_AUTH_SOCK': alias}):
                # Never an alias pointing at another alias.
                second = session_owner.new_alias()
            self.assertIsNotNone(session_owner.alias_parts(second))
            self.assertFalse(os.path.lexists(second))
            directory = os.path.dirname(alias)
            server = {'socket': '/tmp/tmux-test/default', 'pid': os.getpid()}
            session_owner.collect(server, set(), [directory])
            self.assertEqual(os.readlink(alias), agent.path)
            with patch.object(session_owner.time, 'time',
                              return_value=time.time() + session_owner.PENDING_SECONDS + 1):
                session_owner.collect(server, set(), [directory])
            self.assertFalse(os.path.lexists(alias))
            self.assertFalse(os.path.exists(alias + '.json'))
            self.assertTrue(stat.S_ISSOCK(os.stat(agent.path).st_mode))

    def test_alias_replacement_is_atomic_and_removal_spares_real_sockets(self):
        directory = session_owner.ensure_directory(self.env)
        alias = f'{directory}/{"c" * 32}'
        laptop = FakeAgent(self, self.runtime, 'laptop')
        box = FakeAgent(self, self.runtime, 'box')
        session_owner.point_alias(alias, laptop.path)
        self.assertEqual(os.readlink(alias), laptop.path)
        session_owner.point_alias(alias, box.path)
        self.assertEqual(os.readlink(alias), box.path)
        self.assertEqual(sorted(os.listdir(directory)), ['c' * 32])
        session_owner.point_alias(alias, None)
        self.assertFalse(os.path.lexists(alias))
        self.assertTrue(stat.S_ISSOCK(os.stat(box.path).st_mode))
        # Only our own symlink is ever removed, never a socket or a file.
        os.symlink(box.path, alias)
        session_owner.remove_alias(box.path)
        session_owner.remove_alias(alias)
        self.assertTrue(stat.S_ISSOCK(os.stat(box.path).st_mode))
        self.assertFalse(os.path.lexists(alias))


@unittest.skipIf(sys.platform == 'win32', 'Agent aliases are for Linux tmux servers')
@unittest.skipUnless(shutil.which('tmux'), 'tmux is required')
@unittest.skipUnless(Path('/proc/self/environ').exists(), 'Client environments are read from /proc')
class SessionOwnerTests(unittest.TestCase):
    """Drive the installed hooks on a disposable server with real clients."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='dalftui-owner-', dir='/tmp')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        home = self.directory / 'home'
        (home / '.config').mkdir(parents=True)
        (home / '.config/dalftui').symlink_to(ROOT, target_is_directory=True)
        # The installed server loader, without personal settings.
        (home / '.tmux.conf').write_text(f'{MARKER}\nset -g @dalftui_profile server\n'
                                         f'source-file {tmux_quote(ROOT / "config/tmux.conf")}\n',
                                         encoding='utf-8')
        runtime = self.directory / 'run'
        runtime.mkdir(mode=0o700)
        self.alias_directory = runtime / 'dalftui-agent'
        self.probe = self.directory / 'probe.py'
        self.probe.write_text(PROBE, encoding='utf-8')
        self.env = dict(os.environ, HOME=str(home), TMUX_TMPDIR=str(self.directory),
                        XDG_RUNTIME_DIR=str(runtime), SHELL='/bin/sh', TERM='xterm-256color',
                        ENV='', PS1='$ ')
        for name in ('TMUX', 'TMUX_PANE', 'SSH_CONNECTION', 'SSH_CLIENT', 'SSH_AUTH_SOCK',
                     'XDG_CONFIG_HOME', 'dalftui_host_label'):
            self.env.pop(name, None)
        self.addCleanup(self.tmux, 'kill-server')
        self.laptop_agent = FakeAgent(self, self.directory, 'laptop')
        self.box_agent = FakeAgent(self, self.directory, 'box')
        self.reports = 0

    def tmux(self, *args):
        return subprocess.run(['tmux', *args], env=self.env, capture_output=True, text=True,
                              timeout=10).stdout

    def wait_for(self, predicate, message, timeout=10):
        deadline = time.monotonic() + timeout
        while not (value := predicate()):
            if time.monotonic() > deadline:
                self.fail(message)
            time.sleep(0.05)
        return value

    def connect(self, address, agent=None, command=None):
        """An SSH-like login: its own SSH_CONNECTION and forwarded agent socket."""
        env = dict(self.env, SSH_CONNECTION=f'{address} 51000 10.8.0.1 22')
        if agent:
            env['SSH_AUTH_SOCK'] = agent.path
        return Client(self, command or ['/bin/sh', str(STARTER)], env)

    def attach(self, address, agent, session, *flags):
        return self.connect(address, agent, ['tmux', 'attach-session', *flags, '-t', session])

    def clients(self, session=None):
        args = ['-t', session] if session else []
        return self.tmux('list-clients', *args, '-F', '#{client_pid}').split()

    def client_pids(self, client):
        """The tmux client is the process itself, or the launcher's child."""
        pid = str(client.process.pid)
        children = Path(f'/proc/{pid}/task/{pid}/children')
        found = {pid}
        if children.exists():
            found.update(children.read_text(encoding='utf-8').split())
        return found

    def owned_by(self, session, client):
        attached = self.clients(session)
        return len(attached) == 1 and attached[0] in self.client_pids(client)

    def alias(self, session='$0'):
        return self.tmux('show-options', '-t', session, '-qv', '@dalftui_agent_alias').strip()

    def record(self, alias):
        try:
            return json.loads(Path(alias + '.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}

    def target(self, alias):
        try:
            return os.readlink(alias)
        except OSError:
            return None

    def probe_pane(self, pane):
        """Ask a running shell which agent its SSH_AUTH_SOCK reaches."""
        self.reports += 1
        report = self.directory / f'report-{self.reports}'
        self.tmux('send-keys', '-t', pane, '-l',
                  f'python3 {shlex.quote(str(self.probe))} $$ {shlex.quote(str(report))}')
        self.tmux('send-keys', '-t', pane, 'Enter')
        self.wait_for(report.exists, f'pane {pane} did not report')
        return report.read_text(encoding='utf-8').split()

    def first_pane(self):
        return self.wait_for(lambda: self.tmux('list-panes', '-t', '$0', '-F', '#{pane_id}').split(),
                             'no pane')[0]

    def start_laptop(self):
        laptop = self.connect('10.8.0.2', self.laptop_agent)
        alias = self.wait_for(self.alias, 'the launcher gave the session no alias')
        self.wait_for(lambda: self.target(alias) == self.laptop_agent.path,
                      'the alias did not reach the laptop agent')
        # The launcher's alias exists first; the session's first hook claims it.
        self.wait_for(lambda: str((self.record(alias).get('owner') or {}).get('pid'))
                      in self.client_pids(laptop), 'the laptop did not become the owner')
        return laptop, alias

    def test_first_pane_uses_the_alias_and_handover_moves_it_between_agents(self):
        laptop, alias = self.start_laptop()
        self.assertEqual(session_owner.alias_parts(alias), (str(self.alias_directory), Path(alias).name))
        self.assertEqual(stat.S_IMODE(os.lstat(self.alias_directory).st_mode), 0o700)
        pane = self.first_pane()
        shell, path, agent = self.probe_pane(pane)
        self.assertEqual((path, agent), (alias, 'laptop'))
        first = self.record(alias)
        self.assertIn(str(first['owner']['pid']), self.client_pids(laptop))
        self.assertEqual(first['owner']['origin'], '10.8.0.2')

        # The box takes over through the launcher's question.
        box = self.connect('10.8.0.3', self.box_agent)
        self.wait_for(lambda: 'Choice [n]: ' in box.text(), 'no session list')
        box.send('1')
        self.wait_for(lambda: 'Take it over' in box.text(), 'no takeover question')
        box.send('y')
        laptop.process.wait(10)
        self.assertIn(TAKEOVER_MESSAGE, laptop.text())
        self.wait_for(lambda: self.target(alias) == self.box_agent.path, 'the alias did not follow the box')
        self.assertEqual(self.probe_pane(pane), [shell, alias, 'box'])
        self.assertGreater(self.record(alias)['generation'], first['generation'])

        # Back to the laptop with a plain attach: the hook makes the newcomer the owner.
        laptop = self.attach('10.8.0.2', self.laptop_agent, '$0')
        box.process.wait(10)
        self.assertIn(TAKEOVER_MESSAGE, box.text())
        self.wait_for(lambda: self.owned_by('$0', laptop), 'the laptop did not take over')
        self.wait_for(lambda: self.target(alias) == self.laptop_agent.path, 'the alias did not return')
        self.assertEqual(self.probe_pane(pane), [shell, alias, 'laptop'])

        # New panes inherit the alias, not the socket tmux copied on attach.
        self.wait_for(lambda: self.tmux('show-environment', '-t', '$0', 'SSH_AUTH_SOCK').strip()
                      == f'SSH_AUTH_SOCK={alias}', 'the session environment was not pinned')
        window = self.tmux('new-window', '-d', '-t', '$0', '-P', '-F', '#{pane_id}').strip()
        self.assertEqual(self.probe_pane(window)[1:], [alias, 'laptop'])

    def test_first_shell_reaches_the_agent_while_it_starts(self):
        # tmux starts login shells: a startup file that uses the agent works in
        # the first pane of the first session and of a session made from the list.
        startup = self.directory / 'startup'
        startup.mkdir()
        Path(self.env['HOME'], '.profile').write_text(
            f'[ -z "$TMUX" ] || python3 {shlex.quote(str(self.probe))} $$ '
            f'{shlex.quote(str(startup))}/"$$"\n', encoding='utf-8')

        def reports(count):
            def finished():
                files = [path for path in startup.iterdir() if not path.name.endswith('.tmp')]
                return len(files) >= count and files
            files = self.wait_for(finished, 'the first shell did not report')
            return [path.read_text(encoding='utf-8').split()[1:] for path in files]

        _, alias = self.start_laptop()
        self.assertEqual(reports(1), [[alias, 'laptop']])
        box = self.connect('10.8.0.3', self.box_agent)
        self.wait_for(lambda: 'Choice [n]: ' in box.text(), 'no session list')
        box.send('n')
        other = self.wait_for(lambda: self.alias('$1'), 'the new session has no alias')
        self.assertIn([other, 'box'], reports(2))

    def test_new_panes_never_inherit_the_raw_socket_of_an_attaching_client(self):
        _, alias = self.start_laptop()
        self.wait_for(lambda: 'SSH_AUTH_SOCK' not in self.tmux(
            'show-options', '-t', '$0', '-v', 'update-environment').split() and
            self.tmux('show-options', '-t', '$0', 'update-environment'),
            'the session keeps copying SSH_AUTH_SOCK on attach')
        before = set(self.tmux('list-panes', '-s', '-t', '$0', '-F', '#{pane_id}').split())
        # A pane created in the same command as the attach, before any hook runs.
        box = self.connect('10.8.0.3', self.box_agent,
                           ['tmux', 'attach-session', '-d', '-t', '$0', ';', 'new-window'])
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            self.assertEqual(self.tmux('show-environment', '-t', '$0', 'SSH_AUTH_SOCK').strip(),
                             f'SSH_AUTH_SOCK={alias}')
        self.wait_for(lambda: self.owned_by('$0', box), 'the box did not take over')
        self.wait_for(lambda: self.target(alias) == self.box_agent.path, 'the alias did not follow the box')
        pane = self.wait_for(lambda: set(self.tmux('list-panes', '-s', '-t', '$0', '-F',
                                                   '#{pane_id}').split()) - before, 'no new pane')
        self.assertEqual(self.probe_pane(pane.pop())[1:], [alias, 'box'])

    def test_racing_attaches_leave_the_newest_client_whatever_order_the_hooks_run(self):
        self.tmux('new-session', '-d', '-s', 'work')
        # Hold the lock so both clients' hook runs queue up and see both clients.
        self.alias_directory.mkdir(mode=0o700, exist_ok=True)
        import fcntl
        descriptor = os.open(self.alias_directory / 'lock', os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        older = self.attach('10.8.0.2', None, 'work')
        self.wait_for(lambda: len(self.clients('work')) == 1, 'first client missing')
        newer = self.attach('10.8.0.3', None, 'work')
        self.wait_for(lambda: len(self.clients('work')) == 2, 'second client missing')
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        older.process.wait(10)
        self.assertIn(TAKEOVER_MESSAGE, older.text())
        self.wait_for(lambda: self.owned_by('work', newer), 'the newer client did not keep the session')
        self.assertIsNone(newer.process.poll())

    def test_a_client_moved_out_of_a_closed_session_never_takes_over(self):
        # With detach-on-destroy off, tmux moves the clients of a closing session
        # into another one; that is not a choice to take it over.
        for name in ('zero', 'one', 'two'):
            self.tmux('new-session', '-d', '-s', name)
        self.tmux('set-option', '-g', 'detach-on-destroy', 'off')
        mover = self.attach('10.8.0.2', None, 'zero')
        self.wait_for(lambda: self.clients('zero'), 'first client missing')
        # A client that switched before still arrives without a choice.
        mover_name = self.tmux('list-clients', '-t', 'zero', '-F', '#{client_name}').strip()
        self.tmux('switch-client', '-c', mover_name, '-t', 'one')
        self.wait_for(lambda: self.clients('one'), 'the client did not switch')
        self.tmux('kill-session', '-t', 'zero')
        user = self.attach('10.8.0.3', None, 'two')
        self.wait_for(lambda: self.owned_by('two', user), 'second client missing')
        self.tmux('kill-session', '-t', 'one')
        mover.process.wait(10)
        self.assertIn('is in use by another terminal.', mover.text())
        self.assertNotIn(TAKEOVER_MESSAGE, mover.text())
        time.sleep(0.5)
        self.assertTrue(self.owned_by('two', user))
        self.assertIsNone(user.process.poll())
        self.assertNotIn(TAKEOVER_MESSAGE, user.text())

    def test_detach_and_missing_forwarding_leave_the_alias_absent(self):
        laptop, alias = self.start_laptop()
        pane = self.first_pane()
        # An unexpected disconnect: the client dies without detaching.
        os.killpg(laptop.process.pid, signal.SIGKILL)
        laptop.process.wait(10)
        self.wait_for(lambda: not os.path.lexists(alias), 'a dead client kept the alias')
        box = self.attach('10.8.0.3', self.box_agent, '$0')
        self.wait_for(lambda: self.target(alias) == self.box_agent.path, 'the box did not get the alias')
        self.tmux('detach-client', '-s', '$0')
        box.process.wait(10)
        self.wait_for(lambda: self.target(alias) is None and not os.path.lexists(alias),
                      'detaching did not remove the alias')
        self.assertIsNone(self.record(alias)['owner'])
        # The shell keeps the alias; new agent connections fail until an owner returns.
        self.assertEqual(self.probe_pane(pane)[1:], [alias, 'unavailable'])
        self.assertTrue(stat.S_ISSOCK(os.stat(self.laptop_agent.path).st_mode))

        # An owner without a forwarded agent does not fall back to another agent.
        plain = self.attach('10.8.0.3', None, '$0')
        self.wait_for(lambda: self.owned_by('$0', plain), 'the client did not attach')
        self.wait_for(lambda: (self.record(alias).get('owner') or {}).get('origin') == '10.8.0.3',
                      'the agentless client did not become the owner')
        self.assertFalse(os.path.lexists(alias))
        self.assertEqual(self.probe_pane(pane)[1:], [alias, 'unavailable'])

    def test_a_late_detach_of_an_old_owner_keeps_the_new_owners_alias(self):
        laptop, alias = self.start_laptop()
        # Hold the lock so both the laptop's detach and the box's attach queue up.
        directory = str(self.alias_directory)
        import fcntl
        descriptor = os.open(os.path.join(directory, 'lock'), os.O_RDWR)
        self.addCleanup(os.close, descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        box = self.attach('10.8.0.3', self.box_agent, '$0', '-d')
        laptop.process.wait(10)
        self.wait_for(lambda: self.owned_by('$0', box), 'the box did not attach')
        time.sleep(0.5)
        self.assertEqual(self.target(alias), self.laptop_agent.path)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        self.wait_for(lambda: self.target(alias) == self.box_agent.path, 'the box did not get the alias')
        owner = self.record(alias)['owner']
        # Replaying the dead laptop's detach, however late, changes nothing.
        hook_env = dict(self.env, TMUX=self.server_variable())
        for args in (['sync'], ['sync', '--session=$0', f'--client={owner["name"]}x']):
            result = subprocess.run([sys.executable, str(HELPER), *args], env=hook_env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.target(alias), self.box_agent.path)
            self.assertEqual(self.record(alias)['owner'], owner)
        self.assertIsNone(box.process.poll())

    def server_variable(self):
        socket_path, pid = self.tmux('display-message', '-p', '#{socket_path} #{pid}').split()
        return f'{socket_path},{pid},0'

    def test_switching_moves_ownership_and_leaves_other_sessions_alone(self):
        laptop, alias = self.start_laptop()
        # A second aliased session, owned by the box.
        box = self.connect('10.8.0.3', self.box_agent)
        self.wait_for(lambda: 'Choice [n]: ' in box.text(), 'no session list')
        box.send('n')
        self.wait_for(lambda: self.alias('$1'), 'the second session has no alias')
        other = self.alias('$1')
        self.assertNotEqual(other, alias)
        self.wait_for(lambda: self.target(other) == self.box_agent.path, 'the box did not get its alias')
        # An unrelated session with its own client is never touched.
        self.tmux('new-session', '-d', '-s', 'side')
        side = self.attach('10.8.0.4', None, 'side')
        self.wait_for(lambda: self.clients('side'), 'side client missing')

        # The laptop switches into the box's session: it takes over there and
        # releases its own session's alias.
        laptop_name = self.tmux('list-clients', '-t', '$0', '-F', '#{client_name}').strip()
        self.tmux('switch-client', '-c', laptop_name, '-t', '$1')
        box.process.wait(10)
        self.assertIn(TAKEOVER_MESSAGE, box.text())
        self.wait_for(lambda: self.target(other) == self.laptop_agent.path, 'the switched-to alias did not move')
        self.wait_for(lambda: not os.path.lexists(alias), 'the switched-from alias stayed')
        self.assertIsNone(laptop.process.poll())
        self.assertIsNone(side.process.poll())
        self.assertEqual(len(self.clients('side')), 1)

    def test_session_close_and_server_restart_never_reuse_an_alias(self):
        laptop, alias = self.start_laptop()
        self.tmux('kill-session', '-t', '$0')
        laptop.process.wait(10)
        # Killing the last session ends the server before its hook can run;
        # the next server's first sync removes what the dead server left.
        self.wait_for(lambda: not self.tmux('list-sessions'), 'the server kept sessions')
        laptop, second = self.start_laptop()
        self.assertNotEqual(second, alias)
        self.wait_for(lambda: not os.path.lexists(alias) and not os.path.exists(alias + '.json'),
                      'the old alias was not collected')
        # Closing one of several sessions removes its alias and record at once.
        self.tmux('new-session', '-d', '-s', 'spare')
        self.tmux('kill-session', '-t', '$0')
        laptop.process.wait(10)
        self.wait_for(lambda: not os.path.lexists(second) and not os.path.exists(second + '.json'),
                      'closing the session left its alias')
        self.assertEqual(sorted(os.listdir(self.alias_directory)), ['lock'])

    def test_status_shows_the_alias_and_owner_and_enable_migrates_old_sessions(self):
        laptop, alias = self.start_laptop()
        pane = self.first_pane()
        report = shlex.quote(str(self.directory / 'status'))
        self.tmux('send-keys', '-t', pane, '-l',
                  f'python3 {shlex.quote(str(HELPER))} status > {report} 2>&1; mv {report} {report}.done')
        self.tmux('send-keys', '-t', pane, 'Enter')
        done = self.directory / 'status.done'
        self.wait_for(done.exists, 'status did not finish')
        text = done.read_text(encoding='utf-8')
        self.assertIn(f'Agent alias:  {alias}', text)
        self.assertIn(f'Alias target: {self.laptop_agent.path} (socket)', text)
        self.assertIn('from 10.8.0.2', text)
        self.assertIn('This shell:   uses the alias', text)
        self.assertIn('does not prove', text)

        # A session started without the launcher has no alias until enabled,
        # from inside tmux or from a plain shell outside it.
        for inside in (True, False):
            with self.subTest(inside=inside):
                old = self.tmux('new-session', '-d', '-P', '-F', '#{session_id}').strip()
                self.assertEqual(self.alias(old), '')
                box = self.attach('10.8.0.3', self.box_agent, old)
                self.wait_for(lambda old=old, box=box: self.owned_by(old, box), 'the box did not attach')
                env = dict(self.env, TMUX=self.server_variable()) if inside else self.env
                for _ in range(2):
                    result = subprocess.run([sys.executable, str(HELPER), 'enable', f'--session={old}'],
                                            env=env, capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    enabled = self.alias(old)
                    self.assertIsNotNone(session_owner.alias_parts(enabled))
                    self.assertIn(f'export SSH_AUTH_SOCK={enabled}', result.stdout)
                    # Applied before reporting success, without waiting for a hook.
                    self.assertEqual(self.target(enabled), self.box_agent.path)
                    self.assertIn(str(self.record(enabled)['owner']['pid']), self.client_pids(box))
                    self.assertEqual(self.tmux('show-environment', '-t', old, 'SSH_AUTH_SOCK').strip(),
                                     f'SSH_AUTH_SOCK={enabled}')
                    self.assertNotIn('SSH_AUTH_SOCK', self.tmux(
                        'show-options', '-t', old, '-v', 'update-environment').split())
                box.stop()
        self.assertIsNone(laptop.process.poll())

    def test_takeover_keeps_the_recorded_arrival_or_else_the_most_recent_one(self):
        # Without the hooks, two plain attaches mirror one session; then run the
        # helper as the hooks would, with and without tmux 3.3's hook_client.
        Path(self.env['HOME'], '.tmux.conf').write_text('', encoding='utf-8')
        self.tmux('new-session', '-d', '-s', 'work')
        self.tmux('new-session', '-d', '-s', 'side')
        side = self.attach('10.8.0.4', None, 'side')
        older = self.attach('10.8.0.2', None, 'work')
        self.wait_for(lambda: len(self.clients('work')) == 1, 'first client missing')
        time.sleep(1.1)  # tmux records activity in whole seconds.
        newer = self.attach('10.8.0.3', None, 'work')
        self.wait_for(lambda: len(self.clients('work')) == 2, 'second client missing')
        session = self.tmux('display-message', '-p', '-t', 'work', '#{session_id}').strip().lstrip('\\')
        hook_env = dict(self.env, TMUX=self.server_variable())

        def sync(client):
            result = subprocess.run([sys.executable, str(HELPER), 'sync', f'--session={session}',
                                     f'--client={client}'], env=hook_env, capture_output=True,
                                    text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)

        sync('')  # tmux 3.2: keep the most recently active client.
        older.process.wait(10)
        self.assertIn(TAKEOVER_MESSAGE, older.text())
        self.assertEqual(self.clients('work'), [str(newer.process.pid)])
        older = self.attach('10.8.0.2', None, 'work')
        self.wait_for(lambda: len(self.clients('work')) == 2, 'client did not return')
        names = dict(line.split() for line in
                     self.tmux('list-clients', '-F', '#{client_pid} #{client_name}').splitlines())
        # tmux 3.3+: the hooks record the newest arrival before any helper runs,
        # so a helper run for an earlier client still keeps the newest one.
        for option in ('@dalftui_joined', '@dalftui_attached'):
            self.tmux('set-option', '-t', 'work', option, names[str(newer.process.pid)])
        sync(names[str(older.process.pid)])
        older.process.wait(10)
        self.assertEqual(self.clients('work'), [str(newer.process.pid)])
        self.assertEqual(self.clients('side'), [str(side.process.pid)])

    def test_local_and_unhooked_launches_keep_the_raw_socket(self):
        # A local terminal never gets an alias.
        local = Client(self, ['/bin/sh', str(STARTER)], dict(self.env, SSH_AUTH_SOCK=self.laptop_agent.path))
        self.wait_for(lambda: self.clients('$0'), 'the local launch did not attach')
        self.assertEqual(self.alias(), '')
        self.assertEqual(self.probe_pane(self.first_pane())[1:], [self.laptop_agent.path, 'laptop'])
        local.stop()
        self.tmux('kill-server')
        # A server that has not loaded the hooks (not reloaded since an update).
        Path(self.env['HOME'], '.tmux.conf').write_text('', encoding='utf-8')
        self.connect('10.8.0.2', self.laptop_agent)
        self.wait_for(lambda: self.clients('$0'), 'the SSH launch did not attach')
        self.assertEqual(self.alias(), '')
        self.assertEqual(self.probe_pane(self.first_pane())[1:], [self.laptop_agent.path, 'laptop'])
        self.assertEqual(os.listdir(self.alias_directory), ['lock'])


if __name__ == '__main__':
    unittest.main()
