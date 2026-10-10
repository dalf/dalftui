"""Exercise tag filtering with OpenSSH's real configuration evaluator; no logins."""
from contextlib import ExitStack, redirect_stderr
import io
import os
from pathlib import Path
import shutil
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dalftui import ssh as picker
from dalftui.linux import ssh_picker


class Screen:
    def __init__(self, keys):
        self.keys = iter(keys)
        self.messages = []

    def getmaxyx(self):
        return 24, 100

    def erase(self):
        pass

    def addnstr(self, _y, _x, text, _count, _style):
        self.messages.append(text)

    def move(self, _y, _x):
        pass

    def refresh(self):
        pass

    def get_wch(self):
        return next(self.keys)


def supports_ssh_tag():
    if not shutil.which('ssh'):
        return False
    result = subprocess.run(['ssh', '-G', '-F', os.devnull, '-o', 'Tag=dalftui', '--', 'localhost'],
                            capture_output=True, text=True, timeout=10)
    return result.returncode == 0


class TagConfig(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='dalftui-tag-tests-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = self.root / 'config'
        self.config.write_text('')
        source = patch.object(picker, 'SSH_CONFIG', self.config)
        source.start()
        self.addCleanup(source.stop)
        self.enterContext(patch.object(picker, 'host_cache_path', return_value=self.root / 'hosts-cache.json'))


@unittest.skipUnless(supports_ssh_tag(), 'OpenSSH 9.4+ is required for SSH tags')
class TagTests(TagConfig):
    def test_git_services_are_absent_and_server_login_is_preserved(self):
        self.config.write_text('Host server\n Tag dalftui\n User alice\n'
                               'Host github.com gitlab.com gitedu.hesge.ch\n User git\n')
        self.assertEqual(picker.target_hosts(), ['server'])
        self.assertEqual(picker.configured_login('server'), 'alice')

    def test_included_hosts_and_shared_aliases(self):
        include = self.root / 'hosts included.conf'
        include.write_text('Host server alias\n Tag dalftui\nHost service\n Tag git\n')
        self.config.write_text(f'Include "{include}"\n')
        self.assertEqual(picker.target_hosts(), ['alias', 'server'])

    def test_wildcard_tag_and_negated_host_pattern(self):
        self.config.write_text('Host server.lab excluded.lab github.com\n'
                               'Host *.lab !excluded.lab\n Tag dalftui\n')
        self.assertEqual(picker.target_hosts(), ['server.lab'])
        self.assertEqual(picker.configured_tag('another.lab'), 'dalftui')
        self.assertNotEqual(picker.configured_tag('excluded.lab'), 'dalftui')

    def test_first_tag_wins(self):
        self.config.write_text('Host service\n Tag git\nHost *\n Tag dalftui\nHost service server\n')
        self.assertEqual(picker.target_hosts(), ['server'])

    def test_match_and_username_destination_use_openssh_rules(self):
        self.config.write_text('Host server\n Tag dalftui\n'
                               'Match tagged dalftui\n User alice\n'
                               'Host service\n Tag git\n')
        self.assertEqual(picker.target_hosts(), ['server'])
        self.assertEqual(picker.configured_tag('chosen@server'), 'dalftui')
        self.assertEqual(picker.configured_login('server'), 'alice')

    def test_tag_changes_are_read_on_each_open(self):
        self.config.write_text('Host server\n Tag dalftui\n')
        self.assertEqual(picker.target_hosts(), ['server'])
        self.config.write_text('Host server\n')
        self.assertEqual(picker.target_hosts(), [])


@unittest.skipUnless(supports_ssh_tag() and ssh_picker.curses is not None,
                     'OpenSSH 9.4+ and curses are required for desktop tag tests')
class PickerTagTests(TagConfig):
    def input(self, text, hosts):
        screen = Screen([*text, '\n', '\x1b'])
        with ExitStack() as stack:
            for name in ['use_default_colors', 'init_pair', 'set_escdelay', 'color_pair']:
                stack.enter_context(patch.object(ssh_picker.curses, name, return_value=0))
            stack.enter_context(patch.object(ssh_picker.curses, 'COLORS', 256, create=True))
            result = ssh_picker.pick(screen, hosts)
        return result, screen.messages

    def test_typing_an_untagged_service_does_not_bypass_filter(self):
        self.config.write_text('Host server\n Tag dalftui\nHost github.com\n User git\n')
        selected, messages = self.input('github.com', picker.target_hosts())
        self.assertIsNone(selected)
        self.assertTrue(any('github.com is not enabled' in value for value in messages))

    def test_typing_a_host_under_a_tagged_wildcard_is_allowed(self):
        self.config.write_text('Host *.lab\n Tag dalftui\n')
        self.assertEqual(picker.target_hosts(), [])
        selected, _ = self.input('another.lab', [])
        self.assertEqual(selected, 'another.lab')


@unittest.skipUnless(ssh_picker.curses is not None, 'curses is required for desktop UI tests')
class DesktopPickerTests(unittest.TestCase):
    def choose(self, keys, hosts):
        screen = Screen(keys)
        with ExitStack() as stack:
            for name in ('use_default_colors', 'init_pair', 'set_escdelay', 'color_pair'):
                stack.enter_context(patch.object(ssh_picker.curses, name, return_value=0))
            stack.enter_context(patch.object(ssh_picker.curses, 'COLORS', 256, create=True))
            selected = ssh_picker.pick(screen, hosts)
        return selected, screen.messages

    def test_ctrl_o_connects_literal_input_and_is_visible_in_linux_picker(self):
        for query, hosts in (('prod', ['sibils-prod-ai']), ('alice@new-server', [])):
            with (self.subTest(query=query),
                  patch.object(picker, 'configured_tag') as evaluate):
                selected, messages = self.choose([*query, '\x0f'], hosts)
                self.assertEqual(selected, query)
                self.assertIn('Ctrl+O connect typed hostname, IP or user@host', messages)
                evaluate.assert_not_called()

    def test_function_keys_dispatch_directly_and_return_from_details_and_checks(self):
        from dalftui.host_picker import HostAction
        keys = ssh_picker.curses
        for number, mode in ((5, 'plain'), (6, 'ops')):
            with self.subTest(key=number):
                selected, messages = self.choose([keys.KEY_F0 + number], ['prod'])
                self.assertEqual(selected, HostAction('prod', mode))
                self.assertTrue(any('F4 Details' in message and 'F7 Checks' in message for message in messages))
        with patch.object(picker, 'connection_details', return_value=['Hostname: prod.example.org']) as details:
            selected, messages = self.choose([keys.KEY_F0 + 4, '\x1b', '\n'], ['prod'])
            self.assertEqual(selected, 'prod')
            details.assert_called_once_with('prod')
            self.assertTrue(any('Hostname: prod.example.org' in message for message in messages))
        with patch.object(picker, 'saved_checks', return_value=[picker.SavedCheck('health', 'true')]):
            selected, _ = self.choose([keys.KEY_F0 + 7, '\n'], ['prod'])
            self.assertEqual(selected, HostAction('prod', 'check', 'health'))
            selected, _ = self.choose([keys.KEY_F0 + 7, '\x1b', '\n'], ['prod'])
            self.assertEqual(selected, 'prod')

    def test_empty_ctrl_o_input_shows_error_and_allows_correction(self):
        selected, messages = self.choose(['\x0f', *'new-server', '\x0f'], [])
        self.assertEqual(selected, 'new-server')
        self.assertIn('Enter a valid SSH hostname, IP address or user@host.', messages)

    def test_filter_navigation_and_query_editing(self):
        keys = ssh_picker.curses
        cases = (
            ([*'AL', '\n'], ['beta', 'Alpha'], 'Alpha'),
            ([keys.KEY_DOWN, '\n'], ['alpha', 'beta'], 'beta'),
            ([keys.KEY_DOWN, keys.KEY_UP, '\n'], ['alpha', 'beta'], 'alpha'),
            ([keys.KEY_NPAGE, keys.KEY_PPAGE, '\n'], ['alpha', 'beta'], 'alpha'),
            ([*'wrong', '\x15', *'betx', keys.KEY_BACKSPACE, '\n'], ['alpha', 'beta'], 'beta'),
        )
        for typed, hosts, expected in cases:
            with self.subTest(keys=typed):
                self.assertEqual(self.choose(typed, hosts)[0], expected)

    def test_typed_host_checks_use_shared_validation_and_effective_tags(self):
        for tag, expected in (('dalftui', 'another.lab'), ('', None)):
            with self.subTest(tag=tag):
                with patch.object(picker, 'configured_tag', return_value=tag) as evaluate:
                    selected, messages = self.choose([*'another.lab', '\n', '\x1b'], [])
                self.assertEqual(selected, expected)
                evaluate.assert_called_once_with('another.lab')
                if not tag:
                    self.assertTrue(any('another.lab is not enabled' in text for text in messages))
        with patch.object(picker, 'configured_tag') as evaluate:
            self.assertIsNone(self.choose([*'-option', '\n', '\x1b'], [])[0])
        evaluate.assert_not_called()

    def test_typed_host_evaluation_error_is_shown_and_allows_cancellation(self):
        with patch.object(picker, 'configured_tag', side_effect=RuntimeError('tag probe failed')):
            selected, messages = self.choose([*'host', '\n', '\x1b'], [])
        self.assertIsNone(selected)
        self.assertIn('tag probe failed', messages)

    def test_desktop_default_dispatch_and_cancellation(self):
        for key in ('\x1b', '\x03', '\n'):
            with self.subTest(key=key):
                def wrapper(callback, hosts, key=key):
                    self.assertIs(callback, ssh_picker.pick)
                    return self.choose([key], hosts)[0]

                with (patch.object(sys, 'platform', 'linux'),
                      patch.object(sys, 'argv', ['bin/ssh_picker.py']),
                      patch.object(picker, 'target_hosts', return_value=['server']) as hosts,
                      patch.object(ssh_picker.curses, 'wrapper', side_effect=wrapper),
                      patch.object(ssh_picker, 'open_window') as window):
                    self.assertEqual(picker.main(), 0)
                hosts.assert_called_once_with()
                if key == '\n':
                    window.assert_called_once_with('server', '', None)
                else:
                    window.assert_not_called()

    def test_desktop_errors_keep_the_return_prompt_and_status(self):
        for error in (OSError('window failed'), RuntimeError('window failed'),
                      ssh_picker.curses.error('window failed')):
            with self.subTest(error=error):
                output = io.StringIO()
                with (patch.object(sys, 'platform', 'linux'),
                      patch.object(sys, 'argv', ['bin/ssh_picker.py']),
                      patch.object(picker, 'target_hosts', return_value=['server']),
                      patch.object(ssh_picker.curses, 'wrapper', side_effect=error),
                      patch('builtins.input', side_effect=EOFError) as prompt,
                      redirect_stderr(output)):
                    self.assertEqual(picker.main(), 1)
                prompt.assert_called_once_with('Press Enter to return.')
                self.assertIn('Could not open SSH window: window failed', output.getvalue())


class DesktopWindowTests(unittest.TestCase):
    def test_default_desktop_without_curses_keeps_the_cli_error(self):
        output = io.StringIO()
        with (patch.object(sys, 'platform', 'linux'),
              patch.object(sys, 'argv', ['bin/ssh_picker.py']),
              patch.object(ssh_picker, 'curses', None),
              patch.object(picker, 'target_hosts') as hosts,
              redirect_stderr(output)):
            with self.assertRaises(SystemExit) as failure:
                picker.main()
        self.assertEqual(failure.exception.code, 2)
        hosts.assert_not_called()
        self.assertIn('The SSH picker requires Python curses support. Use --connect HOST to connect directly.',
                      output.getvalue())


if __name__ == '__main__':
    unittest.main()
