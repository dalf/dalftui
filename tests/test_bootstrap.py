"""Test the bootstrap with recorded commands instead of dnf, apt, sudo or the network."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dalftui.linux import bootstrap


APT_UPGRADE = bootstrap.APT + ['install', '--only-upgrade']


def done(command, returncode=0, stdout=''):
    return subprocess.CompletedProcess(command, returncode, stdout, '')


class FakeBootstrap(bootstrap.Bootstrap):
    """Answers rpm -q and dpkg-query from `versions` and records every command that would change something."""

    def __init__(self, versions, *, dry_run=False, upgrades=(), fail=(), root=ROOT, **kwargs):
        super().__init__(root, dry_run=dry_run, **kwargs)
        self.versions = dict(versions)
        self.upgrades = dict(upgrades)
        self.fail = set(fail)
        self.commands = []
        self.queries = []

    def query(self, command):
        self.queries.append(command)
        if command[:2] == ['rpm', '-q']:
            names = command[4:]
            return done(command, stdout=''.join(
                f'{name} {self.versions[name]}\n' if name in self.versions
                else f'package {name} is not installed\n' for name in names))
        if command[:2] == ['dpkg-query', '-W']:
            return done(command, stdout=''.join(
                f'{name} ii {self.versions[name]}\n' for name in command[3:] if name in self.versions))
        if command[:2] == ['dnf', 'repoquery']:
            return done(command, stdout=''.join(f'{name}\n' for name in command[6:] if name in self.upgrades))
        if command[:2] == ['apt-get', '-s']:
            return done(command, stdout=''.join(f'Inst {name} [1] ({self.upgrades[name]} Debian:13)\n'
                                                for name in command[4:] if name in self.upgrades))
        raise AssertionError(f'Unexpected query: {command}')

    def run(self, command, *, log_output=True):
        self.commands.append(command)
        if command[:3] == ['sudo', 'dnf', 'install'] or command == bootstrap.APT + ['install', command[-1]]:
            name = command[-1]
            if name in self.fail:
                return done(command, 1)
            if 'lock' in self.fail:
                return done(command, 100, 'E: Unable to acquire the dpkg frontend lock (/var/lib/dpkg/lock-frontend)\n')
            self.versions[name] = '1.0-1'
        elif command[:3] == ['sudo', 'dnf', 'upgrade'] or command[:len(APT_UPGRADE)] == APT_UPGRADE:
            names = command[4:] if command[1] == 'dnf' else command[len(APT_UPGRADE):]
            if any(name in self.fail for name in names):
                return done(command, 1)
            for name in names:
                self.versions[name] = self.upgrades.get(name, self.versions[name])
        elif command == bootstrap.APT + ['update']:
            return done(command, 1 if 'update' in self.fail else 0)
        return done(command)

    def sudo(self):
        self.commands.append(['sudo', '-v'])
        return True


class FakeBrew(bootstrap.Brew):
    """Answers brew list, outdated and bundle list from `versions`; brew bundle applies `upgrades` and installs the rest."""

    def __init__(self, versions, *, upgrades=(), fail=(), dry_run=False, entries=((), ())):
        super().__init__(ROOT, brew='brew', dry_run=dry_run)
        self.versions = dict(versions)
        self.upgrades = dict(upgrades)
        self.fail = set(fail)
        self.formulae, self.casks = entries
        self.outdated_output = None
        self.commands = []
        self.queries = []

    def query(self, command):
        self.queries.append(command)
        if command[1:3] == ['bundle', 'list']:
            return done(command, stdout=''.join(f'{name}\n' for name in
                                                (self.formulae if command[3] == '--formula' else self.casks)))
        if command[1:] == ['list', '--versions']:
            return done(command, stdout=''.join(f'{name} {version}\n' for name, version in self.versions.items()
                                                if name not in self.casks))
        if command[1:] == ['list', '--cask', '--versions']:
            return done(command, stdout=''.join(f'{name} {version}\n' for name, version in self.versions.items()
                                                if name in self.casks))
        if command[1:] == ['outdated', '--json=v2']:
            outdated = [{'name': name} for name in self.upgrades]
            output = self.outdated_output or json.dumps({'formulae': outdated, 'casks': []})
            return done(command, 1 if outdated else 0, output)
        raise AssertionError(f'Unexpected query: {command}')

    def run(self, command, *, log_output=True):
        self.commands.append(command)
        if command[1] == 'update':
            return done(command, 1 if 'update' in self.fail else 0)
        if command[1] == 'bundle':
            for name in self.formulae + self.casks:
                if name not in self.fail:
                    self.versions[name] = self.upgrades.get(name, self.versions.get(name, '1.0'))
        return done(command)


def quietly(function, *args, **kwargs):
    with redirect_stdout(io.StringIO()) as output:
        result = function(*args, **kwargs)
    return result, output.getvalue()


class PackageListTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'fedora.txt'

    def test_comments_and_desktop_section(self):
        self.path.write_text('# heading\ngit  # comment\n\ntmux\n[desktop]\nalacritty\n', encoding='utf-8')
        self.assertEqual(bootstrap.read_packages(self.path), ['git', 'tmux', 'alacritty'])
        self.assertEqual(bootstrap.read_packages(self.path, tmux_only=True), ['git', 'tmux'])

    def test_unknown_section_is_an_error(self):
        self.path.write_text('git\n[server]\ntmux\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, r'Unknown section .*\[server\]'):
            bootstrap.read_packages(self.path)

    def test_repository_lists_are_valid_and_have_install_requirements(self):
        for family, ssh, aws in (('fedora', 'openssh-clients', 'awscli2'), ('debian', 'openssh-client', 'awscli')):
            with self.subTest(family=family):
                server = bootstrap.read_packages(bootstrap.PACKAGES / f'{family}.txt', tmux_only=True)
                desktop = bootstrap.read_packages(bootstrap.PACKAGES / f'{family}.txt')
                for name in ('python3', 'git', 'tmux', 'less', 'fontconfig', 'curl', 'unzip'):
                    self.assertIn(name, server)
                self.assertEqual(set(desktop) - set(server), {ssh, 'alacritty', 'code', 'dvc', aws, 'rclone', 'fido2-tools'})
        # Debian's yq is a different program from the mikefarah/yq that Fedora installs.
        self.assertNotIn('yq', bootstrap.read_packages(bootstrap.PACKAGES / 'debian.txt'))

    def test_brewfile_has_install_requirements(self):
        formulae = re.findall(r'^brew "([^"]+)"', bootstrap.BREWFILE.read_text(encoding='utf-8'), re.MULTILINE)
        for name in ('git', 'tmux', 'oh-my-posh', 'uv'):
            self.assertIn(name, formulae)


class PackageTests(unittest.TestCase):
    def test_missing_installed_one_by_one_and_present_upgraded_together(self):
        run = FakeBootstrap({'git': '2.0-1', 'tmux': '3.7-1'}, upgrades={'tmux': '3.8-1'})
        quietly(run.packages, ['git', 'tmux', 'fzf', 'lsd'])
        self.assertEqual(run.commands, [
            ['sudo', '-v'],
            ['sudo', 'dnf', 'install', '-y', 'fzf'],
            ['sudo', 'dnf', 'install', '-y', 'lsd'],
            ['sudo', 'dnf', 'upgrade', '-y', 'git', 'tmux'],
        ])
        self.assertEqual(run.summary, {'installed': ['fzf', 'lsd'], 'upgraded': ['tmux'],
                                       'skipped': ['git'], 'failed': []})

    def test_one_failure_does_not_stop_the_others(self):
        run = FakeBootstrap({'git': '2.0-1', 'bat': '1-1'}, upgrades={'git': '2.1-1'}, fail={'fzf', 'bat'})
        quietly(run.packages, ['fzf', 'lsd', 'git', 'bat'])
        self.assertIn(['sudo', 'dnf', 'install', '-y', 'lsd'], run.commands)
        # The combined upgrade failed, so each package was retried alone.
        self.assertEqual(run.commands[-2:], [['sudo', 'dnf', 'upgrade', '-y', 'git'],
                                             ['sudo', 'dnf', 'upgrade', '-y', 'bat']])
        self.assertEqual(run.summary, {'installed': ['lsd'], 'upgraded': ['git'],
                                       'skipped': [], 'failed': ['fzf', 'bat']})
        _, output = quietly(run.report)
        self.assertIn('Failed: 2 (fzf, bat)', output)

    def test_dry_run_only_queries(self):
        run = FakeBootstrap({'git': '2.0-1', 'tmux': '3.7-1'}, dry_run=True, upgrades={'tmux': '3.8-1'})
        quietly(run.packages, ['git', 'tmux', 'fzf'])
        self.assertEqual(run.commands, [])
        self.assertEqual(run.summary, {'installed': ['fzf'], 'upgraded': ['tmux'],
                                       'skipped': ['git'], 'failed': []})

    def test_dry_run_reports_a_failed_upgrade_check(self):
        run = FakeBootstrap({'tmux': '3.7-1'}, dry_run=True)
        query = run.query
        run.query = lambda command: done(command, 1) if command[1] == 'repoquery' else query(command)
        quietly(run.packages, ['tmux'])
        self.assertEqual(run.summary['failed'], ['upgrade check (dnf repoquery)'])


class AptPackageTests(unittest.TestCase):
    def test_update_then_missing_one_by_one_and_present_upgraded_together(self):
        run = FakeBootstrap({'git': '1:2.47', 'tmux': '3.5a-3'}, upgrades={'tmux': '3.5a-4'}, apt=True)
        quietly(run.packages, ['git', 'tmux', 'fzf', 'lsd'])
        self.assertEqual(run.commands, [
            ['sudo', '-v'],
            bootstrap.APT + ['update'],
            bootstrap.APT + ['install', 'fzf'],
            bootstrap.APT + ['install', 'lsd'],
            APT_UPGRADE + ['git', 'tmux'],
        ])
        self.assertEqual(run.commands[1][:4], ['sudo', 'env', 'DEBIAN_FRONTEND=noninteractive', 'apt-get'])
        self.assertEqual(run.summary, {'installed': ['fzf', 'lsd'], 'upgraded': ['tmux'],
                                       'skipped': ['git'], 'failed': []})

    def test_failures_do_not_stop_the_others(self):
        run = FakeBootstrap({'git': '1', 'bat': '1'}, upgrades={'git': '2'}, fail={'update', 'fzf', 'bat'}, apt=True)
        quietly(run.packages, ['fzf', 'lsd', 'git', 'bat'])
        self.assertIn(bootstrap.APT + ['install', 'lsd'], run.commands)
        self.assertEqual(run.commands[-2:], [APT_UPGRADE + ['git'], APT_UPGRADE + ['bat']])
        self.assertEqual(run.summary, {'installed': ['lsd'], 'upgraded': ['git'],
                                       'skipped': [], 'failed': ['apt-get update', 'fzf', 'bat']})

    def test_held_dpkg_lock_stops_the_remaining_commands(self):
        run = FakeBootstrap({'git': '1', 'tmux': '1'}, fail={'lock'}, apt=True)
        quietly(run.packages, ['fzf', 'lsd', 'git', 'tmux'])
        self.assertEqual(run.commands[-1], bootstrap.APT + ['install', 'fzf'])
        self.assertEqual(run.summary['failed'], ['fzf', 'lsd', 'git', 'tmux'])

    def test_dry_run_only_queries(self):
        run = FakeBootstrap({'git': '1', 'tmux': '3.5a-3'}, dry_run=True, upgrades={'tmux': '3.5a-4'}, apt=True)
        quietly(run.packages, ['git', 'tmux', 'fzf'])
        self.assertEqual(run.commands, [])
        self.assertEqual(run.queries[-1], ['apt-get', '-s', 'install', '--only-upgrade', 'git', 'tmux'])
        self.assertEqual(run.summary, {'installed': ['fzf'], 'upgraded': ['tmux'],
                                       'skipped': ['git'], 'failed': []})

    def test_only_installed_rows_count(self):
        run = FakeBootstrap({}, apt=True)
        run.query = lambda command: done(command, 1, 'git ii 1:2.47\nzsh rc 5.9\nfzf un <none>\n')
        self.assertEqual(run.installed_versions(['git', 'zsh', 'fzf']), {'git': '1:2.47'})


class BrewTests(unittest.TestCase):
    ENTRIES = (['git', 'tmux', 'fzf', 'lsd'], ['visual-studio-code'])

    def test_update_then_one_bundle_and_versions_decide(self):
        run = FakeBrew({'git': '2.50.0', 'tmux': '3.5a', 'lsd': '1.1.5', 'visual-studio-code': '1.104.0'},
                       upgrades={'tmux': '3.6', 'lsd': '1.1.5'}, fail={'lsd'}, entries=self.ENTRIES)
        quietly(run.packages, run.entries())
        self.assertEqual(run.commands, [['brew', 'update'], ['brew', 'bundle', '--file', str(bootstrap.BREWFILE)]])
        # lsd stayed outdated after the bundle.
        self.assertEqual(run.summary, {'installed': ['fzf'], 'upgraded': ['tmux'],
                                       'skipped': ['git', 'visual-studio-code'], 'failed': ['lsd']})

    def test_failed_update_and_missing_entry_are_reported(self):
        run = FakeBrew({}, fail={'update', 'fzf'}, entries=self.ENTRIES)
        quietly(run.packages, run.entries())
        self.assertEqual(run.commands[-1][:2], ['brew', 'bundle'])
        self.assertEqual(run.summary['failed'], ['brew update', 'fzf'])
        self.assertEqual(run.summary['installed'], ['git', 'tmux', 'lsd', 'visual-studio-code'])

    def test_unreadable_outdated_output_is_a_failed_check(self):
        run = FakeBrew({'git': '2.50.0'}, dry_run=True, entries=self.ENTRIES)
        run.outdated_output = 'Error: something\n'
        quietly(run.packages, ['git'])
        self.assertEqual(run.summary['failed'], ['upgrade check (brew outdated)'])

    def test_dry_run_only_queries(self):
        run = FakeBrew({'git': '2.50.0', 'tmux': '3.5a'}, dry_run=True, upgrades={'tmux': '3.6'},
                       entries=self.ENTRIES)
        quietly(run.packages, run.entries())
        self.assertEqual(run.commands, [])
        self.assertEqual(run.summary, {'installed': ['fzf', 'lsd', 'visual-studio-code'], 'upgraded': ['tmux'],
                                       'skipped': ['git'], 'failed': []})


class StartTests(unittest.TestCase):
    def test_refuses_root(self):
        with patch.object(bootstrap.os, 'geteuid', return_value=0), \
                patch.object(bootstrap, 'Bootstrap') as run, patch('sys.stderr', io.StringIO()) as error:
            self.assertEqual(bootstrap.bootstrap(), 1)
        self.assertIn('as your user', error.getvalue())
        run.assert_not_called()

    def test_refuses_an_unknown_system(self):
        with patch.object(bootstrap.os, 'geteuid', return_value=1000), patch.object(bootstrap.sys, 'platform', 'linux'), \
                patch.object(bootstrap, 'family', return_value=None), \
                patch.object(bootstrap, 'Bootstrap') as run, patch('sys.stderr', io.StringIO()) as error:
            self.assertEqual(bootstrap.bootstrap(), 1)
        self.assertIn('needs Fedora, Debian or Ubuntu', error.getvalue())
        run.assert_not_called()

    def test_macos_needs_homebrew_and_refuses_tmux_only(self):
        for tmux_only, message in ((False, 'install Homebrew first: /bin/bash -c'), (True, '--tmux-only is Linux-only')):
            with self.subTest(tmux_only=tmux_only), patch.object(bootstrap.os, 'geteuid', return_value=501), \
                    patch.object(bootstrap.sys, 'platform', 'darwin'), \
                    patch.object(bootstrap.shutil, 'which', return_value=None), \
                    patch.object(bootstrap, 'BREW_PATHS', ()), \
                    patch.object(bootstrap, 'Brew') as run, patch('sys.stderr', io.StringIO()) as error:
                self.assertEqual(bootstrap.bootstrap(tmux_only=tmux_only), 1)
            self.assertIn(message, error.getvalue())
            run.assert_not_called()

    def test_dvc_is_skipped_off_x86_64(self):
        for machine, dvc in (('x86_64', True), ('aarch64', False)):
            with self.subTest(machine=machine), tempfile.TemporaryDirectory() as directory, \
                    patch.object(bootstrap.os, 'geteuid', return_value=1000), \
                    patch.object(bootstrap.sys, 'platform', 'linux'), \
                    patch.object(bootstrap, 'family', return_value='fedora'), \
                    patch.object(bootstrap.shutil, 'which', return_value='/usr/bin/sudo'), \
                    patch.object(bootstrap, 'state_directory', return_value=Path(directory)), \
                    patch.object(bootstrap.platform, 'machine', return_value=machine), \
                    patch.dict(os.environ, {'PATH': os.environ.get('PATH', '')}), \
                    patch.object(bootstrap, 'Bootstrap') as bootstrap_class:
                bootstrap.bootstrap()
            run = bootstrap_class.return_value
            run.vscode_repo.assert_called_once_with()
            self.assertEqual(run.dvc_repo.called, dvc)
            self.assertEqual('dvc' in run.packages.call_args.args[0], dvc)
            skipped = [call.args for call in run.add.call_args_list]
            self.assertEqual(skipped, [] if dvc else [('skipped', ['DVC repository and dvc (x86-64 only)'])])

    def test_macos_refuses_root_without_mentioning_sudo(self):
        with patch.object(bootstrap.os, 'geteuid', return_value=0), patch.object(bootstrap.sys, 'platform', 'darwin'), \
                patch('sys.stderr', io.StringIO()) as error:
            self.assertEqual(bootstrap.bootstrap(), 1)
        self.assertEqual(error.getvalue(), 'Bootstrap failed: run ./bootstrap as your user.\n')

    def test_family_from_os_release(self):
        for release, expected in (({'ID': 'fedora'}, 'fedora'), ({'ID': 'debian'}, 'debian'),
                                  ({'ID': 'ubuntu', 'ID_LIKE': 'debian'}, 'debian'), ({'ID': 'arch'}, None)):
            with self.subTest(release=release), \
                    patch.object(bootstrap.platform, 'freedesktop_os_release', return_value=release):
                self.assertEqual(bootstrap.family(), expected)
        with patch.object(bootstrap.platform, 'freedesktop_os_release', side_effect=OSError):
            self.assertIsNone(bootstrap.family())


class UserToolTests(unittest.TestCase):
    """oh-my-posh, mise and uv: official installer when missing, their own upgrade command afterwards."""
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        self.binary = self.home / '.local/bin/oh-my-posh'

    def run_step(self, *, installed, before='1.0', after='1.0', dry_run=False, step='oh_my_posh'):
        run = FakeBootstrap({}, dry_run=dry_run)
        versions = iter([before, after])
        state = {'installed': installed}

        def which(_name):
            return str(self.binary) if state['installed'] else None

        def query(command):
            run.queries.append(command)
            return done(command, stdout=next(versions) + '\n')

        def record(command, **_kwargs):
            run.commands.append(command)
            state['installed'] = True
            return done(command)
        with patch.object(bootstrap.Path, 'home', return_value=self.home), \
                patch.object(bootstrap.shutil, 'which', side_effect=which), \
                patch.object(bootstrap.os, 'access', return_value=True), \
                patch.object(run, 'query', side_effect=query), patch.object(run, 'run', side_effect=record):
            quietly(getattr(run, step))
        return run

    def test_missing_uses_the_official_installer(self):
        run = self.run_step(installed=False)
        self.assertEqual(len(run.commands), 1)
        self.assertEqual(run.commands[0][:2], ['bash', '-c'])
        self.assertIn('curl -fsSL https://ohmyposh.dev/install.sh | bash -s -- -d ', run.commands[0][2])
        self.assertTrue(self.binary.parent.is_dir())
        self.assertEqual(run.summary['installed'], ['oh-my-posh'])

    def test_mise_uses_mise_run_then_self_update(self):
        self.binary = self.home / '.local/bin/mise'
        run = self.run_step(installed=False, step='mise')
        self.assertEqual(run.commands, [['bash', '-c', 'set -o pipefail; curl -fsSL https://mise.run | sh']])
        self.assertEqual(run.summary['installed'], ['mise'])
        run = self.run_step(installed=True, before='2026.9.1', after='2026.10.3', step='mise')
        self.assertEqual(run.commands, [[str(self.binary), 'self-update', '--yes', '--no-plugins']])
        self.assertEqual(run.summary['upgraded'], ['mise (2026.9.1 -> 2026.10.3)'])

    def test_uv_uses_astral_installer_then_self_update(self):
        self.binary = self.home / '.local/bin/uv'
        run = self.run_step(installed=False, step='uv')
        self.assertEqual(run.commands, [['bash', '-c', 'set -o pipefail; curl -fsSL https://astral.sh/uv/install.sh | sh']])
        self.assertEqual(run.summary['installed'], ['uv'])
        run = self.run_step(installed=True, before='uv 0.12.19', after='uv 0.12.23', step='uv')
        self.assertEqual(run.commands, [[str(self.binary), 'self', 'update']])
        self.assertEqual(run.summary['upgraded'], ['uv (uv 0.12.19 -> uv 0.12.23)'])

    def test_present_upgrades_and_reports_versions(self):
        run = self.run_step(installed=True, before='31.4.0', after='31.5.0')
        self.assertEqual(run.commands, [[str(self.binary), 'upgrade']])
        self.assertEqual(run.summary['upgraded'], ['oh-my-posh (31.4.0 -> 31.5.0)'])

    def test_current_version_is_skipped(self):
        run = self.run_step(installed=True, before='31.5.0', after='31.5.0')
        self.assertEqual(run.summary['skipped'], ['oh-my-posh'])

    def test_dry_run_changes_nothing(self):
        for installed, category in ((False, 'installed'), (True, 'skipped')):
            with self.subTest(installed=installed):
                run = self.run_step(installed=installed, dry_run=True)
                self.assertEqual(run.commands, [])
                self.assertEqual(len(run.summary[category]), 1)


# Each repository step: method, summary name, file stem, rpm key, apt key and keyring.
REPOSITORIES = (
    ('vscode_repo', 'VS Code repository', 'vscode', 'VSCODE_KEY', 'VSCODE_KEY', '/usr/share/keyrings/microsoft.asc'),
    ('dvc_repo', 'DVC repository', 'dvc', 'DVC_RPM_KEY', 'DVC_APT_KEY', '/usr/share/keyrings/iterative.asc'),
)


class RepositoryStepTests(unittest.TestCase):
    def add_repo(self, method, stem, *, exists, dry_run=False):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / f'{stem}.repo'
            if exists:
                repo.write_text('[repo]\n', encoding='utf-8')
            run = FakeBootstrap({}, dry_run=dry_run)
            with patch.object(bootstrap, f'{stem.upper()}_REPO', repo):
                quietly(getattr(run, method))
        return run, repo

    def test_missing_repository_is_added_with_the_key(self):
        for method, name, stem, key, _, _ in REPOSITORIES:
            with self.subTest(method=method):
                run, repo = self.add_repo(method, stem, exists=False)
                self.assertEqual(run.commands[:2], [['sudo', '-v'], ['sudo', 'rpm', '--import', getattr(bootstrap, key)]])
                self.assertEqual(run.commands[2][:3], ['sudo', 'sh', '-c'])
                self.assertIn(f'> {repo}', run.commands[2][3])
                self.assertEqual(run.summary['installed'], [name])
        self.assertIn('baseurl=https://packages.microsoft.com/yumrepos/vscode\n', bootstrap.VSCODE_REPO_TEXT)
        self.assertIn('baseurl=https://dvc.org/rpm/\n', bootstrap.DVC_REPO_TEXT)
        self.assertIn('gpgcheck=1\ngpgkey=https://dvc.org/rpm/iterative.asc\n', bootstrap.DVC_REPO_TEXT)

    def test_existing_repository_and_dry_run_change_nothing(self):
        for method, name, stem, _, _, _ in REPOSITORIES:
            for exists, dry_run, category in ((True, False, 'skipped'), (False, True, 'installed')):
                with self.subTest(method=method, exists=exists, dry_run=dry_run):
                    run, _ = self.add_repo(method, stem, exists=exists, dry_run=dry_run)
                    self.assertEqual(run.commands, [])
                    self.assertEqual(run.summary[category], [name])


class AptRepositoryStepTests(unittest.TestCase):
    def add_repo(self, method, stem, *, existing=None):
        with tempfile.TemporaryDirectory() as directory:
            sources = Path(directory) / f'{stem}.sources'
            if existing:
                (Path(directory) / existing).write_text('deb ...\n', encoding='utf-8')
            run = FakeBootstrap({}, apt=True)
            response = io.BytesIO(b'-----BEGIN PGP PUBLIC KEY BLOCK-----\n')
            with patch.object(bootstrap, f'{stem.upper()}_SOURCES', sources), \
                    patch.object(bootstrap.urllib.request, 'urlopen', return_value=response) as urlopen:
                quietly(getattr(run, method))
        return run, sources, urlopen

    def test_missing_repository_writes_the_key_and_sources(self):
        for method, name, stem, _, key, keyring in REPOSITORIES:
            with self.subTest(method=method):
                run, sources, urlopen = self.add_repo(method, stem)
                urlopen.assert_called_once_with(getattr(bootstrap, key), timeout=60)
                self.assertEqual(run.commands[0], ['sudo', '-v'])
                self.assertIn('BEGIN PGP', run.commands[1][3])
                self.assertIn(f'> {keyring}', run.commands[1][3])
                self.assertIn(f'> {sources}', run.commands[2][3])
                self.assertIn(f'Signed-By: {keyring}\n', getattr(bootstrap, f'{stem.upper()}_SOURCES_TEXT'))
                self.assertEqual(run.summary['installed'], [name])
        self.assertEqual(bootstrap.DVC_SOURCES_TEXT, 'Types: deb\nURIs: https://dvc.org/deb/\nSuites: stable\n'
                         'Components: main\nArchitectures: amd64\nSigned-By: /usr/share/keyrings/iterative.asc\n')

    def test_existing_sources_or_older_list_change_nothing(self):
        for method, name, stem, _, _, _ in REPOSITORIES:
            for existing in (f'{stem}.sources', f'{stem}.list'):
                with self.subTest(existing=existing):
                    run, _, urlopen = self.add_repo(method, stem, existing=existing)
                    self.assertEqual(run.commands, [])
                    urlopen.assert_not_called()
                    self.assertEqual(run.summary['skipped'], [name])


class RepositoryTests(unittest.TestCase):
    def git_answers(self, *, branch=0, upstream=0, status='', heads=('a' * 40, 'a' * 40)):
        heads = iter(heads)

        def query(command):
            action = command[3]
            if action == 'symbolic-ref':
                return done(command, branch)
            if action == 'rev-parse' and command[4] == '--abbrev-ref':
                return done(command, upstream)
            if action == 'status':
                return done(command, stdout=status)
            return done(command, stdout=next(heads) + '\n')
        return query

    def update(self, query, *, dry_run=False):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / '.git').mkdir()
        run = FakeBootstrap({}, dry_run=dry_run, root=root)
        with patch.object(run, 'query', side_effect=query), \
                patch.object(bootstrap.os, 'execv') as execv, \
                patch.dict(os.environ, {}, clear=False):
            os.environ.pop(bootstrap.PULLED, None)
            quietly(run.update_repo, ['--tmux-only'])
            pulled = os.environ.get(bootstrap.PULLED)
        return run, execv, pulled

    def test_skips_checkouts_it_must_not_pull(self):
        for answers, reason in (({'branch': 1}, 'detached HEAD'), ({'upstream': 128}, 'no upstream branch'),
                                ({'status': ' M install\n'}, 'local changes')):
            with self.subTest(reason=reason):
                run, execv, _ = self.update(self.git_answers(**answers))
                self.assertEqual(run.commands, [])
                execv.assert_not_called()
                self.assertEqual(run.summary['skipped'], [f'dalftui ({reason})'])

    def test_dry_run_does_not_fetch(self):
        run, _, _ = self.update(self.git_answers(), dry_run=True)
        self.assertEqual(run.commands, [])
        self.assertEqual(run.summary['skipped'], ['dalftui (a dry run does not fetch)'])

    def test_unchanged_head_continues(self):
        run, execv, _ = self.update(self.git_answers())
        self.assertEqual(run.commands, [['git', '-C', str(run.root), 'pull', '--ff-only']])
        execv.assert_not_called()
        self.assertEqual(run.summary['skipped'], ['dalftui (up to date)'])

    def test_changed_head_restarts_with_the_same_arguments(self):
        run, execv, pulled = self.update(self.git_answers(heads=('a' * 40, 'b' * 40)))
        execv.assert_called_once_with(sys.executable, [sys.executable, str(run.root / 'bootstrap'), '--tmux-only'])
        self.assertEqual(pulled, 'aaaaaaa..bbbbbbb')

    def test_restarted_run_reports_the_update_without_pulling_again(self):
        run = FakeBootstrap({})
        with patch.dict(os.environ, {bootstrap.PULLED: 'aaaaaaa..bbbbbbb'}):
            quietly(run.update_repo, [])
            self.assertNotIn(bootstrap.PULLED, os.environ)
        self.assertEqual(run.queries, [])
        self.assertEqual(run.summary['upgraded'], ['dalftui (aaaaaaa..bbbbbbb)'])


class InstallStepTests(unittest.TestCase):
    def install(self, output, *, tmux_only=False, dry_run=False, returncode=0, pending=()):
        run = FakeBootstrap({}, dry_run=dry_run)
        run.summary['installed'].extend(pending)

        def record(command, **_kwargs):
            run.commands.append(command)
            return done(command, returncode if command[1].endswith('install') else 0, output)
        with patch.object(run, 'run', side_effect=record):
            quietly(run.install, tmux_only=tmux_only)
        return run

    def test_passes_tmux_only(self):  # ./install reloads tmux itself.
        run = self.install('Installed (tmux-only): ...\n', tmux_only=True)
        self.assertEqual(run.commands, [[sys.executable, str(ROOT / 'install'), '--tmux-only']])
        self.assertEqual(run.summary['installed'], ['install'])

    def test_desktop_keeps_the_installed_profile_and_reports_no_change(self):
        run = self.install('Already installed; personal overrides preserved.\n')
        self.assertEqual(run.commands[0], [sys.executable, str(ROOT / 'install')])
        self.assertEqual(run.summary['skipped'], ['install'])

    def test_failure_is_reported(self):
        run = self.install('Install failed: tmux missing\n', returncode=1)
        self.assertEqual(len(run.commands), 1)
        self.assertEqual(run.summary['failed'], ['install'])

    def test_dry_run_previews(self):
        run = self.install('Already installed; personal overrides preserved.\n', dry_run=True)
        self.assertEqual(run.commands, [[sys.executable, str(ROOT / 'install'), '--dry-run']])

    def test_dry_run_waits_for_missing_tools(self):
        run = self.install('', dry_run=True, pending=['tmux'])
        self.assertEqual(run.commands, [])
        self.assertEqual(run.summary['skipped'], ['install (would run after the missing tools are installed)'])


class LogAndSummaryTests(unittest.TestCase):
    def test_summary_and_log(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'state/dalftui/bootstrap.log'
            run, _ = quietly(bootstrap.Bootstrap, ROOT, log_path=log)  # Colour depends on the output when created.
            run.add('installed', ['fzf'])
            run.add('skipped', ['git', 'tmux'])
            status, output = quietly(run.report)
            self.assertEqual(status, 0)
            self.assertIn('Installed: 1 (fzf)\nUpgraded: 0\nSkipped: 2 (git, tmux)\nFailed: 0\n', output)
            self.assertIn('Failed: 0', log.read_text(encoding='utf-8'))

    def test_dry_run_writes_no_log(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'state/dalftui/bootstrap.log'
            run, _ = quietly(bootstrap.Bootstrap, ROOT, dry_run=True, log_path=log)
            _, output = quietly(run.report)
            self.assertIn('Would install: 0\nWould upgrade: 0\n', output)
            self.assertFalse(log.parent.exists())

    def test_run_echoes_and_logs_command_output(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'bootstrap.log'
            run = bootstrap.Bootstrap(ROOT, log_path=log)
            result, output = quietly(run.run, [sys.executable, '-c', 'import sys; print("out"); '
                                               'print("err", file=sys.stderr); sys.exit(3)'])
            run.log.close()
            self.assertEqual(result.returncode, 3)
            self.assertIn('out\n', result.stdout)
            self.assertIn('err\n', output)
            self.assertIn('err\n', log.read_text(encoding='utf-8'))

    def test_state_directory_honors_absolute_xdg_state_home(self):
        with patch.dict(os.environ, {'XDG_STATE_HOME': '/state'}):
            self.assertEqual(bootstrap.state_directory(), Path('/state/dalftui'))
        with patch.dict(os.environ, {'XDG_STATE_HOME': 'relative'}):
            self.assertEqual(bootstrap.state_directory(), Path.home() / '.local/state/dalftui')


class Terminal(io.StringIO):
    def isatty(self):
        return True


def step_output(*, dry_run=False, stdout=None, env=(), log_path=None, **added):
    """The output of one step that adds the given summary entries, from a Bootstrap made while it is stdout."""
    stdout = stdout or io.StringIO()
    with patch.dict(os.environ, dict(env)), redirect_stdout(stdout):
        for name in ('NO_COLOR', 'TERM'):
            if name not in dict(env):
                os.environ.pop(name, None)
        run = bootstrap.Bootstrap(ROOT, dry_run=dry_run, log_path=log_path)
        with run.step('Packages'):
            for category, names in added.items():
                run.add(category, names)
    if run.log:
        run.log.close()
    stdout.flush()
    return stdout.getvalue() if isinstance(stdout, io.StringIO) else stdout.buffer.getvalue().decode('cp1252')


class StepOutputTests(unittest.TestCase):
    def test_heading_then_one_line_per_kind_of_result(self):
        output = step_output(installed=['fzf', 'git'], upgraded=['uv (0.12.21 -> 0.12.23)'],
                             skipped=['bat', 'tmux', 'dalftui (local changes)'], failed=['code (sudo)', 'dvc'])
        self.assertEqual(output, '\n▶ Packages\n  ✓ fzf, git installed\n  ✓ uv upgraded (0.12.21 -> 0.12.23)\n'
                                 '  · 2 up to date\n  · dalftui (local changes)\n  ✗ dvc failed\n'
                                 '  ✗ code failed (sudo)\n')

    def test_single_skipped_entry_and_empty_step(self):
        self.assertEqual(step_output(skipped=['tmux']), '\n▶ Packages\n  · tmux up to date\n')
        self.assertEqual(step_output(), '\n▶ Packages\n  · up to date\n')

    def test_dry_run_wording(self):
        self.assertEqual(step_output(dry_run=True, installed=['fzf'], upgraded=['git', 'tmux']),
                         '\n▶ Packages\n  ✓ would install fzf\n  ✓ would upgrade git, tmux\n')

    def test_configuration_step_wording(self):
        self.assertEqual(step_output(installed=['install']), '\n▶ Packages\n  ✓ install ran\n')
        self.assertEqual(step_output(dry_run=True, installed=['install']), '\n▶ Packages\n  ✓ would run install\n')

    def test_colour_only_on_a_terminal_without_no_color_or_dumb_term(self):
        added = {'installed': ['fzf'], 'skipped': ['git'], 'failed': ['dvc']}
        output = step_output(stdout=Terminal(), **added)
        self.assertEqual(output, '\n\033[1;36m▶ Packages\033[0m\n\033[32m  ✓ fzf installed\033[0m\n'
                                 '\033[2m  · git up to date\033[0m\n\033[31m  ✗ dvc failed\033[0m\n')
        for env in ({'NO_COLOR': '1'}, {'TERM': 'dumb'}):
            with self.subTest(env=env):
                self.assertNotIn('\033', step_output(stdout=Terminal(), env=env, **added))
        self.assertNotIn('\033', step_output(**added))

    def test_summary_is_a_heading_with_counts_coloured_only_when_they_matter(self):
        def report(stdout, **added):
            with redirect_stdout(stdout), patch.dict(os.environ, {'TERM': 'xterm'}):
                os.environ.pop('NO_COLOR', None)
                run = bootstrap.Bootstrap(ROOT, dry_run=added.pop('dry_run', False))  # Colour is decided here.
                for category, names in added.items():
                    run.add(category, names)
                status = run.report()
            return status, stdout.getvalue()
        status, output = report(Terminal(), installed=['fzf'], skipped=['git'], failed=['dvc'])
        self.assertEqual((status, output), (1, '\n\033[1;36m▶ Summary\033[0m\n\033[32mInstalled: 1 (fzf)\033[0m\n'
                                                'Upgraded: 0\n\033[2mSkipped: 1 (git)\033[0m\n\033[31mFailed: 1 (dvc)\033[0m\n'))
        # Without a terminal, the lines CI checks are plain.
        self.assertEqual(report(io.StringIO(), dry_run=True)[1], '\n▶ Summary (dry run: nothing was changed)\n'
                                                                  'Would install: 0\nWould upgrade: 0\nSkipped: 0\nFailed: 0\n')

    def test_log_has_no_escapes(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'bootstrap.log'
            self.assertIn('\033[', step_output(stdout=Terminal(), log_path=log, installed=['fzf']))
            self.assertEqual(log.read_text(encoding='utf-8'), '\n▶ Packages\n  ✓ fzf installed\n')

    def test_command_echo_is_dim(self):
        with redirect_stdout(Terminal()) as output, patch.dict(os.environ, {'TERM': 'xterm'}):
            os.environ.pop('NO_COLOR', None)
            bootstrap.Bootstrap(ROOT).run([sys.executable, '-c', 'print("out")'])
        self.assertTrue(output.getvalue().startswith(f'\033[2m$ {sys.executable} -c \'print("out")\'\033[0m\nout\n'))

    def test_plain_symbols_when_the_console_cannot_encode_them(self):
        stdout = io.TextIOWrapper(io.BytesIO(), encoding='cp1252')
        self.assertEqual(step_output(stdout=stdout, installed=['fzf'], skipped=['git'], failed=['dvc']),
                         '\n> Packages\n  + fzf installed\n  - git up to date\n  x dvc failed\n')


if __name__ == '__main__':
    unittest.main()
