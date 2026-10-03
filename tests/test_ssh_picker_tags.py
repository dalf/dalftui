"""Exercise tag filtering with OpenSSH's real configuration evaluator; no logins."""
from contextlib import ExitStack
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('ssh_picker', Path(__file__).resolve().parents[1] / 'ssh-picker.py')
picker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(picker)


class Screen:
    def __init__(self, keys):
        self.keys = iter(keys)
        self.messages = []

    def getmaxyx(self):
        return 24, 100

    def erase(self):
        pass

    def addnstr(self, y, x, text, count, style):
        self.messages.append(text)

    def move(self, y, x):
        pass

    def refresh(self):
        pass

    def get_wch(self):
        return next(self.keys)


@unittest.skipUnless(shutil.which('ssh'), 'OpenSSH is required')
class TagTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='dalftui-tag-tests-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = self.root / 'config'
        self.config.write_text('')
        source = patch.object(picker, 'SSH_CONFIG', self.config)
        source.start()
        self.addCleanup(source.stop)

    def input(self, text, hosts):
        screen = Screen([*text, '\n', '\x1b'])
        with ExitStack() as stack:
            for name in ['use_default_colors', 'init_pair', 'set_escdelay', 'color_pair']:
                stack.enter_context(patch.object(picker.curses, name, return_value=0))
            stack.enter_context(patch.object(picker.curses, 'COLORS', 256, create=True))
            result = picker.pick(screen, hosts)
        return result, screen.messages

    def test_git_services_are_absent_and_server_login_is_preserved(self):
        self.config.write_text('Host server\n Tag dalftui\n User alice\n'
                               'Host github.com gitlab.com gitedu.hesge.ch\n User git\n')
        self.assertEqual(picker.target_hosts(), ['server'])
        self.assertEqual(picker.configured_login('server'), 'alice')

    def test_included_hosts_and_shared_aliases(self):
        include = self.root / 'hosts included.conf'
        include.write_text('Host server alias\n Tag dalftui\nHost service\n Tag git\n')
        self.config.write_text(f'Include "{include}"\n')
        self.assertEqual(picker.target_hosts(), ['server', 'alias'])

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

    def test_tag_changes_are_read_on_each_open(self):
        self.config.write_text('Host server\n Tag dalftui\n')
        self.assertEqual(picker.target_hosts(), ['server'])
        self.config.write_text('Host server\n')
        self.assertEqual(picker.target_hosts(), [])


if __name__ == '__main__':
    unittest.main()
