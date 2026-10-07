"""Install the packages and tools of a new Fedora machine, then install dalftui. Safe to rerun."""
from datetime import datetime
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import threading

REPO = Path(__file__).resolve().parents[2]
PACKAGES = REPO / 'packages/fedora.txt'
OH_MY_POSH_INSTALLER = 'https://ohmyposh.dev/install.sh'
MISE_INSTALLER = 'https://mise.run'
# Microsoft's documented Fedora setup: https://code.visualstudio.com/docs/setup/linux
VSCODE_KEY = 'https://packages.microsoft.com/keys/microsoft.asc'
VSCODE_REPO = Path('/etc/yum.repos.d/vscode.repo')
VSCODE_REPO_TEXT = ('[code]\nname=Visual Studio Code\nbaseurl=https://packages.microsoft.com/yumrepos/vscode\n'
                    f'enabled=1\nautorefresh=1\ntype=rpm-md\ngpgcheck=1\ngpgkey={VSCODE_KEY}\n')
PULLED = 'DALFTUI_BOOTSTRAP_PULLED'  # Set before restarting with updated code; stops a loop.


def read_packages(path, *, tmux_only=False):
    """One package per line, # comments; lines after [desktop] are skipped with --tmux-only."""
    packages = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        line = line.split('#', 1)[0].strip()
        if line == '[desktop]':
            if tmux_only:
                break
        elif line.startswith('['):
            raise ValueError(f'Unknown section in {path}: {line}')
        elif line:
            packages.append(line)
    return packages


def state_directory():
    state = os.environ.get('XDG_STATE_HOME')
    return (Path(state) if state and Path(state).is_absolute() else Path.home() / '.local/state') / 'dalftui'


class Bootstrap:
    def __init__(self, root=REPO, *, dry_run=False, log_path=None):
        self.root = Path(root)
        self.dry_run = dry_run
        self.log = None
        if log_path and not dry_run:  # A dry run writes nothing, not even the log.
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self.log = log_path.open('a', encoding='utf-8')
        self.summary = {'installed': [], 'upgraded': [], 'skipped': [], 'failed': []}
        self.sudo_ready = None

    def say(self, text):
        print(text, end='', flush=True)
        if self.log:
            self.log.write(text)
            self.log.flush()

    def add(self, category, names):
        self.summary[category].extend(names)

    def query(self, command):
        """Read-only command; its output is parsed, not shown."""
        return subprocess.run(command, capture_output=True, text=True, errors='replace', check=False)

    def run(self, command, *, log_output=True):
        """Run a command, showing its output and appending it to the log."""
        self.say(f'$ {shlex.join(command)}\n')
        if not log_output:  # Progress bars stay on the terminal only.
            return subprocess.run(command, stdin=subprocess.DEVNULL, check=False)
        output = []
        with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, errors='replace') as process:
            for line in process.stdout:
                output.append(line)
                self.say(line)
        return subprocess.CompletedProcess(command, process.returncode, ''.join(output))

    def sudo(self):
        """Ask for the password once and keep the credentials fresh until exit."""
        if self.sudo_ready is None:
            self.say('$ sudo -v\n')
            self.sudo_ready = subprocess.run(['sudo', '-v'], check=False).returncode == 0
            if self.sudo_ready:
                threading.Thread(target=keep_sudo, daemon=True).start()
        return self.sudo_ready

    def update_repo(self, argv):
        pulled = os.environ.pop(PULLED, None)
        if pulled:
            self.add('upgraded', [f'dalftui ({pulled})'])
            return

        def git(*args):
            return self.query(['git', '-C', str(self.root), *args])
        if not (self.root / '.git').exists():
            reason = 'not a git checkout'
        elif git('symbolic-ref', '-q', 'HEAD').returncode:
            reason = 'detached HEAD'
        elif git('rev-parse', '--abbrev-ref', '@{upstream}').returncode:
            reason = 'no upstream branch'
        elif git('status', '--porcelain', '--untracked-files=no').stdout.strip():
            reason = 'local changes'
        elif self.dry_run:
            reason = 'a dry run does not fetch'
        else:
            before = git('rev-parse', 'HEAD').stdout.strip()
            if self.run(['git', '-C', str(self.root), 'pull', '--ff-only']).returncode:
                self.add('failed', ['dalftui (git pull --ff-only)'])
                return
            after = git('rev-parse', 'HEAD').stdout.strip()
            if after == before:
                reason = 'up to date'
            else:  # Restart so the new code and package list apply.
                self.say(f'dalftui updated {before[:7]}..{after[:7]}; restarting.\n')
                if self.log:
                    self.log.close()
                os.environ[PULLED] = f'{before[:7]}..{after[:7]}'
                os.execv(sys.executable, [sys.executable, str(self.root / 'bootstrap'), *argv])
                return  # Reached only when execv is mocked.
        self.add('skipped', [f'dalftui ({reason})'])

    def installed_versions(self, packages):
        result = self.query(['rpm', '-q', '--qf', '%{NAME} %{EVR}\n', *packages])
        versions = {}
        for line in result.stdout.splitlines():
            name, _, evr = line.partition(' ')
            if name in packages and evr:
                versions[name] = evr
        return versions

    def packages(self, names):
        """Install missing packages one by one and upgrade the listed installed ones."""
        before = self.installed_versions(names)
        missing = [name for name in names if name not in before]
        present = [name for name in names if name in before]
        if self.dry_run:
            result = self.query(['dnf', 'repoquery', '-q', '--upgrades', '--qf', '%{name}\n', *present])
            if present and result.returncode:
                self.add('failed', ['upgrade check (dnf repoquery)'])
            upgrades = set(result.stdout.split())
            self.add('installed', missing)
            self.add('upgraded', [name for name in present if name in upgrades])
            self.add('skipped', [name for name in present if name not in upgrades])
            return
        if not self.sudo():
            self.add('failed', [f'{name} (sudo)' for name in names])
            return
        for name in missing:
            self.run(['sudo', 'dnf', 'install', '-y', name])
        failed = set()
        if present and self.run(['sudo', 'dnf', 'upgrade', '-y', *present]).returncode:
            failed = {name for name in present
                      if self.run(['sudo', 'dnf', 'upgrade', '-y', name]).returncode}
        after = self.installed_versions(names)
        for name in names:
            if name in failed or name not in after:
                self.add('failed', [name])
            elif name in missing:
                self.add('installed', [name])
            else:
                self.add('upgraded' if after[name] != before[name] else 'skipped', [name])

    def vscode_repo(self):
        """Add Microsoft's VS Code repository once, so dnf installs and upgrades the code package."""
        if VSCODE_REPO.exists():
            self.add('skipped', ['VS Code repository'])
            return
        if self.dry_run:
            self.add('installed', ['VS Code repository'])
            return
        if not self.sudo():
            self.add('failed', ['VS Code repository (sudo)'])
            return
        failed = self.run(['sudo', 'rpm', '--import', VSCODE_KEY]).returncode or self.run(
            ['sudo', 'sh', '-c', f'printf %s {shlex.quote(VSCODE_REPO_TEXT)} > {VSCODE_REPO}']).returncode
        self.add('failed' if failed else 'installed', ['VS Code repository'])

    def oh_my_posh(self):
        directory = shlex.quote(str(Path.home() / '.local/bin'))
        self.user_tool('oh-my-posh', f'curl -fsSL {OH_MY_POSH_INSTALLER} | bash -s -- -d {directory}', ['upgrade'])

    def mise(self):
        self.user_tool('mise', f'curl -fsSL {MISE_INSTALLER} | sh', ['self-update', '--yes', '--no-plugins'])

    def user_tool(self, name, installer, upgrade):
        """Official installer into ~/.local/bin; the tool's own upgrade command afterwards."""
        path = shutil.which(name)
        if not path:
            if self.dry_run:
                self.add('installed', [name])
                return
            (Path.home() / '.local/bin').mkdir(parents=True, exist_ok=True)
            result = self.run(['bash', '-c', f'set -o pipefail; {installer}'])
            self.add('installed' if not result.returncode and shutil.which(name) else 'failed', [name])
            return
        if not os.access(path, os.W_OK):
            self.add('skipped', [f'{name} (not writable: {path})'])
            return
        if self.dry_run:
            self.add('skipped', [f'{name} (a dry run does not check for upgrades)'])
            return
        before = self.query([path, '--version']).stdout.strip()
        if self.run([path, *upgrade], log_output=False).returncode:
            self.add('failed', [f'{name} (upgrade)'])
            return
        after = self.query([path, '--version']).stdout.strip()
        if after == before:
            self.add('skipped', [name])
        else:
            self.say(f'{name} {before} -> {after}\n')
            self.add('upgraded', [f'{name} ({before} -> {after})'])

    def install(self, *, tmux_only):
        command = [sys.executable, str(self.root / 'install')] + (['--tmux-only'] if tmux_only else [])
        if self.dry_run:
            if self.summary['installed']:
                self.add('skipped', ['install (would run after the missing tools are installed)'])
                return
            command.append('--dry-run')
        result = self.run(command)
        if result.returncode:
            self.add('failed', ['install'])
            return
        self.add('skipped' if 'Already installed' in result.stdout else 'installed', ['install'])
        if not self.dry_run and self.run([sys.executable, str(self.root / 'bin/reload')]).returncode:
            self.add('failed', ['reload'])

    def report(self):
        labels = (('installed', 'Would install' if self.dry_run else 'Installed'),
                  ('upgraded', 'Would upgrade' if self.dry_run else 'Upgraded'),
                  ('skipped', 'Skipped'), ('failed', 'Failed'))
        lines = ['', 'Dry run: nothing was changed.' if self.dry_run else 'Bootstrap summary:']
        for key, label in labels:
            names = self.summary[key]
            lines.append(f'{label}: {len(names)}' + (f" ({', '.join(names)})" if names else ''))
        self.say('\n'.join(lines) + '\n')
        if self.log:
            self.say(f'Log: {self.log.name}\n')
            self.log.close()
        return 1 if self.summary['failed'] else 0


def keep_sudo():
    while not threading.Event().wait(60):
        subprocess.run(['sudo', '-n', '-v'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False)


def bootstrap(*, dry_run=False, tmux_only=False, argv=()):
    if os.geteuid() == 0:  # Packages need root, but the configuration belongs to the user.
        print('Bootstrap failed: run ./bootstrap as your user; it asks for sudo itself.', file=sys.stderr)
        return 1
    if not all(shutil.which(command) for command in ('rpm', 'dnf', 'sudo')):
        print('Bootstrap failed: this needs Fedora with rpm, dnf and sudo.', file=sys.stderr)
        return 1
    # The official oh-my-posh and mise installers write to ~/.local/bin; install must find it there.
    local_bin = str(Path.home() / '.local/bin')
    if local_bin not in os.environ.get('PATH', '').split(os.pathsep):
        os.environ['PATH'] = local_bin + os.pathsep + os.environ.get('PATH', '')
    run = Bootstrap(dry_run=dry_run, log_path=state_directory() / 'bootstrap.log')
    run.say(f"\n== dalftui bootstrap {datetime.now().isoformat(timespec='seconds')}"
            f" {shlex.join(['bootstrap', *argv])} ==\n")
    run.update_repo(list(argv))
    if not tmux_only:
        run.vscode_repo()
    run.packages(read_packages(PACKAGES, tmux_only=tmux_only))
    run.oh_my_posh()
    run.mise()
    run.install(tmux_only=tmux_only)
    return run.report()
