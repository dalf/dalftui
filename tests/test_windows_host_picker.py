"""Shared grid and Windows console regressions, runnable on either platform."""
from contextlib import redirect_stdout
import io
import subprocess
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dalftui import host_picker, ssh
from dalftui.windows import host_picker as windows_picker


class Screen:
    def __init__(self, keys, size=(100, 24)):
        self.keys = iter(keys)
        self.dimensions = size
        self.frames = []

    def size(self):
        return self.dimensions

    def draw(self, cells):
        self.frames.append(cells)

    def read_key(self):
        key = next(self.keys)
        if isinstance(key, tuple):
            self.dimensions = key
            return None
        return key


class GridTests(unittest.TestCase):
    hosts = [f'host-{index:02}' for index in range(45)]

    def choose(self, keys, hosts=None, size=(100, 24), validate=None):
        screen = Screen(keys, size)
        selected = host_picker.pick(screen, self.hosts if hosts is None else hosts,
                                    validate or (lambda _host: 'Host is not enabled'))
        return selected, screen.frames

    def test_all_hosts_fit_in_three_columns_without_scrolling(self):
        selected, frames = self.choose(['enter'])
        self.assertEqual(selected, 'host-00')
        labels = [(y, x, text[2:]) for y, x, text, _ in frames[0] if text[2:] in self.hosts]
        self.assertEqual([label for _, _, label in labels], self.hosts)
        self.assertEqual(len({x for _, x, _ in labels}), 3)
        self.assertEqual(max(y for y, _, _ in labels), 21)

    def test_tall_terminal_needs_only_one_column(self):
        _, frames = self.choose(['cancel'], size=(100, 55))
        labels = [(x, text[2:]) for _, x, text, _ in frames[0] if text[2:] in self.hosts]
        self.assertEqual(len(labels), len(self.hosts))
        self.assertEqual({x for x, _ in labels}, {1})

    def test_navigation_reaches_columns_pages_and_last_partial_column(self):
        cases = (
            (['right', 'enter'], (100, 24), 'host-18'),
            (['right', 'down', 'left', 'enter'], (100, 24), 'host-01'),
            (['end', 'left', 'right', 'enter'], (100, 24), 'host-44'),
            (['page_down', 'enter'], (24, 12), 'host-12'),
            (['end', 'page_up', 'enter'], (24, 12), 'host-32'),
            (['end', 'home', 'tab', 'back_tab', 'enter'], (100, 24), 'host-00'),
        )
        for keys, size, expected in cases:
            with self.subTest(keys=keys, size=size):
                self.assertEqual(self.choose(keys, size=size)[0], expected)

    def test_resize_preserves_selection_and_reflows_visible_hosts(self):
        selected, frames = self.choose(['end', (24, 12), (150, 24), 'enter'])
        self.assertEqual(selected, 'host-44')
        for frame in frames:
            active = [text for _, _, text, style in frame if style == 'selected']
            self.assertEqual(len(active), 1)
        self.assertEqual([text for _, _, text, style in frames[-1] if style == 'selected'], ['> host-44'])
        self.assertEqual(sum(text[2:] in self.hosts for _, _, text, _ in frames[-1]), 45)

    def test_fuzzy_filter_clear_backspace_and_unicode_preserve_alphabetical_order(self):
        hosts = ['dev-api', 'prod-api', 'prod-database', 'prod-é']
        self.assertEqual(host_picker.filtered_hosts(hosts, 'PD A'), ['prod-api', 'prod-database'])
        self.assertEqual(self.choose([*'PD É', 'enter'], hosts)[0], 'prod-é')
        self.assertEqual(self.choose([*'wrong', 'clear', *'devx', 'backspace', 'enter'], hosts)[0], 'dev-api')
        self.assertIsNone(self.choose([*'no-match', 'enter', 'cancel'], hosts)[0])

    def test_filter_keeps_alphabetical_order_across_columns(self):
        hosts = ['alpha', 'Bravo', 'charlie', 'delta', 'Echo', 'zeta']
        _, frames = self.choose([*'a', 'cancel'], hosts, (50, 8))
        labels = [text[2:] for _, _, text, _ in frames[-1] if text[2:] in hosts]
        self.assertEqual(labels, ['alpha', 'Bravo', 'charlie', 'delta', 'zeta'])

    def test_new_host_requires_tag_validation_and_errors_remain_cancellable(self):
        for result, expected in (('', 'new.lab'), ('Host is not enabled', None)):
            with self.subTest(result=result):
                validate = Mock(return_value=result)
                selected, frames = self.choose([*'new.lab', 'enter', 'cancel'], [], validate=validate)
                self.assertEqual(selected, expected)
                validate.assert_called_once_with('new.lab')
                if result:
                    self.assertTrue(any(text == result for frame in frames for _, _, text, _ in frame))
        validate = Mock(side_effect=RuntimeError('tag probe failed'))
        selected, frames = self.choose([*'new.lab', 'enter', 'cancel'], [], validate=validate)
        self.assertIsNone(selected)
        self.assertTrue(any(text == 'tag probe failed' for frame in frames for _, _, text, _ in frame))

    def test_ctrl_o_help_has_its_own_line_even_on_a_narrow_screen(self):
        for hosts in ([], self.hosts):
            for width in (32, 80, 150):
                with self.subTest(hosts=hosts, width=width):
                    _, frames = self.choose(['cancel'], hosts, (width, 24))
                    help_lines = [(y, text) for y, _, text, _ in frames[0]
                                  if text.startswith('Ctrl+O')]
                    self.assertEqual(len(help_lines), 1)
                    self.assertEqual(help_lines[0][0], 3)
                    self.assertIn('Ctrl+O connect typed', help_lines[0][1])

    def test_ctrl_o_uses_literal_input_without_tag_checks_or_cache_writes(self):
        for query, hosts in (('prod', ['sibils-prod-ai']), ('192.0.2.10', ['server']),
                             ('alice@new-server', []), ('2001:db8::1', []), ('prod-é', [])):
            with (self.subTest(query=query, hosts=hosts),
                  patch.object(ssh, 'configured_tag') as tag,
                  patch.object(ssh, 'write_host_cache') as cache):
                selected, _ = self.choose([*query, 'connect_typed'], hosts,
                                          validate=ssh.validate_picker_host)
                self.assertEqual(selected, query)
                tag.assert_not_called()
                cache.assert_not_called()

    def test_invalid_ctrl_o_input_stays_open_and_can_be_corrected_or_cancelled(self):
        for query in ('', 'two hosts', '-option'):
            with self.subTest(query=query):
                selected, frames = self.choose([*query, 'connect_typed', 'cancel'], [],
                                               validate=ssh.validate_picker_host)
                self.assertIsNone(selected)
                self.assertTrue(any('Enter a valid SSH hostname' in text
                                    for frame in frames for _, _, text, _ in frame))
        self.assertEqual(self.choose(['connect_typed', *'new-server', 'connect_typed'], [],
                                     validate=ssh.validate_picker_host)[0], 'new-server')

    def test_small_sizes_wide_characters_and_controls_stay_inside_terminal(self):
        hosts = ['机器-prod', 'cafe\u0301', 'long-host-' * 8, 'bad\x1b\x07host']
        for width, height in ((1, 1), (10, 5), (24, 12), (100, 24)):
            with self.subTest(size=(width, height)):
                _, frames = self.choose(['cancel'], hosts, (width, height))
                for y, x, text, _ in frames[0]:
                    self.assertLess(y, height)
                    self.assertLess(x + host_picker.cell_width(text), width)
                    self.assertNotIn('\x1b', text)
                    self.assertNotIn('\x07', text)
        self.assertEqual(host_picker.cell_width('机e\u0301'), 3)
        self.assertEqual(host_picker.clip('机e\u0301x', 3), '机e\u0301')

    def test_idle_loop_does_not_repaint_until_resize_or_input(self):
        _, frames = self.choose([None, None, (100, 25), None, 'cancel'])
        self.assertEqual(len(frames), 2)


class WindowsConsoleTests(unittest.TestCase):
    def console(self):
        console = Mock()
        console.GetStdHandle.side_effect = lambda handle: handle

        def read_mode(_handle, mode):
            target = windows_picker.ctypes.cast(
                mode, windows_picker.ctypes.POINTER(windows_picker.wintypes.DWORD))
            target.contents.value = 0x247
            return True

        console.GetConsoleMode.side_effect = read_mode
        console.SetConsoleMode.return_value = True
        return console

    def test_console_restores_modes_and_screen_on_success_and_error(self):
        for failure in (False, True):
            with self.subTest(failure=failure):
                output, console = io.StringIO(), self.console()
                with (patch.object(sys.stdin, 'isatty', return_value=True),
                      redirect_stdout(output), patch.object(output, 'isatty', return_value=True),
                      patch.object(windows_picker.ctypes, 'WinDLL', return_value=console, create=True)):
                    try:
                        with windows_picker.ConsoleScreen() as screen:
                            screen.draw([(0, 0, 'selected-host', 'selected')])
                            if failure:
                                raise RuntimeError('picker failed')
                    except RuntimeError as error:
                        self.assertTrue(failure)
                        self.assertEqual(str(error), 'picker failed')
                self.assertIn('\x1b[?1049h', output.getvalue())
                self.assertTrue(output.getvalue().endswith('\x1b[?1049l'))
                self.assertEqual(console.SetConsoleMode.call_args_list[-2].args, (-11, 0x247))
                self.assertEqual(console.SetConsoleMode.call_args_list[-1].args, (-10, 0x247))

    def test_partial_setup_failure_restores_input_mode_before_fallback(self):
        console = self.console()
        console.SetConsoleMode.side_effect = [True, False, True, True]
        output = io.StringIO()
        with (patch.object(sys.stdin, 'isatty', return_value=True),
              redirect_stdout(output), patch.object(output, 'isatty', return_value=True),
              patch.object(windows_picker.ctypes, 'WinDLL', return_value=console, create=True)):
            with self.assertRaises(windows_picker.ConsoleUnavailable):
                with windows_picker.ConsoleScreen():
                    self.fail('Setup should fail before entering the grid')
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(console.SetConsoleMode.call_args_list[-1].args, (-10, 0x247))

    def test_key_decoding_and_nonblocking_resize_poll(self):
        cases = ((['\xe0', 'M'], 'right'), (['\0', 'I'], 'page_up'),
                 (['\r'], 'enter'), (['\x1b'], 'cancel'), (['\x03'], 'cancel'),
                 (['\x0f'], 'connect_typed'), (['\0', '\x0f'], 'back_tab'),
                 (['\x08'], 'backspace'), (['\x15'], 'clear'), (['é'], 'é'),
                 (['\ud83d', '\udef0'], '🛰'))
        for characters, expected in cases:
            with self.subTest(characters=characters):
                keyboard = SimpleNamespace(kbhit=lambda: True, getwch=Mock(side_effect=characters))
                with patch.dict(sys.modules, {'msvcrt': keyboard}):
                    self.assertEqual(windows_picker.ConsoleScreen.read_key(), expected)
        with (patch.dict(sys.modules, {'msvcrt': SimpleNamespace(kbhit=lambda: False)}),
              patch.object(windows_picker.time, 'sleep') as sleep):
            self.assertIsNone(windows_picker.ConsoleScreen.read_key())
        sleep.assert_called_once_with(0.05)


class PickerDispatchTests(unittest.TestCase):
    def test_default_windows_picker_shows_ctrl_o_and_connects_the_typed_destination(self):
        for query, hosts in (('prod', ['sibils-prod-ai']), ('alice@new-server', [])):
            screen = Screen([*query, 'connect_typed'])
            with (self.subTest(query=query),
                  patch.object(sys, 'platform', 'win32'),
                  patch.object(sys, 'argv', ['bin/ssh_picker.py', '--pick']),
                  patch.object(sys.stdin, 'isatty', return_value=True),
                  patch.object(sys.stdout, 'isatty', return_value=True),
                  patch.object(ssh, 'target_hosts', return_value=hosts),
                  patch.object(ssh, 'pick_fzf') as fallback,
                  patch.object(ssh, 'configured_tag') as tag,
                  patch.object(ssh, 'connect', return_value=17) as connect,
                  patch.object(windows_picker, 'ConsoleScreen') as console):
                console.return_value.__enter__.return_value = screen
                self.assertEqual(ssh.main(), 17)
                connect.assert_called_once_with(query, None)
                fallback.assert_not_called()
                tag.assert_not_called()
                self.assertIn('Ctrl+O connect typed hostname, IP or user@host',
                              [text for _, _, text, _ in screen.frames[0]])

    def test_interactive_windows_uses_grid_without_fzf_or_linux_imports(self):
        screen = Screen(['right', 'enter'], (60, 12))
        hosts = [f'host-{index:02}' for index in range(12)]
        with (patch.object(sys, 'platform', 'win32'),
              patch.object(sys.stdin, 'isatty', return_value=True),
              patch.object(sys.stdout, 'isatty', return_value=True),
              patch.object(ssh, 'target_hosts', return_value=hosts) as listing,
              patch.object(ssh, 'pick_fzf') as fallback,
              patch.object(windows_picker, 'ConsoleScreen') as console,
              patch.dict(sys.modules, {'dalftui.linux.ssh_picker': None})):
            console.return_value.__enter__.return_value = screen
            self.assertEqual(ssh.pick_host(refresh=True), 'host-06')
        listing.assert_called_once_with(refresh=True)
        fallback.assert_not_called()
        console.return_value.__exit__.assert_called_once()

    def test_unavailable_console_falls_back_with_the_same_hosts(self):
        with (patch.object(sys, 'platform', 'win32'),
              patch.object(sys.stdin, 'isatty', return_value=True),
              patch.object(sys.stdout, 'isatty', return_value=True),
              patch.object(ssh, 'target_hosts', return_value=['server']),
              patch.object(ssh, 'pick_fzf', return_value='server') as fallback,
              patch.object(windows_picker, 'ConsoleScreen') as console):
            console.return_value.__enter__.side_effect = windows_picker.ConsoleUnavailable('No console')
            self.assertEqual(ssh.pick_host(), 'server')
        fallback.assert_called_once_with(['server'])

    def test_explicit_fzf_keeps_refresh_and_connection_dispatch(self):
        with (patch.object(sys, 'argv', ['ssh_picker.py', '--fzf', '--refresh-hosts']),
              patch.object(ssh, 'pick_fzf', return_value='server') as choose,
              patch.object(ssh, 'pick_host') as grid,
              patch.object(ssh, 'connect', return_value=17) as connect):
            self.assertEqual(ssh.main(), 17)
        choose.assert_called_once_with(refresh=True)
        grid.assert_not_called()
        connect.assert_called_once_with('server', None)


@unittest.skipUnless(sys.platform == 'win32', 'Requires the native Windows console')
class NativeConsoleTests(unittest.TestCase):
    def test_real_console_renders_all_hosts_and_restores_modes(self):
        program = '''import ctypes, msvcrt, sys
from ctypes import wintypes
from unittest.mock import patch
from dalftui import host_picker
from dalftui.windows.host_picker import ConsoleScreen
original_output = sys.stdout
console = ctypes.WinDLL('kernel32', use_last_error=True)
console.SetStdHandle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
console.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
class Coord(ctypes.Structure):
    _fields_ = [('x', wintypes.SHORT), ('y', wintypes.SHORT)]
console.ReadConsoleOutputCharacterW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR,
    wintypes.DWORD, Coord, ctypes.POINTER(wintypes.DWORD)]
with open('CONIN$', 'r') as input_stream, open('CONOUT$', 'w') as output_stream:
    sys.stdin, sys.stdout = input_stream, output_stream
    handles = [msvcrt.get_osfhandle(stream.fileno()) for stream in (input_stream, output_stream)]
    modes = []
    for identifier, handle in zip((-10, -11), handles):
        assert console.SetStdHandle(identifier, handle)
        mode = wintypes.DWORD()
        assert console.GetConsoleMode(handle, ctypes.byref(mode))
        modes.append(mode.value)
    hosts = [f'host-{index:02}' for index in range(45)]
    with ConsoleScreen() as screen:
        def read_key():
            width, height = screen.size()
            buffer = ctypes.create_unicode_buffer(width * height + 1)
            count = wintypes.DWORD()
            with open('CONOUT$', 'w') as active:
                handle = msvcrt.get_osfhandle(active.fileno())
                assert console.ReadConsoleOutputCharacterW(handle, buffer, width * height,
                    Coord(0, 0), ctypes.byref(count)), ctypes.get_last_error()
            for host in hosts:
                assert host in buffer.value, (host, buffer.value)
            assert 'Ctrl+O connect typed hostname, IP or user@host' in buffer.value, buffer.value
            return 'cancel'
        with patch.object(screen, 'read_key', side_effect=read_key):
            assert host_picker.pick(screen, hosts, lambda _host: '') is None
    for handle, expected in zip(handles, modes):
        mode = wintypes.DWORD()
        assert console.GetConsoleMode(handle, ctypes.byref(mode))
        assert mode.value == expected, (mode.value, expected)
sys.stdout = original_output
print('console verified')
'''
        result = subprocess.run(
            [sys.executable, '-B', '-c', program], cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=15,
            creationflags=0x08000000)  # CREATE_NO_WINDOW: use a private, invisible console.
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'console verified')


if __name__ == '__main__':
    unittest.main()
