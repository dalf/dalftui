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


def pick(screen, hosts):
    from .. import ssh

    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN, -1)
    curses.init_pair(2, curses.COLOR_WHITE, -1)
    curses.init_pair(3, 246 if curses.COLORS >= 256 else curses.COLOR_WHITE, -1)
    curses.set_escdelay(25)
    query, selected, message = '', 0, ''

    def write(y, x, text, style=0):
        height, width = screen.getmaxyx()
        if 0 <= y < height and x < width - 1:
            try:
                screen.addnstr(y, x, text, width - x - 1, style)
            except curses.error:
                pass

    while True:
        height, width = screen.getmaxyx()
        screen.erase()
        matches = [host for host in hosts if query.casefold() in host.casefold()]
        selected = max(0, min(selected, len(matches) - 1))
        capacity = max(1, height - 9)
        start = max(0, selected - capacity + 1)
        write(1, 2, 'SSH HOSTS · TAG DALFTUI', curses.color_pair(1) | curses.A_BOLD)
        write(2, 2, 'Type to filter · ↑/↓ select · Enter opens a new window · Esc cancels', curses.color_pair(3))
        write(4, 2, 'Filter: ', curses.color_pair(3))
        write(4, 10, query, curses.color_pair(2))
        if not matches:
            hint = ('No matching tagged hosts. Enter checks the typed hostname.' if query
                    else 'No hosts enabled. Add Tag dalftui to an SSH Host entry.')
            write(6, 2, hint, curses.color_pair(3))
        for index in range(start, min(len(matches), start + capacity)):
            label = matches[index]
            style = curses.color_pair(2)
            if index == selected:
                style |= curses.A_REVERSE | curses.A_BOLD
            write(6 + index - start, 2, ('  ' + label).ljust(max(0, width - 5)), style)
        write(height - 3, 2, message, curses.color_pair(1))
        write(height - 2, 2, 'Remote tmux when installed · otherwise a login shell', curses.color_pair(3))
        try:
            screen.move(min(4, height - 1), min(10 + len(query), max(0, width - 2)))
        except curses.error:
            pass
        screen.refresh()
        key = screen.get_wch()
        if key in ('\x1b', '\x03'):
            return None
        if key in ('\n', '\r', curses.KEY_ENTER):
            if matches:
                return matches[selected]
            if ssh.valid_host(query):
                try:
                    if ssh.configured_tag(query) == ssh.PICKER_TAG:
                        return query
                    message = f'{query} is not enabled: add Tag dalftui to its SSH configuration.'
                except RuntimeError as error:
                    message = str(error)
            continue
        if key == curses.KEY_UP:
            selected = max(0, selected - 1)
        elif key == curses.KEY_DOWN:
            selected = min(len(matches) - 1, selected + 1)
        elif key == curses.KEY_PPAGE:
            selected = max(0, selected - capacity)
        elif key == curses.KEY_NPAGE:
            selected = min(len(matches) - 1, selected + capacity)
        elif key in ('\x7f', '\b', curses.KEY_BACKSPACE):
            query, selected, message = query[:-1], 0, ''
        elif key == '\x15':
            query, selected, message = '', 0, ''
        elif isinstance(key, str) and key.isprintable() and not key.isspace():
            query, selected, message = query + key, 0, ''


def open_window(host):
    from .. import ssh

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
            str(ssh.CHECKOUT_ROOT / 'bin/ssh_picker.py'), '--connect', host]
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
        parser.error('Use --connect HOST on Windows; the interactive host picker requires curses.')
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
