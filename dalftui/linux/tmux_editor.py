"""Route pane folders using the triggering Linux tmux client's environment."""
import os
from pathlib import Path
import subprocess

from bridge_protocol import SOCKET_ENV, TOKEN_ENV


def client_environment(pid):
    # A persistent tmux server/session can retain another client's old SSH socket.
    # Read the triggering attach client's initial environment instead.
    values = Path(f'/proc/{pid}/environ').read_bytes().split(b'\0')
    return dict(os.fsdecode(item).split('=', 1) for item in values if b'=' in item)


def open_pane(pane, client):
    from .. import vscode

    result = subprocess.run(['tmux', 'display-message', '-p', '-t', pane, '#{pane_current_path}'],
                            capture_output=True, text=True, check=True, timeout=5)
    folder = result.stdout.removesuffix('\n')
    env = client_environment(client)
    if env.get(SOCKET_ENV):
        vscode.request(env[SOCKET_ENV], folder, env.get(TOKEN_ENV))
    elif env.get('SSH_CONNECTION') or env.get('SSH_CLIENT'):
        raise RuntimeError('For remote VS Code, reconnect using the dalftui SSH launcher '
                           'in your local dalftui terminal.')
    else:
        vscode.launch(folder, env=env)


def notify_error(message, client_tty=None):
    command = ['tmux', 'display-message', '-d', '8000']
    if client_tty:
        command += ['-c', client_tty]
    try:
        subprocess.run([*command, message.replace('#', '##')], timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        pass
