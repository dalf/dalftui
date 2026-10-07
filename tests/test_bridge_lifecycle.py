"""Portable bridge lifecycle tests using isolated sockets and harmless editor stubs."""
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dalftui import vscode


class ObservedBridge(vscode.EditorBridge):
    """Observe handler entry/completion without replacing request processing."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.observed = threading.Condition()
        self.started = 0
        self.finished = 0
        self.active = 0
        self.peak = 0

    def handle(self, connection, deadline):
        with self.observed:
            self.started += 1
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.observed.notify_all()
        try:
            super().handle(connection, deadline)
        finally:
            with self.observed:
                self.finished += 1
                self.active -= 1
                self.observed.notify_all()

    def wait_for(self, attribute, count):
        with self.observed:
            return self.observed.wait_for(lambda: getattr(self, attribute) >= count, timeout=5)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.launch_patch = patch.object(vscode, 'launch')
        self.launch = self.launch_patch.start()
        self.addCleanup(self.launch_patch.stop)

    def bridge(self, **kwargs):
        kwargs.setdefault('transport', 'tcp')
        return self.enterContext(ObservedBridge('fixed-host', **kwargs))

    def connect(self, bridge):
        connection = socket.socket(socket.AF_INET if bridge.transport == 'tcp' else socket.AF_UNIX)
        self.addCleanup(connection.close)
        connection.settimeout(5)
        connection.connect(('127.0.0.1', bridge.local_port)
                           if bridge.transport == 'tcp' else bridge.local_socket)
        return connection

    def background(self, function):
        done = threading.Event()
        outcome = []

        def run():
            try:
                outcome.append(function())
            # Report any background failure on the test's main thread.
            except BaseException as error:  # pylint: disable=broad-exception-caught
                outcome.append(error)
            finally:
                done.set()

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        return done, outcome, thread

    def trickle(self, connection):
        stop = threading.Event()
        sent = []

        def write():
            while not stop.is_set():
                try:
                    connection.sendall(b' ')
                    sent.append(time.monotonic())
                except OSError:
                    return
                stop.wait(0.04)

        thread = threading.Thread(target=write, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(stop.set)
        return stop, sent

    def valid(self, bridge, folder='/project'):
        endpoint = (f'tcp:127.0.0.1:{bridge.local_port}'
                    if bridge.transport == 'tcp' else bridge.local_socket)
        vscode.request(endpoint, folder, bridge.token)

    def recover(self, bridge):
        # Completion notification can precede the final socket close by a few
        # instructions. Retry a rejected connection while that slot is released.
        until = time.monotonic() + 5
        pause = threading.Event()
        while True:
            try:
                with bridge.lock:
                    available = len(bridge.connections) < bridge.max_connections
                if not available:
                    if time.monotonic() >= until:
                        self.fail('Connection capacity was not released')
                    pause.wait(0.02)
                    continue
                self.valid(bridge)
                while time.monotonic() < until:
                    with bridge.lock:
                        if len(bridge.connections) < bridge.max_connections:
                            return
                    pause.wait(0.02)
                self.fail('Completed request did not release capacity')
            except RuntimeError:
                if time.monotonic() >= until:
                    raise
                pause.wait(0.02)

    def assert_closed(self, connection):
        try:
            data = connection.recv(vscode.MAX_REQUEST + 1)
        except (ConnectionResetError, ConnectionAbortedError):
            return
        self.assertEqual(data, b'')

    def assert_rejected(self, bridge):
        try:
            connection = self.connect(bridge)
        except (ConnectionResetError, ConnectionAbortedError):
            # Windows may report the immediate close during connect itself.
            return
        self.assert_closed(connection)
        connection.close()

    def stop_bridge(self, bridge):
        done, outcome, thread = self.background(bridge.__exit__)
        self.assertTrue(done.wait(3), 'Bridge shutdown did not interrupt its handlers')
        thread.join()
        self.assertEqual(outcome, [None])
        self.assertFalse(bridge.thread.is_alive())
        self.assertTrue(all(not worker.is_alive() for worker in bridge.workers))
        self.assertFalse(bridge.connections)
        self.assertFalse(bridge.processes)

    def test_trickling_unauthenticated_request_has_an_absolute_deadline(self):
        bridge = self.bridge(request_timeout=1)
        connection = self.connect(bridge)
        self.assertTrue(bridge.wait_for('started', 1))
        stop, sent = self.trickle(connection)
        response = vscode.read_message(connection)
        stop.set()
        self.assertIn('error', response)
        self.assertGreaterEqual(len(sent), 3, 'Probe must send multiple partial reads')
        self.assertTrue(bridge.wait_for('finished', 1))
        self.assert_closed(connection)
        self.launch.assert_not_called()
        self.recover(bridge)

    def test_valid_request_finishes_while_unauthenticated_input_is_still_trickling(self):
        bridge = self.bridge(request_timeout=10, max_connections=2)
        slow = self.connect(bridge)
        self.assertTrue(bridge.wait_for('started', 1))
        stop, _ = self.trickle(slow)
        done, outcome, _ = self.background(lambda: self.valid(bridge))
        self.assertTrue(done.wait(5), 'Valid request was blocked behind unauthenticated input')
        self.assertEqual(outcome, [None])
        self.assertFalse(stop.is_set())
        # Receiving the response can precede the worker's completion notification.
        self.assertTrue(bridge.wait_for('finished', 1))
        with bridge.observed:
            self.assertEqual(bridge.finished, 1)
            self.assertEqual(bridge.active, 1)
        self.launch.assert_called_once()
        stop.set()

    def test_accept_loop_also_remains_available_during_an_editor_launch(self):
        bridge = self.bridge(max_connections=2)
        entered = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)

        def launch(folder, *_args, **_kwargs):
            if folder == '/busy':
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('Test editor was not released')

        self.launch.side_effect = launch
        busy_done, busy_result, _ = self.background(lambda: self.valid(bridge, '/busy'))
        self.assertTrue(entered.wait(5))
        done, outcome, _ = self.background(lambda: self.valid(bridge))
        self.assertTrue(done.wait(3))
        self.assertEqual(outcome, [None])
        self.assertFalse(busy_done.is_set())
        release.set()
        self.assertTrue(busy_done.wait(5))
        self.assertEqual(busy_result, [None])

    def test_capacity_rejects_excess_sockets_and_recovers(self):
        capacity = 3
        bridge = self.bridge(request_timeout=30, max_connections=capacity)
        occupied = [self.connect(bridge) for _ in range(capacity)]
        self.assertTrue(bridge.wait_for('started', capacity))
        for _ in range(capacity * 4):
            self.assert_rejected(bridge)
        with bridge.observed:
            self.assertEqual(bridge.started, capacity)
            self.assertEqual(bridge.peak, capacity)
        # Queued and running sockets share one admission limit.
        with bridge.lock:
            self.assertLessEqual(len(bridge.connections), capacity)
            self.assertLessEqual(bridge.pending.qsize(), capacity)
        self.assertEqual(len(bridge.workers), capacity)
        self.launch.assert_not_called()
        occupied[0].close()
        self.assertTrue(bridge.wait_for('finished', 1))
        self.recover(bridge)
        self.launch.assert_called_once()

    def test_shutdown_interrupts_idle_and_trickling_clients(self):
        bridge = self.bridge(request_timeout=30, max_connections=3)
        clients = [self.connect(bridge) for _ in range(3)]
        self.assertTrue(bridge.wait_for('started', 3))
        stop, _ = self.trickle(clients[0])
        address = bridge.listener.getsockname()
        self.stop_bridge(bridge)
        stop.set()
        self.assertEqual(bridge.finished, 3)
        for connection in clients:
            self.assert_closed(connection)
        with self.assertRaises(OSError):
            socket.create_connection(address, timeout=1)
        self.launch.assert_not_called()

    def test_queued_sockets_share_capacity_and_are_closed_on_shutdown(self):
        release = threading.Event()
        queued = threading.Event()

        class PausedBridge(ObservedBridge):
            def work(self):
                release.wait(5)
                super().work()

        bridge = self.enterContext(PausedBridge('fixed-host', transport='tcp',
                                              max_connections=2, request_timeout=30))
        self.addCleanup(release.set)
        real_put = bridge.pending.put_nowait
        submitted = []

        def put(item):
            real_put(item)
            submitted.append(item)
            if len(submitted) == 2:
                queued.set()

        with patch.object(bridge.pending, 'put_nowait', side_effect=put):
            clients = [self.connect(bridge) for _ in range(2)]
            for connection in clients:
                vscode.send_message(connection, {'folder': '/project', 'token': bridge.token})
            self.assertTrue(queued.wait(5))
            for _ in range(4):
                self.assert_rejected(bridge)
            self.assertEqual(bridge.pending.qsize(), 2)
            self.assertEqual(bridge.started, 0)
            done, outcome, _ = self.background(bridge.__exit__)
            self.assertTrue(bridge.stopped.wait(5))
            release.set()
            self.assertTrue(done.wait(3))
            self.assertEqual(outcome, [None])
        for connection in clients:
            self.assert_closed(connection)
        self.assertTrue(all(not worker.is_alive() for worker in bridge.workers))
        self.assertFalse(bridge.connections)
        self.assertTrue(bridge.pending.empty())
        self.launch.assert_not_called()

    def test_socket_accepted_during_shutdown_is_closed_before_registration(self):
        accepted = threading.Event()
        release = threading.Event()
        real_socket = socket.socket

        class Listener:
            def __init__(self, *args, **kwargs):
                self.socket = real_socket(*args, **kwargs)

            def __getattr__(self, name):
                return getattr(self.socket, name)

            def accept(self):
                result = self.socket.accept()
                accepted.set()
                if not release.wait(5):
                    result[0].close()
                    raise OSError('Test accept was not released')
                return result

        with patch.object(vscode.socket, 'socket', Listener):
            bridge = self.bridge()
        self.addCleanup(release.set)
        connection = self.connect(bridge)
        vscode.send_message(connection, {'folder': '/project', 'token': bridge.token})
        self.assertTrue(accepted.wait(5))
        done, outcome, _ = self.background(bridge.__exit__)
        self.assertTrue(bridge.stopped.wait(5))
        release.set()
        self.assertTrue(done.wait(3))
        self.assertEqual(outcome, [None])
        self.assert_closed(connection)
        self.assertEqual(bridge.started, 0)
        self.launch.assert_not_called()

    def test_shutdown_prevents_a_launch_still_preparing_its_command(self):
        self.launch_patch.stop()
        bridge = self.bridge()
        preparing = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)

        def command(_env):
            preparing.set()
            if not release.wait(5):
                raise RuntimeError('Test command was not released')
            return [sys.executable, '-c', 'pass']

        with patch.object(vscode, 'code_command', side_effect=command):
            with patch.object(vscode.subprocess, 'Popen') as popen:
                connection = self.connect(bridge)
                vscode.send_message(connection, {'folder': '/project', 'token': bridge.token})
                self.assertTrue(preparing.wait(5))
                done, outcome, _ = self.background(bridge.__exit__)
                self.assertTrue(bridge.stopped.wait(5))
                release.set()
                self.assertTrue(done.wait(3))
                self.assertEqual(outcome, [None])
                popen.assert_not_called()
        self.assert_closed(connection)

    def test_shutdown_kills_and_reaps_an_in_progress_editor_cli(self):
        self.launch_patch.stop()
        bridge = self.bridge()
        started = threading.Event()
        children = []
        real_popen = subprocess.Popen

        def start(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            started.set()
            return child

        with patch.object(vscode, 'code_command', return_value=[
                sys.executable, '-c', 'import time; time.sleep(60)']):
            with patch.object(vscode.subprocess, 'Popen', side_effect=start):
                connection = self.connect(bridge)
                vscode.send_message(connection, {'folder': '/project', 'token': bridge.token})
                self.assertTrue(started.wait(5))
                self.stop_bridge(bridge)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
        self.assert_closed(connection)

    def test_invalid_input_disconnects_and_launch_failures_release_capacity(self):
        bridge = self.bridge(max_connections=1)
        invalid = [b'not json\n', b'[]\n', b'{"folder":"/project"}\n',
                   json.dumps({'folder': '/project', 'token': 'wrong'}).encode() + b'\n',
                   json.dumps({'folder': '/project', 'token': '\ud800'}).encode() + b'\n',
                   b'x' * (vscode.MAX_REQUEST + 1), b'', b'{"folder":']
        for payload in invalid:
            with self.subTest(payload=payload[:40]):
                before = self.launch.call_count
                connection = self.connect(bridge)
                connection.sendall(payload)
                connection.shutdown(socket.SHUT_WR)
                self.assertIn('error', vscode.read_message(connection))
                self.assertEqual(self.launch.call_count, before)
                self.recover(bridge)
                connection.close()
        finished = bridge.finished
        connection = self.connect(bridge)
        connection.close()
        self.assertTrue(bridge.wait_for('finished', finished + 1))
        self.recover(bridge)
        for error in (RuntimeError('Editor failed'), OSError('Cannot start editor'),
                      subprocess.TimeoutExpired('fake editor', 15)):
            with self.subTest(error=error):
                self.launch.side_effect = error
                with self.assertRaises(RuntimeError):
                    self.valid(bridge)
                self.launch.side_effect = None
                self.recover(bridge)

    def test_request_limit_still_accepts_a_complete_16_kib_line(self):
        self.assertEqual(vscode.MAX_REQUEST, 16384)
        bridge = self.bridge()
        message = {'folder': '/project', 'token': bridge.token, 'padding': ''}
        size = len(json.dumps(message).encode()) + 1
        message['padding'] = 'x' * (vscode.MAX_REQUEST - size)
        connection = self.connect(bridge)
        vscode.send_message(connection, message)
        self.assertEqual(vscode.read_message(connection), {'ok': True, 'protocol_version': 1})
        self.launch.assert_called_once()

    def test_real_editor_cli_errors_and_timeouts_are_reaped_and_capacity_recovers(self):
        self.launch_patch.stop()
        bridge = self.bridge(max_connections=1)
        children = []
        real_popen = subprocess.Popen

        def start(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child

        programs = [
            ('import sys; sys.stderr.buffer.write("stub failed é".encode("utf-8")); sys.exit(2)',
             15, 'stub failed é'),
            ('import time; time.sleep(60)', 0.5, 'timed out')]
        with patch.object(vscode, 'code_command') as command:
            with patch.object(vscode.subprocess, 'Popen', side_effect=start):
                for program, budget, error in programs:
                    with self.subTest(error=error):
                        command.return_value = [sys.executable, '-c', program]
                        with patch.object(vscode, 'LAUNCH_TIMEOUT', budget):
                            with self.assertRaisesRegex(RuntimeError, error):
                                self.valid(bridge)
                        command.return_value = [sys.executable, '-c', 'pass']
                        self.recover(bridge)
        self.assertEqual(len(children), 4)
        self.assertTrue(all(child.poll() is not None for child in children))
        self.assertFalse(bridge.processes)

    def test_client_response_and_server_write_budgets_are_separate_from_reading(self):
        bridge = self.bridge(request_timeout=0.5)
        entered = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)
        read_budgets = []
        write_budgets = []
        real_read = vscode.read_message
        real_send = vscode.send_message

        def launch(*_args, **_kwargs):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('Test launch was not released')

        def read(connection, *, deadline=None):
            if deadline is not None:
                read_budgets.append(deadline - time.monotonic())
            return real_read(connection, deadline=deadline)

        def send(connection, message):
            if message.get('ok'):
                write_budgets.append(connection.gettimeout())
            real_send(connection, message)

        self.launch.side_effect = launch
        with patch.object(vscode, 'read_message', side_effect=read):
            with patch.object(vscode, 'send_message', side_effect=send):
                done, outcome, _ = self.background(lambda: self.valid(bridge))
                self.assertTrue(entered.wait(5))
                self.assertFalse(done.wait(0.75), 'Editor wait should outlive the reading budget')
                release.set()
                self.assertTrue(done.wait(5))
                self.assertEqual(outcome, [None])
        self.assertTrue(any(budget >= 15 for budget in read_budgets))
        self.assertEqual(write_budgets, [vscode.RESPONSE_TIMEOUT])

    def test_authentication_and_fixed_destination_are_preserved(self):
        bridge = self.bridge()
        connection = self.connect(bridge)
        folder = "/home/alice/project 'quoted' %PATH% & #?é"
        vscode.send_message(connection, {'folder': folder, 'token': bridge.token,
                                         'destination': 'attacker-host'})
        self.assertEqual(vscode.read_message(connection), {'ok': True, 'protocol_version': 1})
        self.assertEqual(self.launch.call_args.args[:2], (folder, 'fixed-host'))

    @unittest.skipIf(os.name == 'nt', 'Private Unix sockets are the Linux transport')
    def test_unix_shutdown_interrupts_readers_and_removes_private_directory(self):
        bridge = self.bridge(transport='unix', request_timeout=30)
        path = Path(bridge.local_socket)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        connection = self.connect(bridge)
        self.assertTrue(bridge.wait_for('started', 1))
        self.stop_bridge(bridge)
        self.assert_closed(connection)
        self.assertFalse(path.exists())
        self.assertFalse(path.parent.exists())
        self.launch.assert_not_called()

    @unittest.skipIf(os.name == 'nt', 'Private Unix sockets are the Linux transport')
    def test_unix_transport_recovers_from_invalid_requests(self):
        bridge = self.bridge(transport='unix', max_connections=1)
        connection = self.connect(bridge)
        # A rejected folder must not prevent the next Unix request from succeeding.
        self.launch.side_effect = ValueError('Invalid folder')
        vscode.send_message(connection, {'folder': 'relative', 'token': bridge.token})
        self.assertIn('error', vscode.read_message(connection))
        self.launch.side_effect = None
        self.recover(bridge)
        self.assertEqual(self.launch.call_args.args[:2], ('/project', 'fixed-host'))


if __name__ == '__main__':
    unittest.main()
