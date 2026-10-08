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
SYSTEM32 = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32'
OPENSSH = SYSTEM32 / 'OpenSSH/ssh.exe'
# Win32-OpenSSH's MSI (winget Microsoft.OpenSSH.Preview), which may replace the built-in client.
OPENSSH_MSI = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'OpenSSH/ssh.exe'
OPENSSH_ADD = 'Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0'
AGENT_RUNNING = (2, 4)  # sc.exe START_TYPE AUTO_START, STATE RUNNING.
AGENT_ENABLE = 'Set-Service ssh-agent -StartupType Automatic; Start-Service ssh-agent'
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


def openssh_client():
    """The Windows OpenSSH client dssh runs: the built-in one first, as in dalftui.windows.ssh."""
    return next((path for path in (OPENSSH, OPENSSH_MSI) if path.is_file()), None)


def interactive():
    """Whether this session has a desktop that can show a UAC prompt, as .NET's Environment.UserInteractive."""
    try:  # Windows-only windll loader is unavailable to Pylint running on Linux.
        user32 = ctypes.windll.user32  # pylint: disable=no-member
        user32.GetProcessWindowStation.restype = ctypes.c_void_p
        flags = (ctypes.c_ulong * 3)()  # USEROBJECTFLAGS: fInherit, fReserved, dwFlags.
        if not user32.GetUserObjectInformationW(ctypes.c_void_p(user32.GetProcessWindowStation()), 1, flags,
                                                ctypes.sizeof(flags), None):
            return False
        return bool(flags[2] & 1)  # WSF_VISIBLE
    except (AttributeError, OSError):
        return False


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

    def agent_state(self):
        """The ssh-agent service's start type and state numbers, or None when this session cannot see it."""
        start = re.search(r'START_TYPE\s*:\s*(\d+)', self.query([str(SYSTEM32 / 'sc.exe'), 'qc', 'ssh-agent']).stdout)
        state = re.search(r'\bSTATE\s*:\s*(\d+)', self.query([str(SYSTEM32 / 'sc.exe'), 'query', 'ssh-agent']).stdout)
        return (int(start[1]), int(state[1])) if start and state else None

    def system(self, names):
        """Install the VC++ runtime, add the OpenSSH client and start its agent at boot, through one UAC prompt."""
        steps = [step for step in [self.vc_runtime(names)] if step]
        client = openssh_client()
        state = self.agent_state() if client else None
        if client and state is None and not interactive():  # An SSH or batch logon cannot see the service.
            self.add('skipped', [f'ssh-agent service (not visible without a desktop session; as administrator: '
                                 f'{AGENT_ENABLE})'])
        elif state != AGENT_RUNNING:
            if not client:
                steps.append(('OpenSSH client', OPENSSH_ADD, lambda: openssh_client() is not None))
            steps.append(('ssh-agent service', AGENT_ENABLE, lambda: self.agent_state() == AGENT_RUNNING))
        if steps:
            self.administrator(steps)
        client = openssh_client()
        if not client:
            return
        result = self.query([str(client), '-V'])
        match = re.search(r'OpenSSH\D*(\d+)\.(\d+)', result.stdout + result.stderr)
        if match and (int(match[1]), int(match[2])) < (9, 4):
            self.add('skipped', [f'OpenSSH client {match[1]}.{match[2]} (Tag dalftui needs 9.4+)'])

    def administrator(self, steps):
        """Run (label, PowerShell command, check) steps elevated with gsudo, or report the commands to run."""
        manual = f"as administrator: {'; '.join(command for _, command, _ in steps)}"
        gsudo = self.app('gsudo') / 'gsudo.exe'  # Scoop shims gsudo only as sudo.
        if self.dry_run:
            self.add('installed', [f'{label} (administrator)' for label, _, _ in steps])
        elif not gsudo.is_file() or not interactive():
            why = 'no desktop for the UAC prompt' if gsudo.is_file() else 'gsudo is not installed'
            for label, _, _ in steps:  # The agent is a convenience; dalftui and Scoop's tools need the rest.
                self.add('skipped' if label == 'ssh-agent service' else 'failed', [f'{label} ({why}; {manual})'])
        else:
            self.say(f"Administrator steps for the {' and '.join(label for label, _, _ in steps)}: "
                     'approve the Windows prompt (UAC).\n')
            self.run([str(gsudo), 'powershell.exe', '-NoProfile', '-Command',
                      "$ErrorActionPreference = 'Stop'; " + '; '.join(command for _, command, _ in steps)])
            for label, _, check in steps:
                if check():
                    self.add('installed', [label])
                else:
                    self.add('failed', [f'{label} ({manual})'])

    def vc_runtime(self, names):
        """The administrator step for the VC++ runtime that bat and mise need, or None when it is present.

        Scoop records vcredist2022 as installed even when its elevated installers could not start, so this
        runs the installer Scoop downloaded."""
        installer = self.app('extras/vcredist2022') / 'vc_redist.x64.exe'
        if 'extras/vcredist2022' not in names or VCRUNTIME.is_file() or not (installer.is_file() or self.dry_run):
            return None
        path = str(installer).replace("'", "''")
        return ('VC++ runtime', f"Start-Process -Wait '{path}' '/install /quiet /norestart'", VCRUNTIME.is_file)

    def git_ssh(self):
        """Scoop's git runs its bundled ssh, which cannot reach the Windows ssh-agent."""
        client, git = openssh_client(), self.scoop / 'shims/git.exe'
        if not client or not git.is_file():
            return
        value = client.as_posix()
        value = f"'{value}'" if ' ' in value else value
        current = self.query([str(git), 'config', '--global', 'core.sshCommand']).stdout.strip()
        if current.strip('\'"').replace('\\', '/').casefold() == client.as_posix().casefold():  # C:\WINDOWS or C:/Windows
            return
        if current:
            self.add('skipped', [f'Git core.sshCommand (kept: {current})'])
        elif self.dry_run:
            self.add('installed', ['Git core.sshCommand'])
        else:
            result = self.run([str(git), 'config', '--global', 'core.sshCommand', value])
            self.add('failed' if result.returncode else 'installed', ['Git core.sshCommand'])

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
    run.system(names)
    run.git_ssh()
    run.terminal()
    run.install_cmd()
    return run.report()
