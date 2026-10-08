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


class LauncherTests(unittest.TestCase):
    def test_bootstrap_cmd_runs_as_one_block(self):
        """git pull can rewrite bootstrap.cmd while cmd runs it; cmd reads a parenthesized block at once."""
        lines = (ROOT / 'bootstrap.cmd').read_text(encoding='ascii').splitlines()
        block = [line.strip() for line in lines[lines.index('@('):lines.index(')') + 1]]
        self.assertEqual(block[1], 'where /q scoop && where /q git && where /q uv || goto missing')
        # uv only reports a Python path and exits, so Scoop can update it while bootstrap runs.
        self.assertIn("'uv run --no-project --python \">=3.11\" python -c", block[3])
        self.assertEqual(block[5], 'call "%%DALFTUI_BOOTSTRAP_PYTHON%%" "%~dp0bootstrap" %*')
        self.assertEqual(block[6], 'call exit /b %%ERRORLEVEL%%')  # $LASTEXITCODE gets bootstrap's status.


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


AGENT = {'qc': '        START_TYPE         : {}   AUTO_START\n', 'query': '        STATE              : {}  RUNNING\n'}


class CheckTests(ScoopTestCase):
    def check_ssh(self, *, system32=True, msi=False, version='OpenSSH_for_Windows_9.5p1\n', agent=(2, 4),
                  enabled=(2, 4), desktop=True, gsudo=True, dry_run=False, names=(), vcredist=False):
        """Run the OpenSSH step; the elevated command, when run, turns the agent state into enabled."""
        run = self.scoop(dry_run=dry_run)
        state = {'agent': agent}
        if vcredist:
            run.app('extras/vcredist2022').mkdir(parents=True)
            (run.app('extras/vcredist2022') / 'vc_redist.x64.exe').write_text('', encoding='ascii')
        if gsudo:
            run.app('gsudo').mkdir(parents=True)
            (run.app('gsudo') / 'gsudo.exe').write_text('', encoding='ascii')

        def query(command):
            if command[-1] != 'ssh-agent' or state['agent'] is None:
                return done(command, stderr=version)
            return done(command, stdout=AGENT[command[1]].format(state['agent'][command[1] == 'query']))

        def elevate(command, **_):
            run.commands.append(command)
            state['agent'] = enabled
            if 'Add-WindowsCapability' in command[-1]:
                bootstrap.OPENSSH.write_text('', encoding='ascii')
            if 'vc_redist.x64.exe' in command[-1]:
                bootstrap.VCRUNTIME.write_text('', encoding='ascii')
            return done(command)
        with patch.object(bootstrap, 'OPENSSH', run.scoop / 'System32/ssh.exe'), \
                patch.object(bootstrap, 'VCRUNTIME', run.scoop / 'System32/vcruntime140.dll'), \
                patch.object(bootstrap, 'OPENSSH_MSI', run.scoop / 'Program Files/ssh.exe'), \
                patch.object(bootstrap, 'interactive', return_value=desktop), \
                patch.object(run, 'query', side_effect=query), patch.object(run, 'run', side_effect=elevate):
            for path, present in ((bootstrap.OPENSSH, system32), (bootstrap.OPENSSH_MSI, msi)):
                path.parent.mkdir(parents=True, exist_ok=True)
                if present:
                    path.write_text('', encoding='ascii')
            quietly(run.system, names)
        return run.summary, run.commands

    def test_openssh_old_or_current(self):
        self.assertEqual(self.check_ssh(version='OpenSSH_for_Windows_8.1p1, LibreSSL 3.0.2\n')[0]['skipped'],
                         ['OpenSSH client 8.1 (Tag dalftui needs 9.4+)'])
        self.assertEqual(self.check_ssh(), ({'installed': [], 'upgraded': [], 'skipped': [], 'failed': []}, []))
        # The MSI client (winget Microsoft.OpenSSH.Preview) counts; the built-in one is not added back.
        self.assertEqual(self.check_ssh(system32=False, msi=True)[1], [])

    def test_agent_service_is_enabled_through_one_uac_prompt(self):
        summary, commands = self.check_ssh(agent=(4, 1))
        self.assertEqual(summary['installed'], ['ssh-agent service'])
        self.assertEqual(len(commands), 1)
        self.assertTrue(commands[0][0].endswith('gsudo.exe'))
        self.assertIn(bootstrap.AGENT_ENABLE, commands[0][-1])
        summary, commands = self.check_ssh(system32=False, agent=None)
        self.assertEqual(summary['installed'], ['OpenSSH client', 'ssh-agent service'])
        self.assertIn(bootstrap.OPENSSH_ADD + '; ' + bootstrap.AGENT_ENABLE, commands[0][-1])

    def test_declined_prompt_reports_the_commands(self):
        summary = self.check_ssh(agent=(4, 1), enabled=(4, 1))[0]
        self.assertEqual(summary['failed'], [f'ssh-agent service (as administrator: {bootstrap.AGENT_ENABLE})'])

    def test_without_a_desktop_or_gsudo_nothing_is_elevated(self):
        summary, commands = self.check_ssh(agent=None, desktop=False)
        self.assertEqual((summary['skipped'], commands), ([f'ssh-agent service (not visible without a desktop '
                                                           f'session; as administrator: {bootstrap.AGENT_ENABLE})'], []))
        summary, commands = self.check_ssh(system32=False, agent=None, desktop=False)
        self.assertIn(f'no desktop for the UAC prompt; as administrator: {bootstrap.OPENSSH_ADD}', summary['failed'][0])
        self.assertIn('ssh-agent service (no desktop', summary['skipped'][0])
        self.assertEqual(commands, [])
        summary, commands = self.check_ssh(agent=(3, 1), gsudo=False)
        self.assertIn('gsudo is not installed', summary['skipped'][0])
        self.assertEqual(commands, [])

    def test_dry_run_lists_the_administrator_steps(self):
        summary, commands = self.check_ssh(agent=(4, 1), dry_run=True)
        self.assertEqual((summary['installed'], commands), (['ssh-agent service (administrator)'], []))

    def git_ssh(self, current='', *, client='System32/OpenSSH/ssh.exe', dry_run=False):
        run = self.scoop(dry_run=dry_run)
        (run.scoop / 'shims').mkdir(parents=True)
        (run.scoop / 'shims/git.exe').write_text('', encoding='ascii')
        with patch.object(bootstrap, 'openssh_client', return_value=Path('C:/', client)), \
                patch.object(run, 'query', return_value=done([], stdout=current + '\n' if current else '')):
            quietly(run.git_ssh)
        return run.summary, [command[1:] for command in run.commands]

    def test_git_uses_the_windows_ssh_client(self):
        summary, commands = self.git_ssh()
        self.assertEqual(summary['installed'], ['Git core.sshCommand'])
        self.assertEqual(commands, [['config', '--global', 'core.sshCommand', 'C:/System32/OpenSSH/ssh.exe']])
        self.assertEqual(self.git_ssh(client='Program Files/OpenSSH/ssh.exe')[1][0][-1],
                         "'C:/Program Files/OpenSSH/ssh.exe'")
        for same in ('C:/System32/OpenSSH/ssh.exe', 'C:\\SYSTEM32\\OpenSSH\\ssh.exe'):
            self.assertEqual(self.git_ssh(same), ({'installed': [], 'upgraded': [], 'skipped': [], 'failed': []}, []))
        self.assertEqual(self.git_ssh('plink'), ({'installed': [], 'upgraded': [], 'skipped':
                                                   ['Git core.sshCommand (kept: plink)'], 'failed': []}, []))
        self.assertEqual(self.git_ssh(dry_run=True), ({'installed': ['Git core.sshCommand'], 'upgraded': [],
                                                        'skipped': [], 'failed': []}, []))

    def test_vc_runtime_shares_the_uac_prompt(self):
        run = self.scoop()
        installer = run.app('extras/vcredist2022') / "vc_redist.x64.exe"
        installer.parent.mkdir(parents=True)
        installer.write_text('', encoding='ascii')
        with patch.object(bootstrap, 'VCRUNTIME', run.scoop / 'vcruntime140.dll'):
            self.assertIsNone(run.vc_runtime(['bat']))
            label, command, check = run.vc_runtime(['bat', 'extras/vcredist2022'])
            self.assertEqual((label, check()), ('VC++ runtime', False))
            self.assertEqual(command, f"Start-Process -Wait '{installer}' '/install /quiet /norestart'")
            bootstrap.VCRUNTIME.write_text('', encoding='ascii')
            self.assertIsNone(run.vc_runtime(['bat', 'extras/vcredist2022']))
        summary, commands = self.check_ssh(agent=(4, 1), names=['extras/vcredist2022'], vcredist=True)
        self.assertEqual(summary['installed'], ['VC++ runtime', 'ssh-agent service'])
        self.assertEqual(len(commands), 1)
        self.assertIn("'/install /quiet /norestart'; " + bootstrap.AGENT_ENABLE, commands[0][-1])

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


class OutputTests(ScoopTestCase):
    def test_colour_needs_virtual_terminal_processing(self):
        class Terminal(io.StringIO):
            def isatty(self):
                return True
        for enabled in (True, False):
            with self.subTest(enabled=enabled), redirect_stdout(Terminal()), \
                    patch.dict(os.environ, {'TERM': 'xterm-256color'}), \
                    patch.object(bootstrap, 'virtual_terminal', return_value=enabled):
                os.environ.pop('NO_COLOR', None)
                self.assertEqual(self.scoop().color, enabled)

    def test_virtual_terminal_is_enabled_on_the_console(self):
        with patch.object(bootstrap.ctypes, 'windll', create=True) as windll:
            kernel32 = windll.kernel32
            kernel32.GetConsoleMode.return_value = 1
            kernel32.SetConsoleMode.return_value = 1
            self.assertTrue(bootstrap.virtual_terminal())
            self.assertEqual(kernel32.SetConsoleMode.call_args.args[1], 4)  # The mocked mode starts at 0.
            kernel32.GetConsoleMode.return_value = 0  # Redirected output: no console.
            self.assertFalse(bootstrap.virtual_terminal())

    def test_steps_have_headings_and_results(self):
        with redirect_stdout(io.StringIO()) as output:
            run = self.scoop()  # Symbols are chosen for the output in place when the run starts.
        with redirect_stdout(output), patch.dict(os.environ, {'LOCALAPPDATA': str(run.scoop)}):
            with run.step('Windows Terminal'):
                run.terminal()
        self.assertEqual(output.getvalue(), f'\n{shared.SYMBOLS[0]} Windows Terminal\n  · Windows Terminal (not found; install it '
                                            'from the Microsoft Store and open it once)\n')


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
