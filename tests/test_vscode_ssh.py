"""Open a remote folder through a real SSH forward to this machine's editor bridge.

The test starts an unprivileged sshd on loopback, so it only runs when
DALFTUI_TEST_SSHD=1. macOS CI sets it to cover Apple's ssh client as the desktop.
"""
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SSHD = '/usr/sbin/sshd'
SSH = '/usr/bin/ssh'


def gnu_stat():
    try:
        return subprocess.run(['stat', '--version'], capture_output=True, check=False).returncode == 0
    except OSError:
        return False


@unittest.skipUnless(os.environ.get('DALFTUI_TEST_SSHD') == '1', 'Set DALFTUI_TEST_SSHD=1 to start a loopback sshd')
@unittest.skipIf(sys.platform == 'win32', 'The desktop bridge is tested natively on Linux and macOS')
@unittest.skipUnless(os.access(SSHD, os.X_OK) and os.access(SSH, os.X_OK) and shutil.which('ssh-keygen')
                     and shutil.which('tmux') and gnu_stat(), 'Needs sshd, ssh, ssh-keygen, tmux and GNU stat')
class RealForwardTests(unittest.TestCase):
    def setUp(self):
        # Keep the remote socket path short: macOS limits Unix socket paths to 104 bytes.
        self.directory = Path(tempfile.mkdtemp(prefix='dalftui-sshd-', dir='/tmp'))
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)
        for key in ('host', 'user'):
            subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(self.directory / key)],
                           check=True)
        (self.directory / 'authorized_keys').write_text((self.directory / 'user.pub').read_text())
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        # The server needs an installed dalftui and GNU stat; sshd sessions do not inherit this PATH.
        xdg = self.directory / 'xdg'
        xdg.mkdir()
        (xdg / 'dalftui').symlink_to(ROOT)
        remote_bin = self.directory / 'remote-bin'
        remote_bin.mkdir()
        (remote_bin / 'python3').symlink_to(sys.executable)
        remote_path = ':'.join([str(remote_bin), os.path.dirname(shutil.which('stat')),
                                os.path.dirname(shutil.which('tmux')), '/usr/bin:/bin'])
        config = self.directory / 'sshd_config'
        config.write_text(f'Port {port}\nListenAddress 127.0.0.1\nHostKey {self.directory}/host\n'
                          f'PidFile {self.directory}/sshd.pid\nAuthorizedKeysFile {self.directory}/authorized_keys\n'
                          'PasswordAuthentication no\nKbdInteractiveAuthentication no\nStrictModes no\n'
                          f'SetEnv PATH={remote_path} XDG_CONFIG_HOME={xdg}\n')
        self.sshd_log = self.directory / 'sshd.log'
        with open(self.sshd_log, 'w', encoding='utf-8') as log:
            sshd = subprocess.Popen([SSHD, '-D', '-e', '-f', str(config)], stderr=log)
        self.addCleanup(sshd.wait, 5)
        self.addCleanup(sshd.terminate)
        until = time.monotonic() + 5
        while sshd.poll() is None and time.monotonic() < until:
            try:
                socket.create_connection(('127.0.0.1', port), timeout=1).close()
                break
            except OSError:
                time.sleep(0.05)
        self.assertIsNone(sshd.poll(), self.sshd_log.read_text())

        home = self.directory / 'home'
        (home / '.ssh').mkdir(parents=True)
        (home / '.ssh/config').write_text(
            f'Host dalftui-loop\n    HostName 127.0.0.1\n    Port {port}\n    User {os.environ.get("USER")}\n'
            f'    IdentityFile {self.directory}/user\n    IdentitiesOnly yes\n'
            f'    UserKnownHostsFile {self.directory}/known_hosts\n    StrictHostKeyChecking accept-new\n'
            '    BatchMode yes\n')
        # ssh reads the passwd home, not $HOME; the wrapper keeps the runner's ~/.ssh out.
        fake_bin = self.directory / 'bin'
        fake_bin.mkdir()
        (fake_bin / 'ssh').write_text(f'#!/bin/sh\nexec {SSH} -F "$HOME/.ssh/config" "$@"\n')
        self.log = self.directory / 'editor.json'
        (fake_bin / 'code').write_text(f'#!{sys.executable}\nimport json, os, pathlib, sys\n'
                                       'pathlib.Path(os.environ["EDITOR_TEST_LOG"]).write_text(json.dumps(sys.argv[1:]))\n')
        for program in ('ssh', 'code'):
            (fake_bin / program).chmod(0o755)
        self.env = dict(os.environ, HOME=str(home), PATH=f'{fake_bin}:{os.environ["PATH"]}',
                        EDITOR_TEST_LOG=str(self.log))
        for name in ('TMUX', 'TMUX_PANE', 'DALFTUI_EDITOR_SOCKET', 'DALFTUI_EDITOR_TOKEN'):
            self.env.pop(name, None)

    def test_remote_request_opens_folder_through_the_forwarded_socket(self):
        folder = "/home/alice/project.with.dot 'quoted' $cash #?é"
        # The remote shell sends the request F3 would send; F3 routing itself needs Linux /proc.
        # An absolute interpreter avoids macOS path_helper putting an older python3 first.
        client = (f'import os, sys; sys.path.insert(0, {str(ROOT)!r}); from dalftui import vscode; '
                  f'vscode.request(os.environ["DALFTUI_EDITOR_SOCKET"], {folder!r}, '
                  'os.environ["DALFTUI_EDITOR_TOKEN"]); print("REQUEST-OK")')
        before = set(Path('/tmp').glob('dalftui-editor-*'))
        result = subprocess.run([sys.executable, str(ROOT / 'bin/ssh_picker.py'), '--connect', 'dalftui-loop', '--plain'],
                                env=self.env, input=f'{shlex.quote(sys.executable)} -c {shlex.quote(client)}\nexit\n',
                                capture_output=True, text=True, timeout=60)
        details = f'{result.stdout}\n{result.stderr}\n{self.sshd_log.read_text()}'
        self.assertEqual(result.returncode, 0, details)
        self.assertIn('REQUEST-OK', result.stdout, details)
        self.assertEqual(json.loads(self.log.read_text()),
                         ['--new-window', '--folder-uri', 'vscode-remote://ssh-remote+dalftui-loop/home/alice/'
                          'project.with.dot%20%27quoted%27%20%24cash%20%23%3F%C3%A9'])
        self.assertEqual(set(Path('/tmp').glob('dalftui-editor-*')), before)


if __name__ == '__main__':
    unittest.main()
