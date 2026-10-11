"""Verify selection upgrades in an existing, isolated tmux server."""
import shlex

import test_install as install_tests


class TmuxSelectionTests(install_tests.TmuxFixture):
    profile = 'server'

    def test_reload_restores_mouse_selection_and_allows_clipboard_writes(self):
        self.start()
        before = self.tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}')
        # Simulate the previous release's bindings in an already running server.
        self.tmux('bind-key', '-n', 'MouseDrag1Pane', 'display-message', 'Hold Shift')
        for key in ('DoubleClick1Pane', 'TripleClick1Pane'):
            self.tmux('bind-key', '-n', key, 'select-pane', '-t', '=')
        self.do_reload()
        self.do_reload()
        self.assertEqual(self.tmux('list-panes', '-a', '-F', '#{pane_id}:#{pane_pid}'), before)
        self.assertEqual(self.tmux('show-options', '-gv', 'mouse'), 'on')
        self.assertEqual(self.tmux('show-options', '-sv', 'set-clipboard'), 'on')
        self.assertIn('#e5e7eb', self.tmux('show-options', '-gv', 'mode-style'))
        root = {shlex.split(line)[3]: line
                for line in self.tmux('list-keys', '-T', 'root').splitlines()}
        self.assertIn('send-keys -M', root['MouseDrag1Pane'])
        self.assertNotIn('Hold Shift', root['MouseDrag1Pane'])
        self.assertIn('copy-mode -M', root['MouseDrag1Pane'])
        for key, action in (('DoubleClick1Pane', 'select-word'), ('TripleClick1Pane', 'select-line')):
            self.assertIn('send-keys -M', root[key])
            self.assertIn(action, root[key])
            self.assertIn('copy-pipe-and-cancel', root[key])
