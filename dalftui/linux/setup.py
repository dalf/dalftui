"""Install stable configuration loaders and reload them without restarting sessions."""
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time

from .alacritty_config import config_directory, load
# Portable JSONC editing shared with the Windows setup.
from ..windows.terminal_settings import PROMPT_FONT, removed_vscode_settings, vscode_settings

MARKER = '# Managed by dalftui.'
PROFILE_MARKER = '# dalftui-profile: '
PROFILES = ('desktop', 'tmux-only', 'macos')
# Alacritty is not used on macOS; a new Mac installation uses Terminal.app or iTerm2.
DEFAULT_PROFILE = 'macos' if sys.platform == 'darwin' else 'desktop'
PROMPT_MARKER = '# dalftui: Oh My Posh prompt'
REPO = Path(__file__).resolve().parents[2]
LOCAL_TMUX = '# Personal tmux settings. Loaded after the shared dalftui configuration.\n'
LOCAL_ALACRITTY = ('# Personal Alacritty settings. This file stays outside the repository.\n'
                   '# Example:\n# [font]\n# size = 11.0\n')
# Discover the directory before .zshrc/.zlogin can change it or initialize a prompt.
# -f skips user startup; /etc/zshenv still runs automatically. Enable the normal
# startup options while sourcing the files that select an interactive login rc.
ZSH_RC_PROBE = r'''
setopt rcs
if [[ -r ${ZDOTDIR:-$HOME}/.zshenv ]]; then
    builtin source "${ZDOTDIR:-$HOME}/.zshenv"
fi
if [[ -o rcs && -o globalrcs && -r /etc/zprofile ]]; then
    builtin source /etc/zprofile
fi
if [[ -o rcs && -r ${ZDOTDIR:-$HOME}/.zprofile ]]; then
    builtin source "${ZDOTDIR:-$HOME}/.zprofile"
fi
builtin printf '\0DALFTUI_ZDOTDIR\0%s\0' "${ZDOTDIR:-$HOME}"
unsetopt rcs
'''


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

    @property
    def bashrc(self):
        return self.home_dir / '.bashrc'

    @property
    def zshrc(self):
        """Honor ZDOTDIR from interactive login startup without loading the prompt."""
        zdotdir = os.environ.get('ZDOTDIR')
        if shutil.which('zsh'):
            try:
                result = subprocess.run(['zsh', '-f', '-i', '-l', '-c', ZSH_RC_PROBE], stdin=subprocess.DEVNULL,
                                        env=dict(os.environ, HOME=str(self.home_dir)),
                                        capture_output=True, text=True, timeout=10)
                _, marker, value = result.stdout.rpartition('\0DALFTUI_ZDOTDIR\0')
                value, end, _ = value.partition('\0')
                if result.returncode == 0 and marker and end:
                    zdotdir = value
            except (OSError, subprocess.SubprocessError):
                pass
        return (Path(zdotdir) if zdotdir and Path(zdotdir).is_absolute() else self.home_dir) / '.zshrc'

    @property
    def vscode_settings(self):
        if sys.platform == 'darwin':
            return self.home_dir / 'Library/Application Support/Code/User/settings.json'
        return self.config_dir / 'Code/User/settings.json'


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


def installed_profile(paths=None):
    """The private tmux loader records the mode; old installations are desktops."""
    paths = paths or Paths.current()
    if not paths.tmux.exists():
        return DEFAULT_PROFILE
    content = paths.tmux.read_text()
    if not content.startswith(MARKER):
        return DEFAULT_PROFILE
    for line in content.splitlines():
        if line.startswith(PROFILE_MARKER):
            profile = line[len(PROFILE_MARKER):]
            if profile not in PROFILES:
                raise ValueError(f'Unknown installation mode in {paths.tmux}: {profile}')
            return profile
    return 'desktop'


def loaders(paths, profile='desktop', *, legacy=False):
    imports = [str(paths.root / 'config/alacritty.toml'),
               str(paths.config_dir / 'alacritty/local.toml')]
    alacritty = (f'{MARKER} Edit local.toml for personal settings.\n'
                 '[general]\n'
                 f'import = {json.dumps(imports, ensure_ascii=False)}\n'
                 'live_config_reload = true\n')
    tmux = f'{MARKER} Edit the local.conf below for personal settings.\n'
    if not legacy:
        tmux += f'{PROFILE_MARKER}{profile}\nset -g @dalftui_profile {profile}\n'
    tmux += (f'source-file {tmux_quote(paths.root / "config/tmux.conf")}\n'
            f'source-file -q {tmux_quote(paths.config_dir / "tmux/local.conf")}\n')
    return alacritty.encode(), tmux.encode()


def known_tmux(paths):
    return {loaders(paths, mode)[1] for mode in PROFILES} | {loaders(paths, legacy=True)[1]}


def dependencies(profile='desktop'):
    if profile not in PROFILES:
        raise ValueError(f'Unknown installation mode: {profile}')
    if not sys.platform.startswith('linux') and sys.platform != 'darwin':
        raise RuntimeError('This installer targets Linux and macOS.')
    if sys.platform == 'darwin' and profile == 'desktop':
        raise RuntimeError('The Alacritty desktop mode is Linux-only; run ./install without --desktop.')
    if sys.platform != 'darwin' and profile == 'macos':
        raise RuntimeError('The macos mode is for macOS only.')
    if sys.version_info < (3, 11):
        raise RuntimeError('Python 3.11 or newer is required.')
    programs = ('tmux', 'less', 'git', 'oh-my-posh', 'uv')  # uv runs the Python of the tmux keys.
    if profile == 'desktop':
        programs += ('alacritty', 'ssh')
    missing = [name for name in programs if not shutil.which(name)]
    if missing:
        hint = ''
        if sys.platform == 'darwin':
            hint = ' (Homebrew: brew install tmux oh-my-posh uv, or ./bootstrap)'
        elif 'uv' in missing:
            hint = ' (uv: ./bootstrap installs it; or see https://docs.astral.sh/uv/getting-started/installation/)'
        raise RuntimeError('Install the missing dependencies first: ' + ', '.join(missing) + hint)
    specifications = [('tmux', '-V', (3, 2))]
    if profile == 'desktop':
        specifications += [('alacritty', '--version', (0, 14)), ('ssh', '-V', (9, 4))]
    for name, flag, minimum in specifications:
        result = subprocess.run([name, flag], capture_output=True, text=True, timeout=10)
        match = re.search(r'(\d+)\.(\d+)', result.stdout + result.stderr)
        if result.returncode or not match or tuple(map(int, match.groups())) < minimum:
            detected = f' Detected {match.group(0)}.' if match else ''
            raise RuntimeError(f'{name} {minimum[0]}.{minimum[1]} or newer is required.{detected}')


def rc_with_prompt(paths, previous, loader_name):
    """Append the managed prompt line once, keeping the rest of ~/.bashrc or ~/.zshrc."""
    content = previous.value if previous and previous.kind == 'file' else b''
    if PROMPT_MARKER.encode() in content:
        return content
    if content and not content.endswith(b'\n'):
        content += b'\n'
    loader = shlex.quote(str(paths.root / 'config' / loader_name))
    return content + f'{PROMPT_MARKER}\n[ -f {loader} ] && . {loader}\n'.encode()


def rc_without_prompt(content):
    """Remove each marker line that is followed by its prompt loader line."""
    lines = content.splitlines(keepends=True)
    loader = re.compile(rb"\[ -f (.+/dalftui/config/prompt\.(?:bash|zsh)'?) \] && \. \1\r?\n?")
    kept, index = [], 0
    while index < len(lines):
        if (lines[index].rstrip(b'\r\n') == PROMPT_MARKER.encode() and index + 1 < len(lines)
                and loader.fullmatch(lines[index + 1])):
            index += 2
        else:
            kept.append(lines[index])
            index += 1
    return b''.join(kept)


def vscode_present(paths):
    """Only desktops with VS Code get its settings file."""
    return bool(shutil.which('code')) or paths.vscode_settings.parents[1].is_dir()


def vscode_settings_bytes(path):
    """Return the updated settings, or None when they are already set."""
    previous = snapshot(path.resolve())
    content = previous.value if previous and previous.kind == 'file' else b''
    try:
        text = content.decode('utf-8-sig')
        updated = vscode_settings(text)
    except ValueError as error:
        raise ValueError(f'Fix the VS Code settings first: {path}: {error}') from error
    if updated == text:
        return None  # Also keeps a symlinked settings file.
    bom = b'\xef\xbb\xbf' if content.startswith(b'\xef\xbb\xbf') else b''
    return bom + updated.encode()


def install_font(dry_run):
    """Install the Nerd Font used by the prompt and VS Code unless it is present."""
    if sys.platform == 'darwin':  # Stock macOS has no fc-list; oh-my-posh installs into ~/Library/Fonts.
        for fonts in (Path.home() / 'Library/Fonts', Path('/Library/Fonts')):
            if any(fonts.glob('HackNerdFont-*')):  # Not HackNerdFontMono or HackNerdFontPropo.
                return
    if shutil.which('fc-list'):
        result = subprocess.run(['fc-list', ':', 'family'], capture_output=True, text=True, timeout=30)
        if any(PROMPT_FONT in line.split(',') for line in result.stdout.splitlines()):
            return
    if dry_run:
        print(f'Install font: {PROMPT_FONT}')
        return
    subprocess.run(['oh-my-posh', 'font', 'install', 'Hack'], check=True, timeout=300)


def apply(paths, changes, *, dry_run, check=None):
    """Back up, then write or remove (wanted None) each path; roll back on failure."""
    if dry_run:
        for path, previous, wanted in changes:
            action = 'Create' if not previous else 'Back up and ' + ('remove' if wanted is None else 'replace')
            print(f'{action}: {path}')
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
            if wanted is None:
                path.unlink()
            else:
                write(path, wanted)
            written.append((path, previous))
        if check:
            check()
    except BaseException:
        for path, previous in reversed(written):
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                write(path, previous)
        raise
    return backup


def install(paths=None, repo=None, *, dry_run=False, profile=None):
    paths = paths or Paths.current()
    profile = profile or installed_profile(paths)
    if profile not in PROFILES:
        raise ValueError(f'Unknown installation mode: {profile}')
    repo = Path(repo or REPO).resolve()
    for path in (paths.home_dir, paths.config_dir, paths.state_dir, repo):
        if not path.is_absolute() or any(ord(char) < 32 for char in str(path)):
            raise ValueError('Configuration paths must be absolute and contain no control characters.')
    if paths.root == repo:
        raise ValueError('Keep the checkout outside the managed ~/.config/dalftui link.')
    if profile == 'desktop':
        load(repo / 'config/alacritty.toml', home_dir=paths.home_dir)
    alacritty, tmux = loaders(paths, profile)
    desired = [
        (paths.root, Snapshot('link', str(repo))),
        (paths.tmux, Snapshot('file', tmux)),
        (paths.config_dir / 'tmux/shortcuts.py',
         Snapshot('link', str(paths.root / 'bin/shortcuts.py'))),
    ]
    if profile == 'desktop':
        desired.append((paths.alacritty, Snapshot('file', alacritty)))
    # A symlinked ~/.bashrc or ~/.zshrc is replaced like other managed paths, keeping its content.
    rc, loader_name = (paths.zshrc, 'prompt.zsh') if profile == 'macos' else (paths.bashrc, 'prompt.bash')
    desired.append((rc, Snapshot('file', rc_with_prompt(paths, snapshot(rc.resolve()), loader_name))))
    if profile in ('desktop', 'macos') and vscode_present(paths):
        settings = vscode_settings_bytes(paths.vscode_settings)
        if settings is not None:
            desired.append((paths.vscode_settings, Snapshot('file', settings)))
    local_alacritty = paths.config_dir / 'alacritty/local.toml'
    local_tmux = paths.config_dir / 'tmux/local.conf'
    local_files = [(local_tmux, LOCAL_TMUX)]
    if profile == 'desktop':
        local_files.append((local_alacritty, LOCAL_ALACRITTY))
    for path, content in local_files:
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
            if path != paths.tmux or previous.value not in known_tmux(paths):
                raise ValueError(f'Managed loader was edited: {path}. Move overrides to the local file first.')
        changes.append((path, previous, wanted))
    if profile in ('desktop', 'macos'):
        install_font(dry_run)
    if not changes:
        print('Already installed; personal overrides preserved.')
        return None
    check = (lambda: load(paths.alacritty, home_dir=paths.home_dir)) if profile == 'desktop' else None
    backup = apply(paths, changes, dry_run=dry_run, check=check)
    if dry_run:
        return None
    print(f'Installed ({profile}): {paths.root} -> {repo}')
    if backup:
        print(f'Original configurations backed up in {backup}')
    personal = [str(local_tmux)]
    if profile == 'desktop':
        personal.insert(0, str(local_alacritty))
    print('Personal settings: ' + ' and '.join(personal))
    return backup


def original_file(paths, path):
    """Return the newest backup of path that dalftui did not generate, and its location."""
    found = None
    manifests = (paths.state_dir / 'dalftui/backups').glob('*/manifest.json')
    for manifest in sorted(manifests, key=lambda item: item.parent.name.zfill(32)):
        try:
            for record in json.loads(manifest.read_text()):
                saved = manifest.parent / record['backup']
                if record['original'] == str(path):
                    item = snapshot(saved)  # dalftui never links a loader, so a link is the user's.
                    if item and (item.kind == 'link' or not item.value.startswith(MARKER.encode())):
                        found = item, saved
        except (OSError, ValueError, KeyError, TypeError):
            continue  # An unreadable manifest only means nothing is restored from it.
    return found


def uninstall(paths=None, *, dry_run=False):
    """Remove what install created while it is unchanged; keep personal files and backups."""
    paths = paths or Paths.current()
    changes, notes, edited = [], [], False
    alacritty = loaders(paths)[0]
    for path, known in ((paths.tmux, known_tmux(paths)), (paths.alacritty, {alacritty})):
        previous = snapshot(path)
        if not previous or previous.kind != 'file' or not previous.value.startswith(MARKER.encode()):
            continue
        if previous.value not in known:
            notes.append(f'Kept edited loader: {path}')
            edited = True
            continue
        restored = original_file(paths, path)
        if restored:
            notes.append(f'Restore {path} from {restored[1]}')
        changes.append((path, previous, restored and restored[0]))
    guide = paths.config_dir / 'tmux/shortcuts.py'
    previous = snapshot(guide)
    if previous and previous.kind == 'link' and previous.value in (
            str(paths.root / 'bin/shortcuts.py'), str(paths.root / 'shortcuts.py')):
        changes.append((guide, previous, None))
    for rc in dict.fromkeys((paths.bashrc, paths.zshrc, paths.home_dir / '.zshrc')):
        previous = snapshot(rc)  # Install writes a file; a symlink is not its own.
        if previous and previous.kind == 'file':
            content = rc_without_prompt(previous.value)
            if content != previous.value:
                changes.append((rc, previous, replace(previous, value=content)))
            if PROMPT_MARKER.encode() in content:
                notes.append(f'Kept an edited "{PROMPT_MARKER}" line: {rc}')
    previous = snapshot(paths.vscode_settings)
    if previous and previous.kind == 'file':
        bom = b'\xef\xbb\xbf' if previous.value.startswith(b'\xef\xbb\xbf') else b''
        try:
            text = previous.value.decode('utf-8-sig')
            content = bom + removed_vscode_settings(text).encode()
        except ValueError as error:
            raise ValueError(f'Fix the VS Code settings first: {paths.vscode_settings}: {error}') from error
        if content != previous.value:
            changes.append((paths.vscode_settings, previous, replace(previous, value=content)))
            notes.append(f'Earlier VS Code font settings, if any, are backed up in {paths.state_dir / "dalftui/backups"}')
    for path, template in ((paths.config_dir / 'tmux/local.conf', LOCAL_TMUX),
                           (paths.config_dir / 'alacritty/local.toml', LOCAL_ALACRITTY)):
        previous = snapshot(path)
        if previous and previous.kind == 'file' and previous.value == template.encode():
            changes.append((path, previous, None))
        elif previous:
            notes.append(f'Kept personal settings: {path}')
    if paths.root.is_symlink() and edited:
        notes.append(f'Kept {paths.root}: the edited loader still sources it')
    elif paths.root.is_symlink():  # Last: the other files refer to this link.
        changes.append((paths.root, snapshot(paths.root), None))
    elif paths.root.exists():
        notes.append(f'Kept, not a dalftui link: {paths.root}')
    for note in notes:
        print(note)
    if not changes:
        print('Nothing to uninstall.')
        return None
    backup = apply(paths, changes, dry_run=dry_run)
    if dry_run:
        return None
    print(f'Uninstalled dalftui configuration. Removed files are backed up in {backup}')
    print('Running tmux and Alacritty keep their current configuration until restarted.')
    return backup


def reload_config(paths=None, *, socket=None):
    paths = paths or Paths.current()
    if not paths.root.is_symlink() or not paths.root.exists():
        raise RuntimeError('The dalftui link is missing or broken. Run ./install from your checkout.')
    if not paths.tmux.read_bytes().startswith(MARKER.encode()):
        raise RuntimeError('Configuration loaders are missing. Run ./install first.')
    if not shutil.which('uv') and not (paths.home_dir / '.local/bin/uv').exists():
        raise RuntimeError('uv is missing; the tmux keys need it. Install uv, or rerun ./bootstrap, then reload.')
    profile = installed_profile(paths)
    if profile == 'desktop':
        content = paths.alacritty.read_bytes()
        if not content.startswith(MARKER.encode()):
            raise RuntimeError('The Alacritty loader is missing. Run ./install first.')
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
    result = subprocess.run([*command, 'set-option', '-g', '@dalftui_profile', profile,
                             ';', 'source-file', str(paths.tmux)],
                            capture_output=True, text=True, timeout=20)
    if result.returncode or result.stderr.strip():
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'tmux reload failed.')
    print('tmux configuration reloaded; sessions and running programs kept.')
