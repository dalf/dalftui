"""Install the Scoop apps of a new Windows machine, then install dalftui. Safe to rerun."""
import ctypes
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shlex
import sys

from dalftui.linux.bootstrap import PACKAGES, REPO, Bootstrap, read_packages
from dalftui.windows.terminal_settings import settings_paths

SCOOP_SCRIPT = Path('apps/scoop/current/bin/scoop.ps1')
FIRST_STEP = ('Set-ExecutionPolicy -Scope CurrentUser RemoteSigned; irm get.scoop.sh | iex; '
              'scoop install git uv')
OPENSSH = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/OpenSSH/ssh.exe'
OPENSSH_ADD = 'Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0'
VCRUNTIME = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/vcruntime140.dll'


def scoop_root():
    return Path(os.environ.get('SCOOP') or Path.home() / 'scoop')


def state_directory():
    local = os.environ.get('LOCALAPPDATA')
    return (Path(local) if local else Path.home() / 'AppData/Local') / 'dalftui'


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}


def elevated():
    try:  # Windows-only windll loader is unavailable to Pylint running on Linux.
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # pylint: disable=no-member
    except (AttributeError, OSError):
        return False


class Scoop(Bootstrap):
    def __init__(self, root=REPO, *, scoop=None, **kwargs):
        super().__init__(root, **kwargs)
        self.scoop = Path(scoop or scoop_root())
        # Windows PowerShell, not scoop.cmd: that runs pwsh when present, and Scoop cannot update the pwsh it runs in.
        self.command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                        '-File', str(self.scoop / SCOOP_SCRIPT)]

    def app(self, name):
        return self.scoop / 'apps' / name.rpartition('/')[2] / 'current'

    def current(self, name, kind):
        """The installed app's manifest or install record; Scoop 0.6 prefixes their names with scoop-."""
        return read_json(self.app(name) / f'scoop-{kind}.json') or read_json(self.app(name) / f'{kind}.json')

    def installed_versions(self, packages):
        versions = {name: self.current(name, 'manifest').get('version') for name in packages}
        return {name: version for name, version in versions.items() if version}

    def latest(self, name):
        """The bucket's version as of the last scoop update; None for a held app or one installed as APP@VERSION."""
        record = self.current(name, 'install')
        if record.get('hold') or record.get('url'):
            return None
        bucket, _, app = name.rpartition('/')
        return read_json(self.scoop / 'buckets' / (bucket or 'main') / 'bucket' / f'{app}.json').get('version')

    def buckets(self, names):
        for bucket in dict.fromkeys(name.split('/')[0] for name in names if '/' in name):
            label, path = f'{bucket} bucket', self.scoop / 'buckets' / bucket
            if path.is_dir():
                self.add('skipped', [label])
            elif self.dry_run:
                self.add('installed', [label])
            else:
                self.run(self.command + ['bucket', 'add', bucket])
                self.add('installed' if path.is_dir() else 'failed', [label])

    def packages(self, names):
        """Install missing apps one by one and update the outdated listed ones; versions decide the outcome."""
        # scoop update exits 0 for some failures, such as an app that a running process keeps in use.
        if not self.dry_run and self.run(self.command + ['update']).returncode:
            self.add('failed', ['scoop update'])
        before = self.installed_versions(names)
        missing = [name for name in names if name not in before]
        present = [name for name in names if name in before]
        outdated = [name for name in present if self.latest(name) not in (None, before[name])]
        if self.dry_run:  # Compared with the buckets as of the last scoop update.
            self.add('installed', missing)
            self.add('upgraded', outdated)
            self.add('skipped', [name for name in present if name not in outdated])
            return
        for name in missing:
            self.run(self.command + ['install', name])
        output = {name: self.run(self.command + ['update', name.rpartition('/')[2]]).stdout for name in outdated}
        after = self.installed_versions(names)
        for name in names:
            if name not in after:
                self.add('failed', [name])
            elif name in missing:
                self.add('installed', [name])
            elif after[name] != before[name]:
                self.add('upgraded', [name])
            elif 'Running process detected' in output.get(name, ''):  # Such as the uv running bootstrap.
                self.add('skipped', [f'{name} (in use; close it, then run scoop update {name.rpartition("/")[2]})'])
            else:
                self.add('failed' if name in outdated else 'skipped', [name])

    def openssh(self):
        if not OPENSSH.is_file():
            self.add('failed', [f'OpenSSH client (missing; as administrator: {OPENSSH_ADD})'])
            return
        result = self.query([str(OPENSSH), '-V'])
        match = re.search(r'OpenSSH\D*(\d+)\.(\d+)', result.stdout + result.stderr)
        if match and (int(match[1]), int(match[2])) < (9, 4):
            self.add('skipped', [f'OpenSSH client {match[1]}.{match[2]} (Tag dalftui needs 9.4+)'])

    def vc_runtime(self, names):
        """Scoop records vcredist2022 as installed even when its elevated installers could not start."""
        if 'extras/vcredist2022' in names and not self.dry_run and not VCRUNTIME.is_file():
            self.add('failed', ['VC++ runtime (missing; in a desktop PowerShell: '
                                'scoop uninstall vcredist2022; scoop install extras/vcredist2022)'])

    def terminal(self):
        if not settings_paths(os.environ.get('LOCALAPPDATA', '')):
            self.add('skipped', ['Windows Terminal (not found; install it from the Microsoft Store and open it once)'])

    def install_cmd(self):
        if self.dry_run:  # install.ps1 has no dry run.
            self.add('skipped', ['install.cmd (not run in a dry run)'])
            return
        result = self.run([str(self.root / 'install.cmd')])
        if result.returncode:
            self.add('failed', ['install'])
            return
        self.add('installed' if 'PowerShell profile configured:' in result.stdout else 'skipped', ['install'])


def bootstrap(*, dry_run=False, tmux_only=False, argv=()):
    if tmux_only:
        print('Bootstrap failed: --tmux-only is Linux-only.', file=sys.stderr)
        return 1
    if elevated():  # Scoop installs per user and refuses an administrator.
        print('Bootstrap failed: run bootstrap from a non-elevated PowerShell; Scoop installs per user.',
              file=sys.stderr)
        return 1
    if not (scoop_root() / SCOOP_SCRIPT).is_file():
        print(f'Bootstrap failed: install Scoop first, in a non-elevated PowerShell: {FIRST_STEP}', file=sys.stderr)
        return 1
    # Scoop runs in Windows PowerShell, which cannot load its modules with the PSModulePath of a parent pwsh.
    os.environ.pop('PSModulePath', None)
    # Command output decoded with the ANSI code page must not stop the run when shown.
    sys.stdout.reconfigure(errors='replace')
    run = Scoop(dry_run=dry_run, log_path=state_directory() / 'bootstrap.log')
    run.say(f"\n== dalftui bootstrap {datetime.now().isoformat(timespec='seconds')}"
            f" {shlex.join(['bootstrap', *argv])} ==\n")
    run.update_repo(list(argv))
    names = read_packages(PACKAGES / 'windows.txt')
    run.buckets(names)
    run.packages(names)
    run.vc_runtime(names)
    run.openssh()
    run.terminal()
    run.install_cmd()
    return run.report()
