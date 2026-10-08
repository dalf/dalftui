"""Test the Windows bootstrap with a temporary Scoop tree and recorded commands instead of Scoop or the network."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dalftui.linux import bootstrap as shared
from dalftui.windows import bootstrap


def done(command, returncode=0, stdout='', stderr=''):
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


def quietly(function, *args, **kwargs):
    with redirect_stdout(io.StringIO()) as output:
        result = function(*args, **kwargs)
    return result, output.getvalue()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding='utf-8')


class FakeScoop(bootstrap.Scoop):
    """Keeps apps and bucket manifests in a temporary Scoop tree; records every command and plays Scoop's part."""

    def __init__(self, scoop, *, dry_run=False, fail=(), busy=(), **kwargs):
        super().__init__(ROOT, scoop=scoop, dry_run=dry_run, **kwargs)
        self.fail = set(fail)
        self.busy = set(busy)
        self.commands = []

    def installed(self, name, version, *, hold=False):
        write_json(self.app(name) / 'scoop-manifest.json', {'version': version})
        write_json(self.app(name) / 'scoop-install.json', {'hold': True} if hold else {})

    def bucket(self, name, version):
        bucket, _, app = name.rpartition('/')
        write_json(self.scoop / 'buckets' / (bucket or 'main') / 'bucket' / f'{app}.json', {'version': version})

    def run(self, command, *, log_output=True):
        if command[:len(self.command)] != self.command:
            self.commands.append(command)
            return done(command, 1 if 'command' in self.fail else 0)
        args = command[len(self.command):]
        self.commands.append(args)
        name = args[-1]
        if args[0] == 'bucket':
            if name not in self.fail:
                (self.scoop / 'buckets' / name).mkdir(parents=True)
        elif args == ['update']:
            return done(command, 1 if 'update' in self.fail else 0)
        elif args[0] == 'install' and name not in self.fail:
            self.installed(name, self.latest(name))
        elif args[0] == 'update':
            if name in self.busy:
                return done(command, stdout="Updating 'python'\nRunning process detected, skip updating.\n")
            if name not in self.fail:
                self.installed(name, self.latest(name))
        return done(command)


class ScoopTestCase(unittest.TestCase):
    def scoop(self, **kwargs):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return FakeScoop(Path(directory.name), **kwargs)


class PackageListTests(unittest.TestCase):
    def test_repository_list_has_the_setup_requirements(self):
        names = shared.read_packages(shared.PACKAGES / 'windows.txt')
        for name in ('git', 'uv', 'oh-my-posh', 'extras/vscode', 'pwsh'):
            self.assertIn(name, names)
        self.assertNotIn('python', names)  # uv provides Python; no plain python command.
        self.assertEqual(len(names), len(set(names)))


class PackageTests(ScoopTestCase):
    def test_versions_come_from_the_current_manifests(self):
        run = self.scoop()
        run.installed('git', '2.56.0')
        run.installed('extras/mc', '4.8')
        write_json(run.app('lsd') / 'manifest.json', {'version': '1.1'})  # Scoop before 0.6
        (run.scoop / 'apps/fzf').mkdir(parents=True)  # A failed install leaves no current version.
        self.assertEqual(run.installed_versions(['git', 'extras/mc', 'lsd', 'fzf', 'jq']),
                         {'git': '2.56.0', 'extras/mc': '4.8', 'lsd': '1.1'})

    def test_refresh_then_install_missing_and_update_only_outdated(self):
        run = self.scoop()
        for name, installed, latest in (('git', '2.55', '2.56'), ('jq', '1.8', '1.8')):
            run.installed(name, installed)
            run.bucket(name, latest)
        run.bucket('fzf', '0.74')
        run.bucket('extras/mc', '4.8')
        quietly(run.packages, ['git', 'jq', 'fzf', 'extras/mc'])
        self.assertEqual(run.commands, [['update'], ['install', 'fzf'], ['install', 'extras/mc'], ['update', 'git']])
        self.assertEqual(run.summary, {'installed': ['fzf', 'extras/mc'], 'upgraded': ['git'],
                                       'skipped': ['jq'], 'failed': []})

    def test_versions_decide_failures_whatever_scoop_exits_with(self):
        run = self.scoop(fail={'update', 'fzf', 'git'}, busy={'python'})
        for name in ('git', 'python', 'jq'):
            run.installed(name, '1')
            run.bucket(name, '2')
        run.installed('lsd', '1', hold=True)
        run.bucket('lsd', '2')
        run.bucket('fzf', '1')
        quietly(run.packages, ['fzf', 'git', 'python', 'jq', 'lsd'])
        self.assertEqual(run.summary, {
            'installed': [], 'upgraded': ['jq'],
            'skipped': ['python (in use; close it, then run scoop update python)', 'lsd'],
            'failed': ['scoop update', 'fzf', 'git']})

    def test_dry_run_compares_with_the_local_buckets(self):
        run = self.scoop(dry_run=True)
        run.installed('git', '2.55')
        run.bucket('git', '2.56')
        run.installed('jq', '1.8')
        run.bucket('jq', '1.8')
        run.installed('lsd', '1', hold=True)
        run.bucket('lsd', '2')
        run.installed('python', '3.12.10')
        write_json(run.app('python') / 'scoop-install.json', {'url': 'C:\\scoop\\workspace\\python.json'})  # @3.12.10
        run.bucket('python', '3.14.8')
        quietly(run.packages, ['git', 'jq', 'lsd', 'python', 'extras/mc'])
        self.assertEqual(run.commands, [])
        self.assertEqual(run.summary, {'installed': ['extras/mc'], 'upgraded': ['git'],
                                       'skipped': ['jq', 'lsd', 'python'], 'failed': []})

    def test_buckets_are_added_only_when_missing(self):
        run = self.scoop()
        quietly(run.buckets, ['git', 'extras/vscode', 'extras/mc'])
        quietly(run.buckets, ['extras/mc'])
        self.assertEqual(run.commands, [['bucket', 'add', 'extras']])
        self.assertEqual(run.summary['installed'], ['extras bucket'])
        self.assertEqual(run.summary['skipped'], ['extras bucket'])
        run = self.scoop(dry_run=True)
        quietly(run.buckets, ['extras/mc'])
        self.assertEqual((run.commands, run.summary['installed']), ([], ['extras bucket']))
        run = self.scoop(fail={'extras'})
        quietly(run.buckets, ['extras/mc'])
        self.assertEqual(run.summary['failed'], ['extras bucket'])


class CheckTests(ScoopTestCase):
    def check_ssh(self, *, exists=True, version=''):
        run = self.scoop()
        with patch.object(bootstrap, 'OPENSSH', Path(run.scoop) / 'ssh.exe'):
            if exists:
                bootstrap.OPENSSH.write_text('', encoding='ascii')
            with patch.object(run, 'query', return_value=done([], stderr=version)):
                run.openssh()
        return run.summary

    def test_openssh_missing_old_or_current(self):
        self.assertIn('Add-WindowsCapability -Online -Name OpenSSH.Client', self.check_ssh(exists=False)['failed'][0])
        self.assertEqual(self.check_ssh(version='OpenSSH_for_Windows_8.1p1, LibreSSL 3.0.2\n')['skipped'],
                         ['OpenSSH client 8.1 (Tag dalftui needs 9.4+)'])
        self.assertEqual(self.check_ssh(version='OpenSSH_for_Windows_9.5p2, LibreSSL 3.8.2\n'),
                         {'installed': [], 'upgraded': [], 'skipped': [], 'failed': []})

    def test_missing_vc_runtime_is_a_failure(self):
        run = self.scoop()
        with patch.object(bootstrap, 'VCRUNTIME', Path(run.scoop) / 'vcruntime140.dll'):
            run.vc_runtime(['bat'])
            self.assertEqual(run.summary['failed'], [])
            run.vc_runtime(['bat', 'extras/vcredist2022'])
            self.assertIn('scoop uninstall vcredist2022; scoop install extras/vcredist2022', run.summary['failed'][0])
            run.summary['failed'].clear()
            bootstrap.VCRUNTIME.write_text('', encoding='ascii')
            run.vc_runtime(['bat', 'extras/vcredist2022'])
        self.assertEqual(run.summary['failed'], [])

    def test_missing_terminal_is_reported(self):
        run = self.scoop()
        with patch.dict(os.environ, {'LOCALAPPDATA': str(run.scoop)}):
            run.terminal()
            self.assertIn('Windows Terminal (not found', run.summary['skipped'][0])
            write_json(run.scoop / 'Microsoft/Windows Terminal/settings.json', {})
            run.summary['skipped'].clear()
            run.terminal()
        self.assertEqual(run.summary['skipped'], [])


class InstallStepTests(ScoopTestCase):
    def install(self, output, *, returncode=0, dry_run=False):
        run = self.scoop(dry_run=dry_run)

        def record(command, **_kwargs):
            run.commands.append(command)
            return done(command, returncode, output)
        with patch.object(run, 'run', side_effect=record):
            run.install_cmd()
        return run

    def test_runs_install_cmd_and_reports_changes(self):
        run = self.install('PowerShell profile configured: C:\\Users\\me\\profile.ps1\n')
        self.assertEqual(run.commands, [[str(ROOT / 'install.cmd')]])
        self.assertEqual(run.summary['installed'], ['install'])
        run = self.install('PowerShell profile already configured.\nVS Code configured: C:\\Code.exe\n')
        self.assertEqual(run.summary['skipped'], ['install'])
        run = self.install('Setup failed: Install the Windows OpenSSH client first\n', returncode=1)
        self.assertEqual(run.summary['failed'], ['install'])

    def test_dry_run_does_not_run_it(self):
        run = self.install('', dry_run=True)
        self.assertEqual(run.commands, [])
        self.assertEqual(run.summary['skipped'], ['install.cmd (not run in a dry run)'])


class StartTests(unittest.TestCase):
    def start(self, **kwargs):
        with patch.object(bootstrap, 'Scoop') as run, patch('sys.stderr', io.StringIO()) as error:
            self.assertEqual(bootstrap.bootstrap(**kwargs), 1)
        run.assert_not_called()
        return error.getvalue()

    def test_refuses_tmux_only(self):
        self.assertIn('--tmux-only is Linux-only', self.start(tmux_only=True))

    def test_refuses_an_elevated_run(self):
        with patch.object(bootstrap.ctypes, 'windll', create=True) as windll:
            windll.shell32.IsUserAnAdmin.return_value = 1
            self.assertIn('non-elevated PowerShell', self.start())

    def test_needs_scoop(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'SCOOP': directory}), \
                patch.object(bootstrap, 'elevated', return_value=False):
            self.assertIn('irm get.scoop.sh | iex; scoop install git uv', self.start())

    def test_log_lives_in_local_app_data(self):
        with patch.dict(os.environ, {'LOCALAPPDATA': '/local'}):
            self.assertEqual(bootstrap.state_directory(), Path('/local/dalftui'))


class RestartTests(unittest.TestCase):
    def test_windows_restart_waits_for_the_new_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.git').mkdir()
            run = FakeScoop(root)
            run.root = root
            heads = iter(['a' * 40, 'b' * 40])

            def query(command):
                return done(command, stdout=next(heads) + '\n' if command[3:4] == ['rev-parse'] and
                            command[4] == 'HEAD' else '')
            with patch.object(run, 'query', side_effect=query), patch.dict(os.environ, {}), \
                    patch.object(shared.os, 'name', 'nt'), patch.object(shared.os, 'execv') as execv, \
                    patch.object(shared.subprocess, 'run', return_value=done([], 3)) as child:
                os.environ.pop(shared.PULLED, None)
                with self.assertRaises(SystemExit) as stop:
                    quietly(run.update_repo, ['--dry-run'])
                self.assertEqual(os.environ[shared.PULLED], 'aaaaaaa..bbbbbbb')
        self.assertEqual(stop.exception.code, 3)
        child.assert_called_once_with([sys.executable, str(root / 'bootstrap'), '--dry-run'], check=False)
        execv.assert_not_called()
        self.assertEqual(run.commands, [['git', '-C', str(root), 'pull', '--ff-only']])


if __name__ == '__main__':
    unittest.main()
