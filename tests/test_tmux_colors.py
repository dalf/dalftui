"""Verify tmux clients and pane programs receive colors the terminal can render."""
import os
import select
import shlex
import subprocess
import termios
import time
import unittest

import test_install as install_tests


@unittest.skipIf(os.name == 'nt', 'Attached clients require a POSIX terminal')
class TmuxColorTests(install_tests.TmuxFixture):
    profile = 'server'

    def attach(self, *, rgb=False):
        master, slave = os.openpty()
        termios.tcsetwinsize(slave, (24, 100))
        env = dict(self.env, TERM='xterm-256color', TERM_PROGRAM='Apple_Terminal')
        env.pop('COLORTERM', None)
        options = ['-T', 'RGB'] if rgb else []
        process = subprocess.Popen([*self.command, *options, 'attach-session', '-t', 'verify'],
                                   stdin=slave, stdout=slave, stderr=slave, env=env,
                                   start_new_session=True)
        os.close(slave)

        def cleanup():
            try:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=5)
            finally:
                os.close(master)

        self.addCleanup(cleanup)
        output = bytearray()
        until = time.monotonic() + 5
        while time.monotonic() < until:
            if select.select([master], [], [], 0.05)[0]:
                output.extend(os.read(master, 65536))
            clients = self.tmux('list-clients', '-F', '#{client_pid}').splitlines()
            if str(process.pid) in clients and output:
                return process, master, bytes(output) + self.redraw(master, process.pid)
        self.fail(f'The tmux client did not attach: {output!r}')

    def client_tty(self, pid):
        clients = dict(line.split(' ', 1) for line in
                       self.tmux('list-clients', '-F', '#{client_pid} #{client_tty}').splitlines())
        return clients[str(pid)]

    def redraw(self, master, pid):
        while select.select([master], [], [], 0)[0]:
            os.read(master, 65536)
        self.tmux('refresh-client', '-t', self.client_tty(pid))
        chunks = []
        until = time.monotonic() + 2
        while time.monotonic() < until:
            if select.select([master], [], [], 0.1)[0]:
                chunks.append(os.read(master, 65536))
            elif chunks:
                return b''.join(chunks)
        self.fail('The attached terminal was not redrawn')

    def assert_colors(self, output, *, rgb):
        escape = rb'\x1b\[[0-9;]*(?:38|48);'
        if rgb:
            self.assertRegex(output, escape + rb'2;')
        else:
            self.assertNotRegex(output, escape + rb'2;')
            self.assertRegex(output, escape + rb'5;')

    def test_same_terminal_name_keeps_each_clients_color_capabilities(self):
        self.start()
        self.do_reload()
        capable, capable_tty, output = self.attach(rgb=True)
        self.assert_colors(output, rgb=True)
        plain, plain_tty, output = self.attach()
        self.assert_colors(output, rgb=False)
        before = self.tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}')
        self.do_reload()
        self.do_reload()
        self.assert_colors(self.redraw(capable_tty, capable.pid), rgb=True)
        self.assert_colors(self.redraw(plain_tty, plain.pid), rgb=False)
        clients = dict(line.split(':', 1) for line in
                       self.tmux('list-clients', '-F', '#{client_pid}:#{client_termfeatures}').splitlines())
        self.assertIn('RGB', clients[str(capable.pid)].split(','))
        self.assertNotIn('RGB', clients[str(plain.pid)].split(','))
        self.assertEqual(self.tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}'), before)

    def test_reload_and_reconnect_clear_legacy_rgb_without_losing_sessions(self):
        self.start()
        self.do_reload()
        self.tmux('set-option', '-s', 'terminal-overrides[100]', '*:Tc')
        client, master, output = self.attach()
        self.assert_colors(output, rgb=True)
        before = self.tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}')
        self.do_reload()
        self.do_reload()
        # tmux retains the capabilities of an already attached client until it reconnects.
        self.assert_colors(self.redraw(master, client.pid), rgb=True)
        _, _, output = self.attach()
        self.assert_colors(output, rgb=False)
        self.tmux('detach-client', '-t', self.client_tty(client.pid))
        client.wait(timeout=5)
        _, _, output = self.attach()
        self.assert_colors(output, rgb=False)
        self.assertEqual(self.tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}'), before)


@unittest.skipIf(os.name == 'nt', 'tmux panes require a POSIX host')
class PaneColorTests(install_tests.TmuxFixture):
    """Programs in panes see 256 colors and truecolor, however the server started."""
    profile = 'server'

    def pane_env(self, name):
        path = self.directory / f'{name}.env'
        until = time.monotonic() + 5
        while not (path.exists() and path.read_text().endswith('done\n')) and time.monotonic() < until:
            time.sleep(0.05)
        return dict(line.split('=', 1) for line in path.read_text().splitlines() if '=' in line)

    def env_command(self, name):
        path = shlex.quote(str(self.directory / f'{name}.env'))
        return f'env > {path}; echo done >> {path}; sleep 600'

    def assert_pane_colors(self, env):
        self.assertIn(env.get('TERM'), ('tmux-256color', 'screen-256color'))
        self.assertEqual(env.get('COLORTERM'), 'truecolor')

    def test_ssh_started_server_gives_first_pane_color_hints(self):
        # SSH forwards TERM but not COLORTERM.
        env = dict(self.env, TERM='xterm-256color')
        env.pop('COLORTERM', None)
        subprocess.run(['tmux', '-S', str(self.socket), '-f', str(self.paths.tmux),
                        'new-session', '-d', '-s', 'verify', self.env_command('first')],
                       env=env, check=True, timeout=15)
        self.addCleanup(subprocess.run, [*self.command, 'kill-server'], capture_output=True, env=self.env)
        self.assert_pane_colors(self.pane_env('first'))

    def reload_old_default(self):
        self.env.pop('COLORTERM', None)
        self.start()
        # tmux before 3.3 has this built in; CI's newer tmux would otherwise skip the replacement.
        self.tmux('set-option', '-s', 'default-terminal', 'screen')
        before = self.tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}')
        self.do_reload()
        self.do_reload()
        self.tmux('new-window', '-d', self.env_command('new'))
        env = self.pane_env('new')
        self.assert_pane_colors(env)
        self.assertIn(before, self.tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}'))
        return env['TERM']

    def test_reload_gives_new_panes_color_hints_and_keeps_old_ones(self):
        known = subprocess.run(['infocmp', 'tmux-256color'], capture_output=True, check=False).returncode == 0
        self.assertEqual(self.reload_old_default(), 'tmux-256color' if known else 'screen-256color')

    def test_reload_falls_back_without_tmux_terminfo(self):
        tools = self.directory / 'no-terminfo'
        tools.mkdir()
        infocmp = tools / 'infocmp'
        infocmp.write_text('#!/bin/sh\nexit 1\n', encoding='utf-8')
        infocmp.chmod(0o755)
        self.env['PATH'] = f'{tools}{os.pathsep}{self.env["PATH"]}'
        self.assertEqual(self.reload_old_default(), 'screen-256color')

    def test_reload_keeps_a_chosen_terminal(self):
        self.start()
        self.tmux('set-option', '-s', 'default-terminal', 'xterm-256color')
        self.do_reload()
        self.assertEqual(self.tmux('show-options', '-sv', 'default-terminal'), 'xterm-256color')


if __name__ == '__main__':
    unittest.main()
