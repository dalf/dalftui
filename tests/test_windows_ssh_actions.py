"""Shared host actions and Windows/Linux dispatch without opening connections."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_windows_host_picker import Screen
from dalftui import host_picker, ssh
from dalftui.linux import ssh_picker
from dalftui.windows.host_picker import ConsoleScreen


class ActionsMenuTests(unittest.TestCase):
    def choose(self, keys, *, details=None, checks=None, size=(100, 24)):
        screen = Screen(keys, size)
        result = host_picker.pick(screen, ['dev', 'prod'], ssh.validate_picker_host,
                                  details=details or Mock(return_value=['Hostname: example.org']),
                                  checks=checks or Mock(return_value=[ssh.SavedCheck('health', 'true')]))
        return result, screen

    def test_actions_help_stays_visible_beside_typed_connection_help(self):
        _, screen = self.choose(['cancel'], size=(32, 12))
        text = '\n'.join(cell[2] for cell in screen.frames[0])
        self.assertIn('F4 actions', text)
        self.assertIn('Ctrl+O connect typed', text)

    def test_details_and_back_preserve_the_filtered_host(self):
        details = Mock(return_value=['Hostname: prod.example.org'])
        result, screen = self.choose([*'prod', 'actions', 'down', 'enter', 'enter', 'cancel', 'enter'],
                                     details=details)
        self.assertEqual(result, 'prod')
        details.assert_called_once_with('prod')
        self.assertTrue(any('Hostname: prod.example.org' in text
                            for frame in screen.frames for _, _, text, _ in frame))

    def test_plain_and_ops_actions_use_the_selected_host(self):
        for steps, mode in ((2, 'plain'), (4, 'ops')):
            with self.subTest(mode=mode):
                result, _ = self.choose(['down', 'actions', *(['down'] * steps), 'enter'])
                self.assertEqual(result, host_picker.HostAction('prod', mode))

    def test_saved_checks_are_loaded_on_demand_and_selection_does_not_execute(self):
        details, checks = Mock(), Mock(return_value=[ssh.SavedCheck('health', 'exit 0', 12)])
        with patch.object(ssh.subprocess, 'run') as run:
            result, _ = self.choose(['actions', 'down', 'down', 'down', 'enter', 'enter'],
                                    details=details, checks=checks)
        self.assertEqual(result, host_picker.HostAction('dev', 'check', 'health'))
        checks.assert_called_once_with('dev')
        details.assert_not_called()
        run.assert_not_called()

    def test_normal_selection_never_loads_actions(self):
        details, checks = Mock(), Mock()
        self.assertEqual(self.choose(['enter'], details=details, checks=checks)[0], 'dev')
        details.assert_not_called()
        checks.assert_not_called()

    def test_action_errors_are_readable_and_return_to_host_grid(self):
        result, screen = self.choose(['actions', 'down', 'enter', 'enter', 'cancel', 'enter'],
                                     details=Mock(side_effect=RuntimeError('SSH details timed out')))
        self.assertEqual(result, 'dev')
        self.assertTrue(any('SSH details timed out' in cell[2]
                            for frame in screen.frames for cell in frame))

    def test_actions_accept_a_valid_typed_destination_without_tag_lookup(self):
        with patch.object(ssh, 'configured_tag') as tag:
            result, _ = self.choose([*'alice@new', 'actions', 'down', 'down', 'enter'])
        self.assertEqual(result, host_picker.HostAction('alice@new', 'plain'))
        tag.assert_not_called()

    def test_text_dialog_wraps_long_paths_and_can_scroll_and_resize(self):
        screen = Screen(['page_down', (30, 12), 'end', 'enter'], (20, 7))
        host_picker.dialog(screen, 'Details', ['Identity: /' + 'long path/' * 30, 'last line'])
        self.assertTrue(any('last line' in cell[2] for cell in screen.frames[-1]))
        for frame, width in zip(screen.frames, (20, 20, 30, 30)):
            for _, x, text, _ in frame:
                self.assertLess(x + host_picker.cell_width(text), width)

    def test_windows_f4_is_decoded(self):
        keyboard = Mock()
        keyboard.getwch.side_effect = ['\0', '>']
        with patch.dict(sys.modules, {'msvcrt': keyboard}):
            self.assertEqual(ConsoleScreen.read_key(), 'actions')


class SavedCheckTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.config = Path(temporary.name) / 'checks.json'
        patched = patch.object(ssh, 'CHECKS_CONFIG', self.config)
        patched.start()
        self.addCleanup(patched.stop)

    def test_missing_configuration_provides_read_only_defaults(self):
        checks = ssh.saved_checks('prod')
        self.assertEqual([item.name for item in checks], ['packages', 'system'])
        self.assertIn('apt-get --simulate', checks[0].command)
        self.assertIn('Cached metadata only', checks[0].command)

    def test_host_patterns_defaults_and_literal_shell_commands(self):
        command = 'printf "%s\\n" "a quoted $value"; systemctl is-active nginx'
        self.config.write_text(json.dumps({'checks': [
            {'name': 'service', 'hosts': ['prod-*', 'stage'], 'command': command, 'timeout': 7},
            {'name': 'everywhere', 'command': 'uptime'}]}), encoding='utf-8-sig')
        self.assertEqual(ssh.saved_checks('prod-api')[2:],
                         [ssh.SavedCheck('service', command, 7), ssh.SavedCheck('everywhere', 'uptime')])
        self.assertEqual([item.name for item in ssh.saved_checks('dev')],
                         ['packages', 'system', 'everywhere'])

    def test_invalid_configuration_does_not_silently_run_something_else(self):
        invalid = [[], {}, {'checks': {}}, {'checks': [{'name': 'packages', 'command': 'true'}]}]
        base = {'name': 'health', 'command': 'true'}
        invalid += [{'checks': [dict(base, **fields)]} for fields in
                    ({'timeout': True}, {'timeout': 0}, {'timeout': 3601}, {'timeout': '30'},
                     {'hosts': '*'}, {'hosts': []}, {'command': 'bad\0command'},
                     {'name': '\x1b[31m'}, {'timeuot': 30})]
        for data in invalid:
            with self.subTest(data=data):
                self.config.write_text(json.dumps(data), encoding='utf-8')
                with self.assertRaises(ValueError):
                    ssh.saved_checks('prod')
        self.config.write_text('{broken', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'Could not read'):
            ssh.saved_checks('prod')


class ActionDispatchTests(unittest.TestCase):
    def test_connection_details_use_effective_openssh_values_with_a_deadline(self):
        response = subprocess.CompletedProcess([], 0,
            'hostname real.example.org\nuser alice\nport 2222\nproxyjump gateway\n'
            'identityfile ~/.ssh/id_one\nidentityfile ~/.ssh/id_two\nignored secret\n', '')
        with patch.object(ssh.subprocess, 'run', return_value=response) as run:
            details = ssh.connection_details('alias')
        for value in ('Hostname: real.example.org', 'User: alice', 'Port: 2222',
                      'Jump host: gateway', 'Identity file: ~/.ssh/id_two'):
            self.assertIn(value, details)
        self.assertNotIn('secret', '\n'.join(details))
        self.assertEqual(run.call_args.args[0][-3:], ['-G', '--', 'alias'])
        self.assertEqual(run.call_args.kwargs['timeout'], 5)

    def test_connection_details_report_timeouts_and_configuration_errors(self):
        with patch.object(ssh.subprocess, 'run', side_effect=subprocess.TimeoutExpired('ssh', 5)):
            with self.assertRaisesRegex(RuntimeError, 'Could not read SSH details'):
                ssh.connection_details('alias')
        with patch.object(ssh.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'bad config')):
            with self.assertRaisesRegex(RuntimeError, 'bad config'):
                ssh.connection_details('alias')

    def test_cli_routes_each_action_and_requires_an_explicit_destination(self):
        for option, mode, check in ((['--plain'], 'plain', None), (['--ops'], 'ops', None),
                                    (['--check', 'health'], 'check', 'health')):
            with (self.subTest(mode=mode), patch.object(sys, 'argv', ['ssh_picker.py', '--connect', 'prod', *option]),
                  patch.object(ssh, 'connect', return_value=0) as connect):
                self.assertEqual(ssh.main(), 0)
                connect.assert_called_once_with('prod', None, mode=mode, check=check)
            with (patch.object(sys, 'argv', ['ssh_picker.py', *option]), redirect_stderr(io.StringIO())):
                with self.assertRaises(SystemExit):
                    ssh.main()

    def test_linux_window_forwards_action_arguments_without_a_shell(self):
        for selection, options in ((host_picker.HostAction('prod', 'ops'), ['--ops']),
                                   (host_picker.HostAction('prod', 'plain'), ['--plain']),
                                   (host_picker.HostAction('prod', 'check', 'a check'), ['--check', 'a check'])):
            with (self.subTest(selection=selection), patch.object(ssh_picker.shutil, 'which', return_value='/bin/alacritty'),
                  patch.object(ssh_picker.subprocess, 'Popen') as launch):
                launch.return_value.wait.side_effect = subprocess.TimeoutExpired('alacritty', 0.4)
                ssh_picker.open_window(selection)
                self.assertEqual(launch.call_args.args[0][-len(options) - 2:], ['--connect', 'prod', *options])
                self.assertNotIn('shell', launch.call_args.kwargs)

    def test_unknown_saved_check_fails_before_credentials_or_ssh(self):
        with (patch.object(ssh, 'saved_checks', return_value=[]),
              patch.object(ssh, 'configured_login') as login, patch.object(ssh, 'EditorBridge') as bridge,
              patch('builtins.input', return_value=''), redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO())):
            self.assertEqual(ssh.connect('prod', mode='check', check='missing'), 1)
            login.assert_not_called()
            bridge.assert_not_called()


if __name__ == '__main__':
    unittest.main()
