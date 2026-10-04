"""Frozen authenticated bridge contract deployed before explicit versioning.

This fixture deliberately imports no dalftui implementation or constants. Keep
its behavior and examples unchanged when introducing future protocol versions;
add another fixture for another historical peer instead. Authentication arrived
before version metadata, so these unversioned messages are known protocol v1.
Earlier unauthenticated bridges are not represented as compatible peers.
"""
import json
import re
import secrets
import socket


SOCKET_ENV = 'DALFTUI_EDITOR_SOCKET'
TOKEN_ENV = 'DALFTUI_EDITOR_TOKEN'
MAX_REQUEST = 16384
TOKEN = '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
FOLDER = '/home/alice/project.with.dot "quoted" $cash #?é'
REQUEST_LINE = (
    b'{"folder": "/home/alice/project.with.dot \\"quoted\\" $cash #?\\u00e9", '
    b'"token": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"}\n'
)
SUCCESS_LINE = b'{"ok": true}\n'
ERROR_LINE = b'{"error": "Could not start VS Code."}\n'


def valid_token(token):
    return isinstance(token, str) and re.fullmatch(r'[0-9a-f]{64}', token) is not None


def validate_folder(folder):
    if not isinstance(folder, str) or not folder.startswith('/') or '\0' in folder:
        raise ValueError('The editor folder must be an absolute path.')


def read_message(connection):
    data = bytearray()
    while len(data) <= MAX_REQUEST:
        chunk = connection.recv(min(4096, MAX_REQUEST + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
        if b'\n' in chunk:
            break
    if len(data) > MAX_REQUEST or not data.endswith(b'\n'):
        raise ValueError('Invalid editor request.')
    message = json.loads(data)
    if not isinstance(message, dict):
        raise ValueError('Invalid editor request.')
    return message


def send_message(connection, message):
    connection.sendall(json.dumps(message).encode() + b'\n')


def request(endpoint, folder, token):
    """The old remote client's real wire exchange and response interpretation."""
    validate_folder(folder)
    tcp = endpoint.startswith('tcp:')
    if tcp:
        match = re.fullmatch(r'tcp:127\.0\.0\.1:([0-9]+)', endpoint)
        if not match or not 0 < int(match[1]) < 65536:
            raise ValueError('Invalid loopback editor endpoint.')
    if not valid_token(token):
        raise RuntimeError('Missing or invalid editor bridge credentials. '
                           'Reconnect using the dalftui SSH launcher.')
    with socket.socket(socket.AF_INET if tcp else socket.AF_UNIX) as connection:
        connection.settimeout(5)
        connection.connect(('127.0.0.1', int(match[1])) if tcp else endpoint)
        send_message(connection, {'folder': folder, 'token': token})
        response = read_message(connection)
    if response.get('ok') is not True:
        raise RuntimeError(response.get('error') or 'The VS Code request failed.')


def serve_connection(connection, expected_token, *, launch_error=None):
    """The old laptop's authentication and response, without starting an editor."""
    message = read_message(connection)
    try:
        supplied = message.get('token')
        if (not valid_token(supplied)
                or not secrets.compare_digest(supplied, expected_token)):
            raise ValueError('Invalid editor bridge credentials. '
                             'Reconnect using the dalftui SSH launcher.')
        validate_folder(message.get('folder'))
        if launch_error is not None:
            raise RuntimeError(launch_error)
        response = {'ok': True}
    except (ValueError, RuntimeError) as error:
        response = {'error': str(error)}
    send_message(connection, response)
    return message
