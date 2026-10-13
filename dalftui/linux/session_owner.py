"""Keep one tmux client per session, and route its SSH agent through a stable alias.

config/tmux.conf runs ``sync`` from tmux hooks when a client attaches to or
switches into a session, when a client detaches, and when a session closes:

- The client that joined a session takes it over: the session's other clients
  are detached. Clients of other sessions are never touched. A client that tmux
  itself moved because its own session closed (detach-on-destroy off) is not a
  newcomer: it leaves, and the session keeps its client. Only a positive record
  of such a move makes a client leave; without one, the newest arrival wins.
- A session started by the SSH launcher on an installed host has a private
  alias path, recorded in its ``@dalftui_agent_alias`` option. Its shells use
  ``SSH_AUTH_SOCK=<alias>`` from startup: the launcher creates the alias for its
  own forwarded agent before the first pane starts. Afterwards the alias points
  at the forwarded agent socket of the session's attached client, read from
  that client's own process environment, and is absent while no client with an
  agent is attached. The session's update-environment leaves SSH_AUTH_SOCK out,
  so attaching never copies a raw socket into the environment of new panes.

Decisions come from tmux's current state under a lock, never from the event
alone, so a late detach of a dead client cannot remove a newer owner's alias.
The hooks record the newest arrival in each session synchronously, so the
order in which their background runs take the lock does not matter.
Requires Linux /proc for client environments; Python 3.8 or newer.
"""
import argparse
import contextlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import time

HOOKS_OPTION = '@dalftui_agent_hooks'
ALIAS_OPTION = '@dalftui_agent_alias'
# Set synchronously by the hooks (config/tmux.conf), in tmux's event order: the
# newest client to arrive in the session, and globally "<session ID> <client>"
# for an arrival that a session closure followed at once, as tmux's moves are.
JOINED_OPTION = '@dalftui_joined'
MOVED_OPTION = '@dalftui_moved'
AGENT = 'SSH_AUTH_SOCK'
KEY = re.compile(r'[0-9a-f]{32}\Z')
# Alias paths are passed through tmux commands and shells as plain words.
SAFE_PATH = re.compile(r'/[-A-Za-z0-9/._]*\Z')
SESSION_ID = re.compile(r'\\?(\$[0-9]+)\Z')
# The pause keeps the message readable: the SSH launcher closes a window that
# exits 0 at once. The launcher's own takeover shows the same message and pause.
TAKEOVER = "printf '%s\\n' 'Another terminal took over this tmux session.'; sleep 3"
DISPLACED = ("printf '%s\\n' 'Your tmux session closed, and the session tmux moved you to"
             " is in use by another terminal.'; sleep 3")
# client_last_session is set by a switch, never by a first attach, and tmux
# clears it when it moves a client out of a closing session. It is a name,
# such as "0", which #{?...} would read as false.
CLIENT_FORMAT = ('#{client_pid} #{client_created} #{client_activity}'
                 ' #{!=:#{client_last_session},} #{session_id} #{client_name}')
RECORD_VERSION = 1
# The launcher creates an alias just before new-session; the first sync claims it.
PENDING_SECONDS = 60
ERROR_FILE = 'last-error'
# First line of the installed ~/.tmux.conf (setup.MARKER); setup needs Python 3.11.
LOADER_MARKER = '# Managed by dalftui.'


class TmuxError(RuntimeError):
    pass


def tmux(*args, check=True):
    try:
        result = subprocess.run(['tmux', *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as error:
        raise TmuxError(str(error)) from error
    if check and result.returncode:
        raise TmuxError(result.stderr.strip() or f'tmux {args[0]} failed')
    return result.stdout


# Private directories --------------------------------------------------------

def directory_names():
    return ('dalftui-agent', f'dalftui-agent-{os.getuid()}')


def candidate_directories(env=None):
    """Private alias directories, preferred first: the runtime directory, then /tmp."""
    env = os.environ if env is None else env
    uid = os.getuid()
    bases = []
    runtime = env.get('XDG_RUNTIME_DIR', '')
    if runtime.startswith('/'):
        # A runtime directory that is gone (logind removed it, or a test's
        # was cleaned up) means aliases are off, never another user's place.
        if not os.path.lexists(runtime):
            return []
        bases.append(os.path.normpath(runtime))
    bases.append(f'/run/user/{uid}')
    candidates = []
    for base in bases:
        try:
            info = os.stat(base)
        except OSError:
            continue
        if stat.S_ISDIR(info.st_mode) and info.st_uid == uid and not info.st_mode & 0o077:
            candidates.append(os.path.join(base, 'dalftui-agent'))
            break
    # /tmp is shared: the name is predictable, so ownership and mode are verified.
    candidates.append(f'/tmp/dalftui-agent-{uid}')
    return candidates


def private_directory(path):
    """A real directory owned by this user that nobody else can enter."""
    if os.path.basename(path) not in directory_names():
        return False
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return (stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and not info.st_mode & 0o077)


def ensure_directory(env=None):
    for path in candidate_directories(env):
        try:
            os.mkdir(path, 0o700)
        except FileExistsError:
            pass
        except OSError:
            continue
        if private_directory(path):
            return path
    return None


def alias_parts(alias, restore=False):
    """Return (directory, key) for a well-formed alias in a private directory.

    With restore, recreate its directory when it is one of the candidates and
    has gone, so a session keeps its alias path once the directory is back.
    """
    if not alias or not SAFE_PATH.match(alias) or os.path.normpath(alias) != alias:
        return None
    directory, key = os.path.split(alias)
    if not KEY.match(key):
        return None
    if restore and directory in candidate_directories():
        with contextlib.suppress(OSError):
            os.mkdir(directory, 0o700)
    if not private_directory(directory):
        return None
    return directory, key


@contextlib.contextmanager
def locked(directory):
    """Serialize updates; flock is released even if this process dies."""
    if directory is None:
        yield
        return
    import fcntl
    descriptor = os.open(os.path.join(directory, 'lock'), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


# Records --------------------------------------------------------------------

def record_path(alias):
    return alias + '.json'


def read_record(alias):
    try:
        with open(record_path(alias), encoding='utf-8') as source:
            record = json.load(source)
    except (OSError, ValueError):
        return {}
    return record if isinstance(record, dict) else {}


def write_record(alias, record):
    path = record_path(alias)
    temporary = f'{path}.{secrets.token_hex(4)}.tmp'
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as target:
            json.dump(record, target, sort_keys=True)
            target.write('\n')
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def remove_alias(alias):
    """Remove only our own symlink; the socket it points at belongs to OpenSSH."""
    try:
        if stat.S_ISLNK(os.lstat(alias).st_mode):
            os.unlink(alias)
    except FileNotFoundError:
        pass


def point_alias(alias, target):
    if target is None:
        remove_alias(alias)
        return
    try:
        info = os.lstat(alias)
    except FileNotFoundError:
        info = None
    if info is not None:
        if not stat.S_ISLNK(info.st_mode):
            return
        if os.readlink(alias) == target:
            return
    temporary = f'{alias}.{secrets.token_hex(4)}.tmp'
    os.symlink(target, temporary)
    try:
        os.replace(temporary, alias)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


# Clients --------------------------------------------------------------------

class Client:
    def __init__(self, pid, created, activity, session, name, switched=False):
        self.pid, self.created, self.activity = pid, created, activity
        self.session, self.name, self.switched = session, name, switched

    def recency(self):
        return (self.activity, self.created, self.pid)


def list_clients():
    clients = []
    for line in tmux('list-clients', '-F', CLIENT_FORMAT).splitlines():
        fields = line.split(' ', 5)
        if len(fields) != 6:
            continue
        try:
            pid, created, activity = (int(value) for value in fields[:3])
        except ValueError:
            continue
        clients.append(Client(pid, created, activity, fields[4], fields[5],
                              switched=fields[3] == '1'))
    return clients


def list_sessions():
    """Map each session ID to its alias option, empty when it has none.

    Also return whether tmux may move clients when one of them closes: some
    session's detach-on-destroy (which inherits the global value) is not on.
    no-detached counts: before tmux 3.6 it can move clients into attached sessions.
    """
    sessions = {}
    movable = False
    for line in tmux('list-sessions', '-F',
                     '#{session_id} #{detach-on-destroy} #{' + ALIAS_OPTION + '}').splitlines():
        session, _, rest = line.partition(' ')
        detach, _, alias = rest.partition(' ')
        if session:
            sessions[session] = alias
            movable = movable or detach != 'on'
    return sessions, movable


def process_environment(pid):
    try:
        with open(f'/proc/{pid}/environ', 'rb') as source:
            data = source.read()
    except OSError:
        return None
    return dict(item.split(b'=', 1) for item in data.split(b'\0') if b'=' in item)


def process_start(pid):
    """Start time in clock ticks since boot, which tells a reused PID apart."""
    try:
        with open(f'/proc/{pid}/stat', 'rb') as source:
            data = source.read()
        return int(data[data.rindex(b')') + 2:].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def client_origin(environment):
    connection = (environment or {}).get(b'SSH_CONNECTION')
    if connection is None:
        return 'local'
    address = os.fsdecode(connection).split(' ', 1)[0]
    return address if re.fullmatch(r'[0-9A-Za-z.:%_-]+', address) else None


def inside_directories(path, directories):
    for candidate in (path, os.path.realpath(path)):
        if os.path.dirname(os.path.normpath(candidate)) in directories:
            return True
    return False


def agent_socket(environment, alias, directories):
    """The client's own forwarded agent socket, or None when it has none."""
    value = (environment or {}).get(AGENT.encode())
    if not value:
        return None
    path = os.fsdecode(value)
    if not path.startswith('/') or '\0' in path:
        return None
    # Never point an alias at itself or at another alias.
    if os.path.normpath(path) == alias or inside_directories(path, set(directories)):
        return None
    try:
        info = os.stat(path)
    except OSError:
        return None
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
        return None
    return path


# Synchronization -------------------------------------------------------------

def current_server():
    """Socket path and PID of the server this process belongs to, from $TMUX."""
    # $TMUX is "<socket path>,<server pid>,<session index>"; the path may contain commas.
    socket = os.environ.get('TMUX', '').rpartition(',')[0]
    socket, _, pid = socket.rpartition(',')
    try:
        return {'socket': socket, 'pid': int(pid)} if socket else None
    except ValueError:
        return None


def server_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        with open(f'/proc/{pid}/comm', encoding='utf-8', errors='replace') as source:
            return source.read().startswith('tmux')
    except OSError:
        return True


def session_option(session, name):
    return tmux('show-options', '-t', session, '-qv', name, check=False).strip()


def moved_arrival():
    # Some tmux versions escape "$" when showing an option.
    return tmux('show-options', '-gqv', MOVED_OPTION, check=False).strip().replace('\\$', '$')


def enforce(session, hook_client, members, movable):
    """Leave one client in a session: its newest arrival, unless tmux moved it there.

    Background syncs take the lock in any order, so the newest arrival comes
    from the option the hooks set synchronously, not from this run's event.
    """
    if len(members) < 2:
        return members
    newest = None
    for name in (session_option(session, JOINED_OPTION), hook_client):
        newest = next((client for client in members if name and client.name == name), None)
        if newest is not None:
            break
    # tmux moves the clients of a closing session (detach-on-destroy off) just
    # before announcing the closure; the hooks record an arrival followed at once
    # by a closure. A switch out of a session that closes at that moment, such
    # as an ops session, looks the same, so the record counts only where
    # detach-on-destroy lets tmux move clients. Without a record, the newcomer
    # chose to come: attaching and switching take over.
    moved = (newest is not None and movable and not newest.switched
             and moved_arrival() == f'{session} {newest.name}')
    if newest is not None and not moved:
        keeper, displaced = newest, None
    else:
        # Without hook_client (tmux before 3.3), keep the most recently active client.
        displaced = newest
        keeper = max((client for client in members if client is not newest), key=Client.recency)
    for client in members:
        if client is not keeper:
            message = DISPLACED if client is displaced else TAKEOVER
            tmux('detach-client', '-t', client.name, '-E', message, check=False)
    return [keeper]


def same_owner(client, owner):
    return (isinstance(owner, dict) and owner.get('pid') == client.pid
            and owner.get('created') == client.created and owner.get('name') == client.name)


def update_alias(alias, session, members, server, directories):
    record = read_record(alias)
    owner = record.get('owner')
    current = None
    if members:
        current = next((client for client in members if same_owner(client, owner)), None)
        if current is None:
            current = max(members, key=Client.recency)
    generation = record.get('generation') if isinstance(record.get('generation'), int) else 0
    if current is None:
        new_owner = None
        target = None
    else:
        environment = process_environment(current.pid)
        target = agent_socket(environment, alias, directories)
        if same_owner(current, owner):
            new_owner = owner
        else:
            new_owner = {'name': current.name, 'pid': current.pid, 'created': current.created,
                         'start': process_start(current.pid), 'origin': client_origin(environment)}
    if new_owner != owner:
        generation += 1
    updated = {'version': RECORD_VERSION, 'server': server, 'session': session,
               'owner': new_owner, 'generation': generation, 'target': target,
               'since': record.get('since') if new_owner == owner else int(time.time())}
    if updated != record:
        write_record(alias, updated)
    point_alias(alias, target)


def collect(server, live, directories):
    """Remove aliases of closed sessions and of tmux servers that have exited.

    Without live (no server, or not run from a hook), only aliases of exited
    servers and unclaimed launcher aliases go. Return how many were removed.
    """
    removed = 0
    for directory in directories:
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        for name in names:
            key = name[:-len('.json')]
            if not name.endswith('.json') or not KEY.match(key):
                continue
            alias = os.path.join(directory, key)
            record = read_record(alias)
            owner_server = record.get('server') if isinstance(record.get('server'), dict) else {}
            pending = record.get('pending')
            if not owner_server and isinstance(pending, int):
                # Created by the launcher; unclaimed if its session never started.
                stale = not 0 <= time.time() - pending < PENDING_SECONDS
            elif live is not None and owner_server == server:
                stale = (record.get('session'), alias) not in live
            else:
                stale = not server_alive(owner_server.get('pid'))
            if stale:
                remove_alias(alias)
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(record_path(alias))
                removed += 1
    return removed


def updated_variables():
    """The global update-environment list without SSH_AUTH_SOCK, for alias sessions."""
    names = tmux('show-options', '-gv', 'update-environment', check=False).split()
    return ' '.join(name for name in names if name != AGENT)


def sync(session=None, hook_client=None, server=None):
    server = server or current_server()
    if server is None:
        raise TmuxError('sync runs from tmux hooks; $TMUX is not set.')
    directory = ensure_directory()
    with locked(directory):
        directories = [directory] if directory else []
        try:
            sessions, movable = list_sessions()
            # The last session's closure: list-clients has no target left.
            clients = list_clients() if sessions else []
        except TmuxError:
            # The server is gone or busy: only remove what belongs to dead servers.
            collect(server, None, directories)
            return 0
        members = {}
        for client in clients:
            members.setdefault(client.session, []).append(client)
        if session in sessions:
            members[session] = enforce(session, hook_client, members.get(session, []), movable)
        live = set()
        pins = []
        variables = None
        for session_id, alias in sessions.items():
            parts = alias_parts(alias, restore=True)
            if parts is None:
                continue
            live.add((session_id, alias))
            update_alias(alias, session_id, members.get(session_id, []), server,
                         {*directories, parts[0]})
            if variables is None:
                variables = updated_variables()
            # Attaching and switching would copy the client's raw socket into
            # the session environment, which new panes inherit: leave it out,
            # and restore the alias wherever an older attach copied one.
            pins += [';', 'set-option', '-t', session_id, 'update-environment', variables,
                     ';', 'set-environment', '-t', session_id, AGENT, alias]
        if pins:
            tmux(*pins[1:], check=False)
        collect(server, live, directories)
        if directory:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(os.path.join(directory, ERROR_FILE))
    return 0


def note_error(error):
    """Hooks discard output, so keep the last failure for "status"."""
    directory = ensure_directory()
    if directory is None:
        return
    path = os.path.join(directory, ERROR_FILE)
    with contextlib.suppress(OSError):
        temporary = f'{path}.{secrets.token_hex(4)}.tmp'
        with open(temporary, 'x', encoding='utf-8') as target:
            target.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} {type(error).__name__}: {error}\n')
        os.replace(temporary, path)


def last_error():
    directory = ensure_directory()
    if directory is None:
        return None
    try:
        with open(os.path.join(directory, ERROR_FILE), encoding='utf-8') as source:
            return source.read().strip()
    except OSError:
        return None


# Commands --------------------------------------------------------------------

def hooks_installed():
    """Whether the server that will hold a new session runs these hooks."""
    try:
        result = subprocess.run(['tmux', 'show-options', '-gqv', HOOKS_OPTION],
                                capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode == 0:
        # A running server may predate the update until bin/reload.
        return result.stdout.strip() == 'on'
    # No server yet: the next one reads the loader that the installer manages.
    try:
        with open(os.path.expanduser('~/.tmux.conf'), encoding='utf-8') as loader:
            return loader.readline().startswith(LOADER_MARKER)
    except (OSError, ValueError):
        return False


def new_alias():
    """Create a fresh alias for a session the launcher is about to create.

    The launcher's tmux client inherits this process's environment, so the
    alias already reaches its forwarded agent when the first shell starts.
    The session's first sync records the client as the owner.
    """
    if not os.path.exists('/proc/self/environ') or not hooks_installed():
        return None
    directory = ensure_directory()
    if directory is None:
        return None
    alias = os.path.join(directory, secrets.token_hex(16))
    if not alias_parts(alias):
        return None
    with locked(directory):
        # kill-server runs no hooks: every login removes what exited servers left.
        collect(None, None, [directory])
        target = agent_socket(dict(os.environb), alias, {directory})
        write_record(alias, {'version': RECORD_VERSION, 'pending': int(time.time()),
                             'server': None, 'session': None, 'owner': None,
                             'generation': 0, 'target': target, 'since': None})
        point_alias(alias, target)
    return alias


def pane_session():
    pane = os.environ.get('TMUX_PANE', '')
    if not pane or not os.environ.get('TMUX'):
        raise TmuxError('Run this inside tmux, or pass --session.')
    # tmux 3.4 escapes "$" in display-message output.
    output = tmux('display-message', '-p', '-t', pane, '#{session_id}').strip()
    match = SESSION_ID.match(output)
    if not match:
        raise TmuxError('Could not read the current tmux session.')
    return match.group(1)


def session_alias(session):
    # show-options -t ignores a missing session; has-session reports it.
    tmux('has-session', '-t', session)
    return tmux('show-options', '-t', session, '-qv', ALIAS_OPTION).strip()


def session_server(session):
    """The server holding a session, identified like $TMUX does in hooks."""
    output = tmux('display-message', '-p', '-t', session, '#{pid},#{socket_path}').strip()
    pid, _, socket = output.partition(',')
    try:
        return {'socket': socket, 'pid': int(pid)} if socket else None
    except ValueError:
        return None


def enable(session):
    """Give an existing session an alias, for shells started before this feature."""
    # Outside tmux, $TMUX does not name the server; ask the one holding the session.
    alias = session_alias(session)
    server = current_server() or session_server(session)
    if server is None:
        raise TmuxError(f'Could not find the tmux server of session {session}.')
    # Keep the recorded alias, which existing shells use, even when its
    # directory has gone with the runtime directory and has not been recreated.
    if not alias_parts(alias, restore=True):
        if not os.path.exists('/proc/self/environ'):
            raise TmuxError('Agent aliases need Linux /proc.')
        if tmux('show-options', '-gqv', HOOKS_OPTION, check=False).strip() != 'on':
            raise TmuxError('This tmux server has not loaded the dalftui hooks; run bin/reload first.')
        directory = ensure_directory()
        alias = os.path.join(directory, secrets.token_hex(16)) if directory else ''
        if not alias_parts(alias):
            raise TmuxError('No private directory is available for agent aliases.')
        tmux('set-option', '-t', session, ALIAS_OPTION, alias)
    # Always apply it: point the alias at the attached client and pin new panes.
    sync(server=server)
    print(f'Session {session} now uses the agent alias {alias}.')
    print('New panes use it. In each existing shell of this session, run once:')
    print(f'  export SSH_AUTH_SOCK={alias}')
    return 0


def describe_age(seconds):
    if seconds < 60:
        return f'{seconds}s'
    if seconds < 3600:
        return f'{seconds // 60}m'
    if seconds < 86400:
        return f'{seconds // 3600}h{seconds % 3600 // 60:02d}m'
    return f'{seconds // 86400}d{seconds % 86400 // 3600:02d}h'


def status(session):
    alias = session_alias(session)
    shell = os.environ.get(AGENT)
    print(f'Session:      {session}')
    error = last_error()
    if error:
        print(f'Last hook error: {error}')
    directory = ensure_directory()
    if directory:
        with locked(directory):
            removed = collect(None, None, [directory])
        if removed:
            print(f'Removed {removed} alias(es) left by tmux servers that have exited.')
    if not alias_parts(alias):
        print('Agent alias:  none; panes keep the socket tmux copied when they started')
        print(f'This shell:   SSH_AUTH_SOCK={shell or "(unset)"}')
        print('Run "session_owner.py enable" to give this session an alias.')
        return 0
    record = read_record(alias)
    print(f'Agent alias:  {alias}')
    try:
        target = os.readlink(alias)
    except OSError:
        target = None
    owner = record.get('owner') if isinstance(record.get('owner'), dict) else None
    if target is None:
        reason = ('the attached client has no forwarded agent' if owner else
                  'no client is attached')
        print(f'Alias target: absent ({reason})')
    else:
        reachable = 'socket' if os.path.exists(target) else 'missing'
        print(f'Alias target: {target} ({reachable})')
    if owner:
        details = [str(owner.get('name')), f'pid {owner.get("pid")}']
        if owner.get('origin'):
            details.append(owner['origin'] if owner['origin'] == 'local' else f'from {owner["origin"]}')
        if isinstance(record.get('since'), int):
            details.append(f'owner for {describe_age(max(0, int(time.time()) - record["since"]))}')
        details.append(f'generation {record.get("generation")}')
        print('Owner client: ' + ', '.join(details))
    else:
        print('Owner client: none')
    if shell == alias:
        print('This shell:   uses the alias')
    else:
        print(f'This shell:   SSH_AUTH_SOCK={shell or "(unset)"}; to follow the alias, run:')
        print(f'  export SSH_AUTH_SOCK={alias}')
    print('The alias routes to the attached client; it does not prove which agent or keys answer.')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Keep one tmux client per session and its stable SSH agent alias.')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status', help="show this session's agent alias and owner client") \
        .add_argument('--session', help='session ID, such as $3 (default: this pane)')
    commands.add_parser('enable', help='give this existing session an agent alias') \
        .add_argument('--session', help='session ID, such as $3 (default: this pane)')
    commands.add_parser('new', help='print an alias path for a new session (launcher)')
    hook = commands.add_parser('sync', help='apply tmux state (tmux hooks)')
    hook.add_argument('--session', default='', help='session the hook client joined')
    hook.add_argument('--client', default='', help='name of the hook client (tmux 3.3+)')
    args = parser.parse_args(argv)
    try:
        if args.command == 'new':
            alias = new_alias()
            if alias is None:
                return 1
            print(alias)
            return 0
        if args.command == 'sync':
            try:
                return sync(args.session or None, args.client or None)
            except Exception as error:  # pylint: disable=broad-exception-caught  # hooks hide output
                note_error(error)
                raise
        session = args.session or pane_session()
        return enable(session) if args.command == 'enable' else status(session)
    except (TmuxError, OSError) as error:
        print(f'session_owner: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
