"""Windows console adapter for the shared full-screen host grid."""
import ctypes
from ctypes import wintypes
import os
import sys
import time


class ConsoleUnavailable(RuntimeError):
    """The current terminal cannot provide a native interactive console."""


class ConsoleScreen:
    def __init__(self):
        self.console = None
        self.modes = []
        self.active = False

    def __enter__(self):
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise ConsoleUnavailable('An interactive Windows console is required.')
        # Windows-only ctypes APIs cannot be inferred by Linux Pylint.
        self.console = ctypes.WinDLL('kernel32', use_last_error=True)  # pylint: disable=no-member
        self.console.GetStdHandle.argtypes = [wintypes.DWORD]
        self.console.GetStdHandle.restype = wintypes.HANDLE
        self.console.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self.console.GetConsoleMode.restype = wintypes.BOOL
        self.console.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.console.SetConsoleMode.restype = wintypes.BOOL
        try:
            for identifier, enabled, disabled in ((-10, 0x80, 0x247), (-11, 0x4, 0)):
                handle = self.console.GetStdHandle(identifier)
                mode = wintypes.DWORD(0)
                if not self.console.GetConsoleMode(handle, ctypes.byref(mode)):
                    raise ConsoleUnavailable('Could not read console mode.')
                self.modes.append((handle, mode.value))
                # Input: disable echo, line input, Ctrl+C processing, Quick Edit,
                # and VT input. Output: enable virtual-terminal rendering.
                if not self.console.SetConsoleMode(handle, (mode.value | enabled) & ~disabled):
                    raise ConsoleUnavailable('Could not enable interactive console mode.')
            self.active = True
            sys.stdout.write('\x1b[?1049h\x1b[?25l')
            sys.stdout.flush()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_args):
        try:
            if self.active:
                sys.stdout.write('\x1b[0m\x1b[?25h\x1b[?1049l')
                sys.stdout.flush()
        finally:
            self.active = False
            for handle, mode in reversed(self.modes):
                self.console.SetConsoleMode(handle, mode)
            self.modes.clear()

    @staticmethod
    def size():
        return os.get_terminal_size(sys.stdout.fileno())

    @staticmethod
    def draw(cells):
        colors = {'normal': '\x1b[0m', 'heading': '\x1b[96m',
                  'muted': '\x1b[90m', 'selected': '\x1b[7m'}
        output = ['\x1b[H\x1b[2J']
        for y, x, text, style in cells:
            output.append(f'\x1b[{y + 1};{x + 1}H{colors[style]}{text}\x1b[0m')
        sys.stdout.write(''.join(output))
        sys.stdout.flush()

    @staticmethod
    def read_key():
        # Import lazily so portable helpers and tests remain usable on Linux.
        import msvcrt  # pylint: disable=import-error
        if not msvcrt.kbhit():
            time.sleep(0.05)
            return None  # Let the shared loop notice terminal resizes.
        key = msvcrt.getwch()
        if key in ('\0', '\xe0'):
            return {'H': 'up', 'P': 'down', 'K': 'left', 'M': 'right',
                    'G': 'home', 'O': 'end', 'I': 'page_up', 'Q': 'page_down',
                    '\x0f': 'back_tab'}.get(msvcrt.getwch())
        if '\ud800' <= key <= '\udbff':
            following = msvcrt.getwch()
            if '\udc00' <= following <= '\udfff':
                key = chr(0x10000 + ((ord(key) - 0xd800) << 10) + ord(following) - 0xdc00)
            else:
                key = following
        return {'\r': 'enter', '\n': 'enter', '\x1b': 'cancel', '\x03': 'cancel',
                '\x04': 'eof', '\x08': 'backspace', '\x7f': 'backspace',
                '\x0f': 'connect_typed', '\x15': 'clear', '\t': 'tab'}.get(key, key)
