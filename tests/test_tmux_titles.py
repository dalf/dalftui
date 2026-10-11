"""Check outer terminal titles across tmux reloads and client reattachments."""
from contextlib import contextmanager
import os
import re
import select
import subprocess
import termios
import time
import unittest

import test_install as install_tests


@unittest.skipIf(os.name == 'nt', 'tmux clients require a POSIX terminal')
class TmuxTitleTests(install_tests.TmuxFixture):
    profile = 'server'

    @contextmanager
    def attached_client(self, session):
        master, slave = os.openpty()
        process = None
        try:
            termios.tcsetwinsize(slave, (24, 100))
            process = subprocess.Popen([*self.command, 'attach-session', '-t', session],
                                       stdin=slave, stdout=slave, stderr=slave,
                                       env=dict(self.env, TERM='xterm-256color'),
                                       start_new_session=True)
            os.close(slave)
            slave = None
            yield master
        finally:
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=5)
            if slave is not None:
                os.close(slave)
            os.close(master)

    def read_titles(self, master, expected):
        output = bytearray()
        until = time.monotonic() + 5
        while time.monotonic() < until:
            if select.select([master], [], [], 0.1)[0]:
                output.extend(os.read(master, 65536))
            titles = [value.decode('utf-8') for value in
                      re.findall(rb'\x1b\]0;([^\x07\x1b]*)\x07', output)]
            if expected in titles:
                self.assertEqual(set(titles), {expected})
                return
        self.fail(f'Expected terminal title {expected!r}; received {bytes(output[-1000:])!r}')

    def test_ssh_shell_title_survives_reload_window_changes_and_reattachment(self):
        self.start()
        # An older server may already have enabled tmux's session:window title.
        self.tmux('set-option', '-g', 'set-titles', 'on')
        self.tmux('set-option', '-g', 'set-titles-string', '#S:#I:#W')
        label = 'alexandre@aflament#{host},%H'
        self.tmux('set-option', '-t', 'verify', '@dalftui_host', label)
        self.do_reload()
        for _ in range(2):
            with self.attached_client('verify') as master:
                self.read_titles(master, label)
                self.tmux('new-window', '-n', 'bash', 'sleep 600')
                self.tmux('select-pane', '-T', 'repository@feature')
                self.do_reload()
                self.assertEqual(self.tmux('display-message', '-p', '-t', 'verify',
                                           '#{T:set-titles-string}'), label)

    def test_without_an_ssh_label_the_title_follows_the_local_pane(self):
        self.start()
        title = 'repository@feature/local'
        self.tmux('select-pane', '-T', title)
        self.do_reload()
        with self.attached_client('verify') as master:
            self.read_titles(master, title)

    def test_reload_preserves_claude_status_titles_and_per_session_host_labels(self):
        self.start()
        self.do_reload()
        self.tmux('new-session', '-d', '-s', 'other', 'sleep 600')
        # Model claude-tabstatus's ownership and title indirection. Its status
        # renderer is independent of dalftui's choice of the host label.
        plugin_format = '#{s|^ ||:#{T:@cctab_title}}'
        self.tmux('set-option', '-s', '@cctab_string', plugin_format)
        self.tmux('set-option', '-s', '@cctab_title', '🔵 #{E:@cctab_label}')
        self.tmux('set-option', '-g', 'set-titles', 'on')
        self.tmux('set-option', '-g', 'set-titles-string', plugin_format)
        for session, label in (('verify', 'alice@prod'), ('other', 'bob@staging')):
            self.tmux('set-option', '-t', session, '@dalftui_host', label)
        self.do_reload()
        self.do_reload()
        self.assertEqual(self.tmux('show-options', '-gv', 'set-titles-string'), plugin_format)
        for session, label in (('verify', 'alice@prod'), ('other', 'bob@staging')):
            with self.attached_client(session) as master:
                self.read_titles(master, f'🔵 {label}')

    def test_personal_title_override_takes_precedence(self):
        self.start()
        local = self.paths.config_dir / 'tmux/local.conf'
        local.write_text("set -g set-titles-string 'My custom title'\n")
        self.do_reload()
        with self.attached_client('verify') as master:
            self.read_titles(master, 'My custom title')
