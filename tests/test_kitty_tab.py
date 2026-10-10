"""Open picked SSH hosts in a new tab of the kitty window where Ctrl+B F2 was pressed."""
import json
import os
from pathlib import Path
import select
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import test_install as install_tests
from dalftui.linux import ssh_picker

KITTY = {'KITTY_LISTEN_ON': 'unix:/run/user/1000/kitty-42', 'KITTY_WINDOW_ID': '7', 'TERM': 'xterm-kitty'}


@unittest.skipUnless(sys.platform.startswith('linux'), 'The picker reads the tmux client through /proc')
class KittyTabTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='dalftui-kitty-')
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.record = self.directory / 'kitten.json'
        kitten = self.directory / 'kitten'
        kitten.write_text(f'#!{sys.executable}\nimport json, os, sys\n'
                          f'open({str(self.record)!r}, "w").write(json.dumps(sys.argv[1:]))\n'
                          'sys.stderr.write(os.environ.get("TEST_KITTEN_ERROR", ""))\n'
                          'sys.exit(int(os.environ.get("TEST_KITTEN_STATUS", "0")))\n', encoding='utf-8')
        kitten.chmod(0o755)
        path = patch.dict(os.environ, {'PATH': f'{self.directory}{os.pathsep}{os.environ["PATH"]}'})
        path.start()
        self.addCleanup(path.stop)

    def client(self, env):
        """A stand-in tmux client; the picker reads its environment through /proc."""
        process = subprocess.Popen(['sleep', '30'], env=env)
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        return process.pid

    def test_clients_outside_kitty_or_without_a_socket_get_an_error(self):
        plain = {name: value for name, value in os.environ.items() if not name.startswith('KITTY_')}
        for env in (plain, dict(plain, KITTY_WINDOW_ID='7'), {**plain, **KITTY, 'TERM': 'xterm-256color'}):
            pid = self.client(env)
            with self.assertRaisesRegex(RuntimeError, 'no kitty remote control socket'):
                ssh_picker.open_window('prod', client_pid=pid)
        with self.assertRaisesRegex(RuntimeError, 'no kitty remote control socket'):
            ssh_picker.open_window('prod')
        self.assertFalse(self.record.exists())

    def test_launch_failures_are_reported(self):
        pid = self.client(dict(os.environ, **KITTY))
        for env, expected in (({'TEST_KITTEN_STATUS': '1', 'TEST_KITTEN_ERROR': 'Error: No matching windows'},
                               'No matching windows'),
                              ({'TEST_KITTEN_STATUS': '1'}, 'Could not open a kitty tab')):
            with self.subTest(expected=expected), patch.dict(os.environ, env):
                with self.assertRaisesRegex(RuntimeError, expected):
                    ssh_picker.open_window('prod', client_pid=pid)
        with patch.object(ssh_picker.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'kitten was not found in PATH'):
                ssh_picker.open_window('prod', client_pid=pid)


@unittest.skipUnless(sys.platform.startswith('linux'), 'The picker reads the tmux client through /proc')
class KittyPickerKeyTests(install_tests.TmuxFixture):
    profile = 'desktop'

    def test_prefix_f2_passes_the_pressing_clients_pid_to_the_picker(self):
        import pty  # pylint: disable=import-outside-toplevel
        self.start()
        self.do_reload()
        record, recorder = self.directory / 'picker.json', self.directory / 'record.py'
        recorder.write_text('import json, os, sys\n'
                            'open(sys.argv[1], "w").write(json.dumps([os.getcwd(), *sys.argv[2:]]))\n')
        # The popup runs this instead of uv and the picker.
        self.tmux('set-environment', '-gh', 'DALFTUI_PYTHON',
                  shlex.join([sys.executable, str(recorder), str(record)]))
        pid, client = pty.fork()
        if not pid:
            os.execvpe('tmux', [*self.command, 'attach', '-t', 'verify'],
                       {**self.env, **KITTY, 'TERM': 'xterm-256color'})
        self.addCleanup(os.waitpid, pid, 0)
        self.addCleanup(os.close, client)

        def answer(seconds, keys=b''):
            os.write(client, keys)
            until = time.monotonic() + seconds
            while time.monotonic() < until and not record.exists():
                if select.select([client], [], [], 0.1)[0]:
                    os.read(client, 65536)
        answer(2)
        answer(0.3, b'\x02')
        answer(10, b'\x1bOQ')  # F2
        self.assertEqual(json.loads(record.read_text()),
                         [str(self.repo), 'bin/ssh_picker.py', '--client-pid', str(pid)])


if __name__ == '__main__':
    unittest.main()
