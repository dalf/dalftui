"""Shared fzf selection tests, also included in native Windows discovery."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dalftui import ssh


class FzfInputTests(unittest.TestCase):
    def choose(self, output, *, code=0, hosts=('sibils-prod-ai',)):
        with (patch.object(ssh.shutil, 'which', return_value='fzf'),
              patch.object(ssh.subprocess, 'run',
                           return_value=subprocess.CompletedProcess(['fzf'], code, output))):
            return ssh.pick_fzf(hosts)

    def test_enter_selects_the_highlighted_host_instead_of_the_query(self):
        for query in ('', 'prod', '^sibils !dev'):
            with self.subTest(query=query):
                self.assertEqual(self.choose(query + '\nsibils-prod-ai\n'), 'sibils-prod-ai')

    def test_ctrl_o_uses_literal_query_even_when_a_listed_host_matches(self):
        self.assertEqual(self.choose('prod\n'), 'prod')

    def test_ctrl_o_accepts_unlisted_destinations_without_tag_or_cache_writes(self):
        with (patch.object(ssh, 'configured_tag') as tag,
              patch.object(ssh, 'write_host_cache') as cache):
            for destination in ('new-server.example.org', '192.0.2.10', '2001:db8::1',
                                'alexandre@new-server', 'prod-é'):
                with self.subTest(destination=destination):
                    self.assertEqual(self.choose(destination + '\r\n'), destination)
        tag.assert_not_called()
        cache.assert_not_called()

    def test_ctrl_o_rejects_empty_whitespace_options_and_control_characters(self):
        for destination in ('', ' ', '-oProxyCommand=bad', 'two hosts', ' host',
                            'host ', 'host\tname', 'host\0name', 'host\x1bname',
                            'host\nother'):
            with self.subTest(destination=destination):
                with self.assertRaises(RuntimeError):
                    self.choose(destination + '\n')

    def test_cancellation_and_enter_without_matches_never_use_the_query(self):
        for code in (1, 130):
            for output in ('', 'new-server\n'):
                with self.subTest(code=code, output=output):
                    self.assertIsNone(self.choose(output, code=code))

    def test_unknown_selection_and_malformed_output_are_rejected(self):
        for output in ('', '\nunlisted\n', 'prod\nsibils-prod-ai\nextra\n'):
            with self.subTest(output=output):
                with self.assertRaises(RuntimeError):
                    self.choose(output)

    def test_empty_list_remains_open_for_input_and_help_shows_ctrl_o(self):
        with (patch.object(ssh.shutil, 'which', return_value='fzf'),
              patch.object(ssh, 'target_hosts', return_value=[]),
              patch.object(ssh.subprocess, 'run',
                           return_value=subprocess.CompletedProcess(['fzf'], 0, 'new-server\n')) as run):
            self.assertEqual(ssh.pick_fzf(), 'new-server')
        command = run.call_args.args[0]
        self.assertEqual(run.call_args.kwargs['input'], '')
        self.assertIn('--print-query', command)
        self.assertIn('--bind=ctrl-o:print-query', command)
        header = next(arg for arg in command if arg.startswith('--header='))
        self.assertIn('Ctrl+O connect typed hostname, IP or user@host', header.splitlines())
        self.assertIn('Enter connect', header)
        self.assertIn('Esc cancel', header)

    def test_cli_connects_typed_destination_on_windows_and_linux(self):
        for platform in ('win32', 'linux'):
            with (self.subTest(platform=platform),
                  patch.object(sys, 'platform', platform),
                  patch.object(sys, 'argv', ['ssh_picker.py', '--fzf']),
                  patch.object(ssh.shutil, 'which', return_value='fzf'),
                  patch.object(ssh, 'target_hosts', return_value=[]),
                  patch.object(ssh.subprocess, 'run',
                               return_value=subprocess.CompletedProcess(['fzf'], 0, 'alice@new-server\n')),
                  patch.object(ssh, 'connect', return_value=17) as connect):
                self.assertEqual(ssh.main(), 17)
                connect.assert_called_once_with('alice@new-server', None)

    @unittest.skipUnless(os.name == 'nt' and shutil.which('fzf'),
                         'Native Windows fzf requires a private console')
    def test_native_fzf_ctrl_o_action_with_matches_no_matches_and_empty_list(self):
        # Give real fzf an invisible console, then invoke its configured Ctrl+O
        # action at startup. This checks output framing without opening SSH or
        # injecting keystrokes into the user's terminal.
        program = r'''
import json, subprocess, sys
from unittest.mock import patch
from dalftui import ssh
real_run = subprocess.run
query, hosts_json = sys.argv[1:]
def automatic(command, **kwargs):
    binding = next(arg for arg in command if arg.startswith('--bind=ctrl-o:'))
    action = binding.split(':', 1)[1]
    return real_run([*command, '--sync', '--query=' + query, '--bind=start:' + action],
                    **kwargs, timeout=5)
with patch.object(ssh.subprocess, 'run', side_effect=automatic):
    destination = ssh.pick_fzf(json.loads(hosts_json))
print(json.dumps(destination))
'''
        for query, hosts in (('prod', ['sibils-prod-ai']),
                             ('192.0.2.10', ['sibils-prod-ai']),
                             ('alice@prod-é', [])):
            with self.subTest(query=query, hosts=hosts):
                result = subprocess.run(
                    [sys.executable, '-B', '-c', program, query, json.dumps(hosts)],
                    cwd=ROOT, capture_output=True, encoding='utf-8', timeout=10,
                    creationflags=0x08000000)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), query)


if __name__ == '__main__':
    unittest.main()
