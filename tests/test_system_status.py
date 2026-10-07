"""Exercise the remote snapshot with deterministic tools, files, and failures."""
import errno
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
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dalftui.linux import ops


@unittest.skipIf(sys.platform == 'win32', 'System reports execute on Linux servers')
class SystemStatusTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='dalftui-status-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.bin = self.directory / 'bin'
        self.bin.mkdir()
        self.responses_file = self.directory / 'responses.json'
        self.log = self.directory / 'commands.jsonl'
        self.responses = {
            'hostname': {'stdout': 'server-example\n'},
            'date': {'stdout': '2026-10-05 12:00:00 UTC\n'},
            'uptime': {'stdout': '12:00 up 7 days, load average: 0.10, 0.20, 0.30\n'},
            'nproc': {'stdout': '8\n'},
            'systemctl': {
                'is-system-running': {'stdout': 'running\n'},
                'list-units': {'stdout': ''},
            },
            'free': {'stdout': ('               total used free shared buff/cache available\n'
                                'Mem:           16Gi  8Gi  1Gi  1Gi    7Gi        7Gi\n'
                                'Swap:          2Gi   0B   2Gi\n')},
            'df': {
                '-hPT': {'stdout': ('Filesystem Type Size Used Avail Use% Mounted on\n'
                                    'overlay overlay 100G 20G 80G 20% /\n'
                                    '/dev/sdb ext4 200G 80G 120G 40% /srv/data\n'
                                    'tmpfs tmpfs 1G 1G 0G 100% /run\n')},
                '-iPT': {'stdout': ('Filesystem Type Inodes IUsed IFree IUse% Mounted on\n'
                                    'overlay overlay 1000 200 800 20% /\n'
                                    '/dev/sdb ext4 2000 800 1200 40% /srv/data\n')},
            },
            'timedatectl': {'stdout': 'yes\n'},
            'uname': {'stdout': '6.8.0-9-generic\n'},
            'journalctl': {'stdout': '-- No entries --\n'},
        }
        for name in ('sh', 'timeout', 'awk', 'cat', 'find', 'sort'):
            (self.bin / name).symlink_to(shutil.which(name))
        for name in self.responses:
            path = self.bin / name
            path.write_text(f'#!{sys.executable}\n' + '''import json, os, sys, time
name = os.path.basename(sys.argv[0])
with open(os.environ['STATUS_LOG'], 'a', encoding='utf-8') as log:
    log.write(json.dumps([name, *sys.argv[1:]]) + '\\n')
with open(os.environ['STATUS_RESPONSES'], encoding='utf-8') as source:
    result = json.load(source)[name]
if sys.argv[1:2] and sys.argv[1] in result:
    result = result[sys.argv[1]]
time.sleep(result.get('delay', 0))
sys.stdout.write(result.get('stdout', ''))
sys.stderr.write(result.get('stderr', ''))
sys.exit(result.get('status', 0))
''', encoding='utf-8')
            path.chmod(0o755)
        self.mdstat = self.directory / 'mdstat'
        self.mdstat.write_text('Personalities : [raid1]\nunused devices: <none>\n')
        self.reboot = self.directory / 'reboot-required'
        self.boot = self.directory / 'boot'
        self.boot.mkdir()
        for version in ('6.8.0-9-generic', '6.8.0-10-generic'):
            (self.boot / ('vmlinuz-' + version)).touch()
        self.env = dict(os.environ, PATH=str(self.bin), STATUS_LOG=str(self.log),
                        STATUS_RESPONSES=str(self.responses_file))

    def script(self, *, compact=False):
        return (ops.system_status_script(compact=compact)
                .replace('/proc/mdstat', str(self.mdstat))
                .replace('/run/reboot-required', str(self.reboot))
                .replace('/boot', str(self.boot)))

    def run_report(self, *, compact=False, script=None, terminal=False, term='xterm-256color'):
        self.responses_file.write_text(json.dumps(self.responses), encoding='utf-8')
        command = ['/bin/sh', '-c', script or self.script(compact=compact)]
        env = dict(self.env, TERM=term)
        if not terminal:
            return subprocess.run(command, env=env, capture_output=True, text=True, timeout=12)
        master, slave = os.openpty()
        try:
            result = subprocess.run(command, env=env, stdout=slave, stderr=subprocess.PIPE,
                                    text=True, timeout=12)
            chunks = []
            # macOS discards unread output once the last slave descriptor closes.
            while select.select([master], [], [], 0.2)[0]:
                chunks.append(os.read(master, 65536))
            os.close(slave)
            slave = None
            while True:
                try:
                    chunk = os.read(master, 65536)
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    break
                if not chunk:
                    break
                chunks.append(chunk)
            result.stdout = b''.join(chunks).decode().replace('\r\n', '\n')
            return result
        finally:
            os.close(master)
            if slave is not None:
                os.close(slave)

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_compact_snapshot_fits_and_preserves_overlay_root_without_journal_or_apt(self):
        result = self.run_report(compact=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertLessEqual(len(result.stdout.splitlines()), 15)
        self.assertIn('Systemd: running', result.stdout)
        self.assertIn('Failed units: 0 (none)', result.stdout)
        self.assertIn('Memory: 7Gi available / 16Gi; swap: 0B used / 2Gi', result.stdout)
        self.assertIn('Disk space: / 20% used, 80G available', result.stdout)
        self.assertIn('Disk space: 2 filesystems checked; 0 at >=80%', result.stdout)
        self.assertIn('Reboot: no request recorded', result.stdout)
        self.assertIn('NTP synchronized: yes', result.stdout)
        self.assertNotIn('Software RAID:', result.stdout)
        self.assertNotIn('CPUs:', result.stdout)
        self.assertFalse({'journalctl', 'uname', 'apt-get', 'nproc'} & {command[0] for command in self.commands()})

    def test_warnings_show_units_space_inodes_reboot_and_degraded_raid(self):
        self.responses['systemctl']['is-system-running'] = {'stdout': 'degraded\n', 'status': 1}
        self.responses['systemctl']['list-units']['stdout'] = 'nginx.service loaded failed failed Web server\n'
        self.responses['df']['-hPT']['stdout'] += '/dev/sdc ext4 10G 9G 1G 90% /srv/other data\n'
        self.responses['df']['-iPT']['stdout'] += '/dev/sdc ext4 1000 850 150 85% /srv/other data\n'
        self.mdstat.write_text('md0 : active raid1 sda[0]\n  1000 blocks [2/1] [U_]\n')
        self.reboot.touch()
        result = self.run_report(compact=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for expected in ('WARN Systemd: degraded', 'WARN Failed units: 1\n         nginx.service\n',
                         'WARN Disk space: /srv/other data 90%', 'WARN Inodes: /srv/other data 85%',
                         'WARN Reboot: requested', 'WARN Software RAID: degraded'):
            self.assertIn(expected, result.stdout)

    def test_compact_report_lists_every_failed_unit_on_its_own_line(self):
        units = ['data.mount', 'nvidia-cdi-refresh.path', 'getty@tty1.service',
                 'nginx.service', 'app.service', 'backup.timer', 'worker.service']
        self.responses['systemctl']['list-units']['stdout'] = ''.join(
            f'{unit} loaded failed failed Description\n' for unit in units)
        result = self.run_report(compact=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('WARN Failed units: 7\n' + ''.join(f'         {unit}\n' for unit in units), result.stdout)
        self.assertNotIn('...', result.stdout)

    def test_missing_raid_interface_is_silent(self):
        self.mdstat.unlink()
        result = self.run_report(compact=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('Software RAID:', result.stdout)

    def test_status_column_is_aligned_and_colors_whole_labels(self):
        self.responses['df']['-hPT']['stdout'] += '/dev/sdc ext4 10G 9G 1G 90% /data\n'
        self.responses['timedatectl'] = {'stderr': 'Permission denied\n', 'status': 1}
        for terminal, term in ((False, 'xterm-256color'), (True, 'dumb'), (True, 'xterm-256color')):
            with self.subTest(terminal=terminal, term=term):
                result = self.run_report(compact=True, terminal=terminal, term=term)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('\n     Disk space: / 20% used, 80G available\n', result.stdout)
                if terminal and term != 'dumb':
                    self.assertIn('\n\x1b[33mWARN\x1b[39m Disk space: /data 90%', result.stdout)
                    self.assertIn('\n\x1b[31mERR\x1b[39m  NTP synchronized: unknown', result.stdout)
                    self.assertNotIn('\x1b[7m', result.stdout)
                else:
                    self.assertNotIn('\x1b', result.stdout)
                    self.assertIn('\nWARN Disk space: /data 90%', result.stdout)
                    self.assertIn('\nERR  NTP synchronized: unknown', result.stdout)

    def test_many_warnings_are_counted_but_only_a_few_are_printed_in_compact_view(self):
        self.responses['df']['-hPT']['stdout'] += ''.join(
            f'/dev/disk{i} ext4 10G 9G 1G 90% /data{i}\n' for i in range(7))
        result = self.run_report(compact=True)
        self.assertIn('7 at >=80% (see F7 system for all)', result.stdout)
        self.assertLessEqual(result.stdout.count('WARN Disk space: /'), 3)

    def test_command_failures_are_unknown_not_empty_success(self):
        for name, key in (('systemctl', 'list-units'), ('df', '-iPT'), ('journalctl', None)):
            failure = {'stderr': 'Permission denied\n', 'status': 1}
            if key:
                self.responses[name][key] = failure
            else:
                self.responses[name] = failure
        result = self.run_report()
        self.assertEqual(result.returncode, 1)
        for label in ('Failed units', 'Inodes', 'Journal'):
            self.assertIn(label + ': unknown - Permission denied', result.stdout)
        self.assertNotIn('Failed units: 0', result.stdout)
        self.assertNotIn('No matching visible entries', result.stdout)

    def test_missing_tools_and_malformed_data_are_reported(self):
        (self.bin / 'systemctl').unlink()
        (self.bin / 'timedatectl').unlink()
        self.responses['df']['-iPT']['stdout'] = 'unexpected\n'
        self.responses['free']['stdout'] = 'unexpected\n'
        result = self.run_report(compact=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('Failed units: unknown - systemctl is unavailable', result.stdout)
        self.assertIn('NTP synchronized: unknown - timedatectl is unavailable', result.stdout)
        self.assertIn('Inodes: unknown (no filesystem data)', result.stdout)
        self.assertIn('Memory: unknown (unexpected free output)', result.stdout)

    def test_slow_command_times_out_and_later_sections_still_run(self):
        self.responses['timedatectl']['delay'] = 30
        self.mdstat.write_text('md0 : active raid1 sda[0] sdb[1]\n  1000 blocks [2/2] [UU]\n')
        start = time.monotonic()
        result = self.run_report(compact=True)
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual(result.returncode, 1)
        self.assertIn('NTP synchronized: unknown (timed out)', result.stdout)
        self.assertIn('Software RAID: no degraded member pattern found', result.stdout)

    def test_detailed_report_uses_bounded_journal_queries_and_keeps_access_warnings(self):
        self.responses['journalctl']['stdout'] = 'one visible error\n'
        self.responses['journalctl']['stderr'] = 'Hint: You are currently not seeing messages from other users.\n'
        result = self.run_report()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('CPUs: 8', result.stdout)
        self.assertIn('/srv/data', result.stdout)
        self.assertIn('6.8.0-10-generic (boot selection not checked)', result.stdout)
        self.assertIn('Reboot: no request recorded', result.stdout)
        self.assertIn('visible entries only', result.stdout)
        self.assertIn('not seeing messages from other users', result.stdout)
        commands = [command for command in self.commands() if command[0] == 'journalctl']
        self.assertEqual(len(commands), 2)
        for command in commands:
            self.assertIn('--boot', command)
            self.assertIn('--no-pager', command)
            self.assertEqual(command[command.index('--since') + 1], '-1 hour')
        self.assertIn('--lines=15', commands[0])
        self.assertIn('--lines=5', commands[1])
        self.assertIn('--dmesg', commands[1])
        self.assertTrue(any(arg.startswith('--grep=') for arg in commands[1]))

    def test_no_matching_journal_entries_differs_from_a_failed_query(self):
        self.responses['journalctl'].update(stdout='-- No entries --\n', status=1)
        result = self.run_report()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('Journal: unknown', result.stdout)
        self.responses['journalctl'].update(stdout='', status=1)
        result = self.run_report()
        self.assertEqual(result.returncode, 1)
        self.assertIn('Journal: unknown', result.stdout)

    def test_report_failure_still_leaves_an_interactive_shell(self):
        (self.bin / 'systemctl').unlink()
        shell = self.bin / 'login-shell'
        shell.write_text('#!/bin/sh\nprintf "SHELL_READY:%s\\n" "$1"\n')
        shell.chmod(0o755)
        self.env['SHELL'] = str(shell)
        result = self.run_report(script=ops.check_script('system overview', self.script(compact=True), 10, overview=True))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ERR  Some status information is unavailable.', result.stdout)
        self.assertNotIn('Check exit status:', result.stdout)
        self.assertTrue(result.stdout.endswith('SHELL_READY:-l\n'))

    def test_overview_wrapper_uses_the_same_error_marker_in_a_terminal(self):
        self.env['SHELL'] = shutil.which('true')
        result = self.run_report(script=ops.check_script('system overview', 'exit 23', 10, overview=True), terminal=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('\x1b[31mERR\x1b[39m  System overview could not finish (exit 23).', result.stdout)
        self.assertNotIn('Check exit status:', result.stdout)


if __name__ == '__main__':
    unittest.main()
