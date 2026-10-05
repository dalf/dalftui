"""Linux desktop SSH picker and Alacritty window launching."""
try:
    import curses
except ImportError:
    curses = None
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def host_cache_path():
    directory = Path(os.environ.get('XDG_CACHE_HOME', ''))
    if not directory.is_absolute():
        directory = Path.home() / '.cache'
    return directory / 'dalftui/hosts-cache.json'


def set_terminal_title(title):
    """Set the outer terminal title before starting the remote shell or tmux."""
    if not sys.stdout.isatty():
        return
    title = ''.join(char for char in title if char.isprintable())
    try:
        sys.stdout.write(f'\x1b]2;{title}\x07')
        sys.stdout.flush()
    except (OSError, UnicodeError):
        # An unsupported terminal or output encoding must not block SSH.
        pass


class PickerScreen:
    """Adapt curses to the shared grid without importing it on Windows."""
    def __init__(self, screen):
        self.screen = screen
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_WHITE, -1)
        curses.init_pair(3, 246 if curses.COLORS >= 256 else curses.COLOR_WHITE, -1)
        curses.set_escdelay(25)

    def size(self):
        height, width = self.screen.getmaxyx()
        return width, height

    def draw(self, cells):
        from ..host_picker import cell_width
        self.screen.erase()
        styles = {'normal': curses.color_pair(2),
                  'heading': curses.color_pair(1) | curses.A_BOLD,
                  'muted': curses.color_pair(3),
                  'selected': curses.color_pair(2) | curses.A_REVERSE | curses.A_BOLD}
        for y, x, text, style in cells:
            try:
                self.screen.addnstr(y, x, text, len(text), styles[style])
            except curses.error:
                pass  # A resize may happen between layout and drawing.
        try:
            query = next((text for y, _, text, _ in cells if y == 2), '')
            self.screen.move(2, min(self.size()[0] - 2, 1 + cell_width(query)))
        except curses.error:
            pass
        self.screen.refresh()

    def read_key(self):
        key = self.screen.get_wch()
        keys = {curses.KEY_UP: 'up', curses.KEY_DOWN: 'down',
                curses.KEY_LEFT: 'left', curses.KEY_RIGHT: 'right',
                curses.KEY_HOME: 'home', curses.KEY_END: 'end',
                curses.KEY_PPAGE: 'page_up', curses.KEY_NPAGE: 'page_down',
                curses.KEY_BACKSPACE: 'backspace', curses.KEY_ENTER: 'enter',
                curses.KEY_BTAB: 'back_tab', curses.KEY_RESIZE: None, curses.KEY_F0 + 4: 'actions',
                '\x1b': 'cancel', '\x03': 'cancel', '\x04': 'eof',
                '\r': 'enter', '\n': 'enter', '\x7f': 'backspace', '\b': 'backspace',
                '\x0f': 'connect_typed', '\x15': 'clear', '\t': 'tab'}
        return keys.get(key, key if isinstance(key, str) else None)


def pick(screen, hosts, *, action='opens a new window'):
    from .. import host_picker, ssh
    return host_picker.pick(PickerScreen(screen), hosts, ssh.validate_picker_host, action=action,
                            details=ssh.connection_details, checks=ssh.saved_checks)

def open_window(host):
    from .. import ssh
    from ..host_picker import HostAction

    selection = host
    if isinstance(selection, HostAction):
        host = selection.host

    alacritty = shutil.which('alacritty')
    if not alacritty:
        raise RuntimeError('Alacritty was not found in PATH')
    env = dict(os.environ)
    env.pop('TMUX', None)
    env.pop('TMUX_PANE', None)
    # -e overrides the normal local-tmux startup command for this new OS window.
    # --title fixes the title in place, ignoring the connecting process's update.
    # JSON quoting also produces a TOML basic string for this printable host.
    title = json.dumps(f'SSH · {host}', ensure_ascii=False)
    args = [alacritty, '--option', f'window.title={title}', 'window.dynamic_title=true',
            '-e', sys.executable,
            str(ssh.CHECKOUT_ROOT / 'bin/ssh_picker.py'), '--connect', host,
            *ssh.action_arguments(selection)]
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(args, env=env, start_new_session=True,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        try:
            status = process.wait(timeout=0.4)
        except subprocess.TimeoutExpired:
            return
        if status:
            log.seek(0)
            raise RuntimeError(log.read().decode(errors='replace').strip() or 'Could not open Alacritty')


def run_picker(parser, *, refresh=False):
    from .. import ssh

    if curses is None:
        parser.error('The SSH picker requires Python curses support. Use --connect HOST to connect directly.')
    try:
        hosts = ssh.target_hosts(refresh=True) if refresh else ssh.target_hosts()
        host = curses.wrapper(pick, hosts)
        if host:
            open_window(host)
    except (OSError, RuntimeError, curses.error) as error:
        print(f'Could not open SSH window: {error}', file=sys.stderr)
        try:
            input('Press Enter to return.')
        except (EOFError, KeyboardInterrupt):
            pass
        return 1
    return 0
