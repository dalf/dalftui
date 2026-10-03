"""Install stable configuration loaders and reload them without restarting sessions."""
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time

from alacritty_config import config_directory, load

MARKER = '# Managed by dalftui.'
REPO = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Paths:
    home_dir: Path
    config_dir: Path
    state_dir: Path

    @classmethod
    def current(cls):
        state = os.environ.get('XDG_STATE_HOME')
        state_dir = Path(state) if state and Path(state).is_absolute() else Path.home() / '.local/state'
        return cls(Path.home(), config_directory(), state_dir)

    @property
    def root(self):
        return self.config_dir / 'dalftui'

    @property
    def alacritty(self):
        return self.config_dir / 'alacritty/alacritty.toml'

    @property
    def tmux(self):
        return self.home_dir / '.tmux.conf'


@dataclass(frozen=True)
class Snapshot:
    kind: str
    value: bytes | str
    mode: int = 0o644


def snapshot(path):
    if path.is_symlink():
        return Snapshot('link', os.readlink(path))
    if not path.exists():
        return None
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f'Refusing to replace a directory or special file: {path}')
    return Snapshot('file', path.read_bytes(), stat.S_IMODE(info.st_mode))


def write(path, item):
    """Replace a regular file or symlink without modifying its previous target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    temporary = Path(name)
    try:
        if item.kind == 'file':
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(item.value)
                stream.flush()
                os.fsync(stream.fileno())
                os.fchmod(stream.fileno(), item.mode)
        else:
            os.close(descriptor)
            temporary.unlink()
            temporary.symlink_to(item.value)
        os.replace(temporary, path)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()


def tmux_quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$') + '"'


def loaders(paths):
    imports = [str(paths.root / 'config/alacritty.toml'),
               str(paths.config_dir / 'alacritty/local.toml')]
    alacritty = (f'{MARKER} Edit local.toml for personal settings.\n'
                 '[general]\n'
                 f'import = {json.dumps(imports, ensure_ascii=False)}\n'
                 'live_config_reload = true\n')
    tmux = (f'{MARKER} Edit the local.conf below for personal settings.\n'
            f'source-file {tmux_quote(paths.root / "config/tmux.conf")}\n'
            f'source-file -q {tmux_quote(paths.config_dir / "tmux/local.conf")}\n')
    return alacritty.encode(), tmux.encode()


def dependencies():
    if not sys.platform.startswith('linux'):
        raise RuntimeError('This installer currently targets Linux.')
    if sys.version_info < (3, 11):
        raise RuntimeError('Python 3.11 or newer is required.')
    missing = [name for name in ('alacritty', 'tmux', 'ssh', 'less', 'git') if not shutil.which(name)]
    if missing:
        raise RuntimeError('Install the missing dependencies first: ' + ', '.join(missing))
    specifications = [('alacritty', '--version', (0, 14)),
                      ('tmux', '-V', (3, 4)), ('ssh', '-V', (9, 4))]
    for name, flag, minimum in specifications:
        result = subprocess.run([name, flag], capture_output=True, text=True, timeout=10)
        match = re.search(r'(\d+)\.(\d+)', result.stdout + result.stderr)
        if result.returncode or not match or tuple(map(int, match.groups())) < minimum:
            raise RuntimeError(f'{name} {minimum[0]}.{minimum[1]} or newer is required.')


def install(paths=None, repo=None, *, dry_run=False):
    paths = paths or Paths.current()
    repo = Path(repo or REPO).resolve()
    for path in (paths.home_dir, paths.config_dir, paths.state_dir, repo):
        if not path.is_absolute() or any(ord(char) < 32 for char in str(path)):
            raise ValueError('Configuration paths must be absolute and contain no control characters.')
    if paths.root == repo:
        raise ValueError('Keep the checkout outside the managed ~/.config/dalftui link.')
    load(repo / 'config/alacritty.toml', home_dir=paths.home_dir)
    alacritty, tmux = loaders(paths)
    desired = [
        (paths.root, Snapshot('link', str(repo))),
        (paths.alacritty, Snapshot('file', alacritty)),
        (paths.tmux, Snapshot('file', tmux)),
        (paths.config_dir / 'tmux/shortcuts.py',
         Snapshot('link', str(paths.root / 'shortcuts.py'))),
    ]
    local_alacritty = paths.config_dir / 'alacritty/local.toml'
    local_tmux = paths.config_dir / 'tmux/local.conf'
    for path, content in (
        (local_alacritty, '# Personal Alacritty settings. This file stays outside the repository.\n'
                          '# Example:\n# [font]\n# size = 11.0\n'),
        (local_tmux, '# Personal tmux settings. Loaded after the shared dalftui configuration.\n'),
    ):
        existing = snapshot(path)
        if existing is None:
            desired.append((path, Snapshot('file', content.encode())))
        elif path == local_alacritty:
            load(path, home_dir=paths.home_dir)

    changes = []
    for path, wanted in desired:
        previous = snapshot(path)
        if previous and previous.kind == wanted.kind == 'file':
            wanted = replace(wanted, mode=previous.mode)
        if previous == wanted:
            continue
        if (path in (paths.alacritty, paths.tmux) and previous and previous.kind == 'file'
                and previous.value.startswith(MARKER.encode())):
            raise ValueError(f'Managed loader was edited: {path}. Move overrides to the local file first.')
        changes.append((path, previous, wanted))
    if not changes:
        print('Already installed; personal overrides preserved.')
        return None
    if dry_run:
        for path, previous, wanted in changes:
            print(f'{"Back up and replace" if previous else "Create"}: {path}')
        print('Dry run: no files changed.')
        return None

    backup = None
    if any(previous is not None for _, previous, _ in changes):
        backup = paths.state_dir / 'dalftui/backups' / str(time.time_ns())
        backup.mkdir(parents=True, mode=0o700)
        os.chmod(backup, 0o700)
        records = []
        for index, (path, previous, _) in enumerate(changes):
            if previous is not None:
                filename = f'{index:02d}-{path.name}'
                write(backup / filename, previous)
                records.append({'original': str(path), 'backup': filename, 'kind': previous.kind})
        (backup / 'manifest.json').write_text(json.dumps(records, indent=2) + '\n')

    written = []
    try:
        for path, previous, wanted in changes:
            write(path, wanted)
            written.append((path, previous))
        load(paths.alacritty, home_dir=paths.home_dir)
    except BaseException:
        for path, previous in reversed(written):
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                write(path, previous)
        raise
    print(f'Installed: {paths.root} -> {repo}')
    if backup:
        print(f'Original configurations backed up in {backup}')
    print('Personal settings: ' + str(local_alacritty) + ' and ' + str(local_tmux))
    return backup


def reload_config(paths=None, *, socket=None):
    paths = paths or Paths.current()
    if not paths.root.is_symlink() or not paths.root.exists():
        raise RuntimeError('The dalftui link is missing or broken. Run ./install from your checkout.')
    content = paths.alacritty.read_bytes()
    if not content.startswith(MARKER.encode()) or not paths.tmux.read_bytes().startswith(MARKER.encode()):
        raise RuntimeError('Configuration loaders are missing. Run ./install first.')
    load(paths.alacritty, home_dir=paths.home_dir)

    # Write the same bytes in place: Alacritty's watcher can miss rename events
    # produced by Git or an editor. A data modification on its main file is reliable.
    with paths.alacritty.open('r+b') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    print('Alacritty configuration reload requested; startup settings apply to new windows.')

    command = ['tmux', '-N']
    if socket:
        command.extend(['-S', str(socket)])
    status = subprocess.run([*command, 'has-session'], capture_output=True, text=True, timeout=10)
    if status.returncode:
        message = status.stderr.strip()
        absent = any(value in message.lower() for value in
                     ('no server running', 'no such file', 'connection refused', 'no sessions'))
        if status.returncode == 1 and (absent or not message):
            print('tmux is not running; the next server will load the updated configuration.')
            return
        raise RuntimeError(message or 'Could not contact the tmux server.')
    result = subprocess.run([*command, 'source-file', str(paths.tmux)],
                            capture_output=True, text=True, timeout=20)
    if result.returncode or result.stderr.strip():
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'tmux reload failed.')
    print('tmux configuration reloaded; sessions and running programs kept.')
