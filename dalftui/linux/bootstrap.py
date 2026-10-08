"""Install the packages and tools of a new Fedora, Debian, Ubuntu or macOS machine, then install dalftui. Safe to rerun."""
from datetime import datetime
import json
import os
import platform
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import threading
import urllib.request

REPO = Path(__file__).resolve().parents[2]
PACKAGES = REPO / 'packages'
OH_MY_POSH_INSTALLER = 'https://ohmyposh.dev/install.sh'
MISE_INSTALLER = 'https://mise.run'
UV_INSTALLER = 'https://astral.sh/uv/install.sh'
# sudo drops DEBIAN_FRONTEND; stdin is closed, so conffile prompts must not be asked.
APT = ['sudo', 'env', 'DEBIAN_FRONTEND=noninteractive', 'apt-get', '-y', '-o', 'DPkg::Lock::Timeout=300',
       '-o', 'Dpkg::Options::=--force-confdef', '-o', 'Dpkg::Options::=--force-confold']
# Microsoft's documented Fedora and Debian setup: https://code.visualstudio.com/docs/setup/linux
VSCODE_KEY = 'https://packages.microsoft.com/keys/microsoft.asc'
VSCODE_REPO = Path('/etc/yum.repos.d/vscode.repo')
VSCODE_REPO_TEXT = ('[code]\nname=Visual Studio Code\nbaseurl=https://packages.microsoft.com/yumrepos/vscode\n'
                    f'enabled=1\nautorefresh=1\ntype=rpm-md\ngpgcheck=1\ngpgkey={VSCODE_KEY}\n')
VSCODE_KEYRING = Path('/usr/share/keyrings/microsoft.asc')
VSCODE_SOURCES = Path('/etc/apt/sources.list.d/vscode.sources')
VSCODE_SOURCES_TEXT = ('Types: deb\nURIs: https://packages.microsoft.com/repos/code\nSuites: stable\nComponents: main\n'
                       f'Architectures: amd64,arm64,armhf\nSigned-By: {VSCODE_KEYRING}\n')
BREWFILE = PACKAGES / 'Brewfile'
BREW_PATHS = ('/opt/homebrew/bin/brew', '/usr/local/bin/brew')  # Apple Silicon, Intel
BREW_INSTALLER = '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
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


def family():
    """'fedora' or 'debian' (Debian and Ubuntu) from /etc/os-release; None otherwise."""
    try:
        release = platform.freedesktop_os_release()
    except OSError:
        return None
    ids = f"{release.get('ID', '')} {release.get('ID_LIKE', '')}".split()
    if 'fedora' in ids:
        return 'fedora'
    if 'debian' in ids or 'ubuntu' in ids:
        return 'debian'
    return None


def state_directory():
    state = os.environ.get('XDG_STATE_HOME')
    return (Path(state) if state and Path(state).is_absolute() else Path.home() / '.local/state') / 'dalftui'


class Bootstrap:
    def __init__(self, root=REPO, *, dry_run=False, log_path=None, apt=False):
        self.root = Path(root)
        self.apt = apt
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
                command = [sys.executable, str(self.root / 'bootstrap'), *argv]
                if os.name == 'nt':  # execv returns to the console before the new process ends.
                    raise SystemExit(subprocess.run(command, check=False).returncode)
                os.execv(sys.executable, command)
                return  # Reached only when execv is mocked.
        self.add('skipped', [f'dalftui ({reason})'])

    def installed_versions(self, packages):
        if self.apt:  # Rows other than 'ii', such as removed packages with configuration left, count as missing.
            result = self.query(['dpkg-query', '-W', '-f=${Package} ${db:Status-Abbrev} ${Version}\n', *packages])
            rows = (line.split() for line in result.stdout.splitlines())
            return {row[0]: row[2] for row in rows if len(row) == 3 and row[1] == 'ii' and row[0] in packages}
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
            if self.apt:  # Simulated without root, from the lists of the last apt-get update.
                check = 'apt-get -s'
                result = self.query(['apt-get', '-s', 'install', '--only-upgrade', *present])
                upgrades = {line.split()[1] for line in result.stdout.splitlines() if line.startswith('Inst ')}
            else:
                check = 'dnf repoquery'
                result = self.query(['dnf', 'repoquery', '-q', '--upgrades', '--qf', '%{name}\n', *present])
                upgrades = set(result.stdout.split())
            if present and result.returncode:
                self.add('failed', [f'upgrade check ({check})'])
            self.add('installed', missing)
            self.add('upgraded', [name for name in present if name in upgrades])
            self.add('skipped', [name for name in present if name not in upgrades])
            return
        if not self.sudo():
            self.add('failed', [f'{name} (sudo)' for name in names])
            return
        install, upgrade = ['sudo', 'dnf', 'install', '-y'], ['sudo', 'dnf', 'upgrade', '-y']
        if self.apt:
            install, upgrade = APT + ['install'], APT + ['install', '--only-upgrade']
            if self.run(APT + ['update']).returncode:
                self.add('failed', ['apt-get update'])
        locked = False

        def run(command):  # Once apt has waited out the dpkg lock, the next commands would each wait again.
            nonlocal locked
            if locked:
                return 1
            result = self.run(command)
            locked = self.apt and 'Unable to acquire the dpkg frontend lock' in result.stdout
            return result.returncode
        for name in missing:
            run(install + [name])
        failed = set()
        if present and run(upgrade + present):
            failed = {name for name in present if run(upgrade + [name])}
        after = self.installed_versions(names)
        for name in names:
            if name in failed or name not in after:
                self.add('failed', [name])
            elif name in missing:
                self.add('installed', [name])
            else:
                self.add('upgraded' if after[name] != before[name] else 'skipped', [name])

    def vscode_repo(self):
        """Add Microsoft's VS Code repository once, so dnf or apt installs and upgrades the code package."""
        # vscode.list: an older apt setup; a second source with another Signed-By makes apt fail.
        existing = (VSCODE_SOURCES, VSCODE_SOURCES.with_suffix('.list')) if self.apt else (VSCODE_REPO,)
        if any(path.exists() for path in existing):
            self.add('skipped', ['VS Code repository'])
            return
        if self.dry_run:
            self.add('installed', ['VS Code repository'])
            return
        if not self.sudo():
            self.add('failed', ['VS Code repository (sudo)'])
            return

        def write(path, text):
            return self.run(['sudo', 'sh', '-c', f'printf %s {shlex.quote(text)} > {path}']).returncode
        if self.apt:  # Fetched in Python: a minimal Debian has no curl yet.
            try:
                with urllib.request.urlopen(VSCODE_KEY, timeout=60) as response:
                    key = response.read().decode('ascii')
            except (OSError, ValueError) as error:
                self.say(f'VS Code key: {error}\n')
                key = None
            failed = not key or write(VSCODE_KEYRING, key) or write(VSCODE_SOURCES, VSCODE_SOURCES_TEXT)
        else:
            failed = self.run(['sudo', 'rpm', '--import', VSCODE_KEY]).returncode or write(VSCODE_REPO, VSCODE_REPO_TEXT)
        self.add('failed' if failed else 'installed', ['VS Code repository'])

    def oh_my_posh(self):
        directory = shlex.quote(str(Path.home() / '.local/bin'))
        self.user_tool('oh-my-posh', f'curl -fsSL {OH_MY_POSH_INSTALLER} | bash -s -- -d {directory}', ['upgrade'])

    def mise(self):
        self.user_tool('mise', f'curl -fsSL {MISE_INSTALLER} | sh', ['self-update', '--yes', '--no-plugins'])

    def uv(self):
        self.user_tool('uv', f'curl -fsSL {UV_INSTALLER} | sh', ['self', 'update'])

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


class Brew(Bootstrap):
    def __init__(self, root=REPO, *, brew='brew', **kwargs):
        super().__init__(root, **kwargs)
        self.brew = brew

    def entries(self):
        """The Brewfile's formulae, then its casks."""
        return [name for kind in ('--formula', '--cask')
                for name in self.query([self.brew, 'bundle', 'list', kind, '--file', str(BREWFILE)]).stdout.split()]

    def installed_versions(self, packages):
        versions = {}
        for kind in ([], ['--cask']):
            for line in self.query([self.brew, 'list', *kind, '--versions']).stdout.splitlines():
                name, _, installed = line.partition(' ')
                if name in packages and installed:
                    versions[name] = installed
        return versions

    def outdated(self, names):
        """Listed entries that brew bundle would upgrade, as of the last brew update; it exits 1 when there are any."""
        try:
            data = json.loads(self.query([self.brew, 'outdated', '--json=v2']).stdout)
        except ValueError:
            self.add('failed', ['upgrade check (brew outdated)'])
            return set()
        return {item['name'] for kind in ('formulae', 'casks') for item in data.get(kind, [])
                if item['name'] in names and not item.get('pinned')}

    def packages(self, names):
        """Install the missing entries and upgrade the outdated ones with one brew bundle; versions decide the outcome."""
        if not self.dry_run and self.run([self.brew, 'update']).returncode:
            self.add('failed', ['brew update'])
        before = self.installed_versions(names)
        outdated = self.outdated(names)
        missing = [name for name in names if name not in before]
        if self.dry_run:
            self.add('installed', missing)
            self.add('upgraded', [name for name in names if name in outdated])
            self.add('skipped', [name for name in names if name in before and name not in outdated])
            return
        self.run([self.brew, 'bundle', '--file', str(BREWFILE)])  # Other formulae are not upgraded.
        after = self.installed_versions(names)
        for name in names:
            if name not in after:
                self.add('failed', [name])
            elif name in missing:
                self.add('installed', [name])
            elif after[name] != before[name]:
                self.add('upgraded', [name])
            else:
                self.add('failed' if name in outdated else 'skipped', [name])


def keep_sudo():
    while not threading.Event().wait(60):
        subprocess.run(['sudo', '-n', '-v'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False)


def bootstrap(*, dry_run=False, tmux_only=False, argv=()):
    if os.geteuid() == 0:  # Packages need root, but the configuration belongs to the user.
        print('Bootstrap failed: run ./bootstrap as your user'
              + ('.' if sys.platform == 'darwin' else '; it asks for sudo itself.'), file=sys.stderr)
        return 1
    if sys.platform == 'darwin':
        return macos(dry_run=dry_run, tmux_only=tmux_only, argv=argv)
    system = family()
    if system is None or not shutil.which('sudo'):
        print('Bootstrap failed: this needs Fedora, Debian or Ubuntu with sudo.', file=sys.stderr)
        return 1
    # The official oh-my-posh, mise and uv installers write to ~/.local/bin; install must find it there.
    local_bin = str(Path.home() / '.local/bin')
    if local_bin not in os.environ.get('PATH', '').split(os.pathsep):
        os.environ['PATH'] = local_bin + os.pathsep + os.environ.get('PATH', '')
    run = Bootstrap(dry_run=dry_run, log_path=state_directory() / 'bootstrap.log', apt=system == 'debian')
    run.say(f"\n== dalftui bootstrap {datetime.now().isoformat(timespec='seconds')}"
            f" {shlex.join(['bootstrap', *argv])} ==\n")
    run.update_repo(list(argv))
    if not tmux_only:
        run.vscode_repo()
    run.packages(read_packages(PACKAGES / f'{system}.txt', tmux_only=tmux_only))
    run.oh_my_posh()
    run.mise()
    run.uv()
    run.install(tmux_only=tmux_only)
    return run.report()


def macos(*, dry_run, tmux_only, argv):
    if tmux_only:
        print('Bootstrap failed: --tmux-only is Linux-only.', file=sys.stderr)
        return 1
    brew = shutil.which('brew') or next((path for path in BREW_PATHS if os.access(path, os.X_OK)), None)
    if not brew:
        print(f'Bootstrap failed: install Homebrew first: {BREW_INSTALLER}', file=sys.stderr)
        return 1
    # ./install must find Homebrew's tmux, oh-my-posh and uv.
    directory = os.path.dirname(brew)
    if directory not in os.environ.get('PATH', '').split(os.pathsep):
        os.environ['PATH'] = directory + os.pathsep + os.environ.get('PATH', '')
    os.environ['HOMEBREW_NO_AUTO_UPDATE'] = '1'  # A real run updates once itself; a dry run must not.
    run = Brew(brew=brew, dry_run=dry_run, log_path=state_directory() / 'bootstrap.log')
    run.say(f"\n== dalftui bootstrap {datetime.now().isoformat(timespec='seconds')}"
            f" {shlex.join(['bootstrap', *argv])} ==\n")
    run.update_repo(list(argv))
    run.packages(run.entries())
    run.install(tmux_only=False)
    return run.report()
