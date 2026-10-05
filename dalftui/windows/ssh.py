"""Native Windows SSH console integration and temporary configuration ACLs."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re
import subprocess
import sys


def ssh_executable():
    native = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/OpenSSH/ssh.exe'
    return str(native) if native.is_file() else 'ssh'


def host_cache_path():
    directory = os.environ.get('LOCALAPPDATA', '')
    if not directory or not Path(directory).is_absolute():
        return None
    return Path(directory) / 'dalftui/hosts-cache.json'


def set_terminal_title(title):
    """Set an interactive console's title even when remote tmux emits none."""
    if not sys.stdout.isatty():
        return
    # Use the Unicode console API without depending on VT output mode. The
    # Windows-only windll loader is unavailable to Pylint running on Linux.
    try:
        set_title = ctypes.windll.kernel32.SetConsoleTitleW  # pylint: disable=no-member
        set_title.argtypes = [wintypes.LPCWSTR]
        set_title.restype = wintypes.BOOL
        set_title(''.join(char for char in title if char.isprintable()))
    except OSError:
        # A missing console must not prevent the SSH connection.
        pass


def secure_ssh_directory(path):
    """Give temporary Windows configs an ACL that Windows OpenSSH accepts."""
    # Python 3.13+ uses an OWNER RIGHTS ACE for private temporary directories.
    # Windows OpenSSH treats that ACE as a grant to another user. Replace it
    # with the current account's explicit SID, keeping the directory private.
    system = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32'
    try:
        identity = subprocess.run([str(system / 'whoami.exe'), '/user', '/fo', 'csv', '/nh'],
                                  capture_output=True, check=True, timeout=5)
        match = re.search(rb'S-1-5(?:-[0-9]+)+', identity.stdout.replace(b'\0', b''))
        if not match:
            raise RuntimeError('Could not determine the Windows account SID.')
        account = match[0].decode('ascii')
        subprocess.run([str(system / 'icacls.exe'), str(path), '/inheritance:r', '/grant:r',
                        f'*{account}:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F',
                        '/remove:g', '*S-1-3-4'], capture_output=True, check=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError('Could not secure the temporary Windows SSH configuration.') from error
