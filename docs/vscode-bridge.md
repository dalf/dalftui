# VS Code bridge reference

## Open a folder

Press **Ctrl+Shift+F3** in an Alacritty pane to open its directory in a new local
VS Code window. Install VS Code's `code` command on your desktop.

In an SSH window opened through **Ctrl+Shift+F2** to a server with a compatible
dalftui bridge installed, the same shortcut opens the remote pane's directory
in local VS Code using Microsoft's **Remote - SSH** extension. VS Code uses
the same SSH host alias and login as the picker, so your
SSH configuration supplies the hostname, keys, port, and jump hosts. This uses
VS Code's documented [remote folder command](https://code.visualstudio.com/docs/remote/troubleshooting#_connect-to-a-remote-host-from-the-terminal).

Update dalftui and run `./install` on both machines. Reconnect older SSH windows
through the dalftui launcher (the picker or `--connect HOST`): attachments without
credentials cannot use F3, even if their old Unix socket is still reachable.
Local folder opening continues to work without bridge credentials.
The picker checks for tmux and the installed dalftui files under
`~/.config/dalftui` (or `$XDG_CONFIG_HOME/dalftui` when the remote configuration
directory is absolute), then reads the bridge's declared protocol version.
Only installations declaring a supported version receive bridge credentials
and an authenticated socket bridge through that window's SSH connection.
The bridge is removed when the connection ends.
No desktop VS Code installation is needed on the server; Remote - SSH manages
its own server component when you first connect.

The bridge follows the tmux client that pressed F3, including when several
clients attach to the same session. Your SSH server must allow Unix socket
forwarding (`AllowStreamLocalForwarding`). A plain `ssh host` connection lacks
the bridge; reconnect with the picker, or run
`python3 ~/code/dalftui/bin/ssh_picker.py --connect HOST` from your local terminal.
If VS Code cannot open, tmux displays the error in its status line.

Both Unix and TCP bridges require a fresh, random 32-byte token for every SSH
window. The token travels over SSH stdin, never in SSH command arguments or
terminal titles. Before requesting forwarding, a separate SSH setup connection
creates an unpredictable remote directory with mode 0700 and an exclusive
mode-0600 credential file. Attachment reads and removes the file, then passes
the endpoint and token in the triggering tmux client's environment. Several
clients on one tmux session keep their own credentials and fixed SSH destinations.
Setup now uses an additional SSH authentication step on Linux too, so password
authentication may prompt twice. SSH keys and an agent avoid repeated prompts.
The remote setup uses `sh` and Linux `stat`, independent of the login shell.

The remote Unix socket is created inside that private directory. Application
authentication remains mandatory even if socket permissions allow other users
to connect. OpenSSH's server-side
[`StreamLocalBindMask`](https://man.openbsd.org/sshd_config#StreamLocalBindMask)
defaults to 0177; a permissive server setting must not grant editor access.
The bridge protects against other server accounts reaching the forwarded socket.
It does not protect against a compromised login account or the remote
administrator, who can access that account's credentials. Requests can open
folders only on the bridge's fixed remote host.

Remote exit and signal traps remove only that bridge's credential, socket, and
ownership marker, then remove the empty directory. Setup refuses existing paths
and symlinks; attachment and fallback cleanup validate ownership and permissions.
After failed setup, cancellation, disconnect, or normal exit, the desktop bridge
stops first and the launcher also attempts bounded SSH cleanup in batch mode,
without another password prompt. If the server is unreachable or batch
authentication is unavailable, remote cleanup is best effort: private, inactive
resources may remain until removed on the server.

Each bridge retains at most eight queued or active requests, handled by eight
workers; additional connections are closed immediately. A complete request must
arrive within three seconds of acceptance, even if bytes keep arriving, and must
fit in 16 KiB. Editor startup has a separate 15-second timeout, response writing
has a three-second timeout, and the client waits up to 20 seconds for a response.
Ending the SSH connection closes accepted sockets, cancels running editor CLI
processes, and waits for the workers before removing the private socket directory.
These bounds reduce slow-connection denial of service; they do not guarantee
availability under sustained connection flooding.

## Bridge version compatibility

The desktop checks for `bin/vscode.py` and checks the remote protocol with
`python3 ~/.config/dalftui/bridge_protocol.py --version` before creating
credentials or starting forwarding. The desktop and server need the `bin/`
command layout and a supported protocol declaration; they do not need identical
Git revisions. Installations with the previous root command layout, without a
readable protocol declaration, or declaring an unsupported version keep normal
tmux login but skip the VS Code bridge. The launcher suggests updating dalftui
from [GitHub](https://github.com/dalf/dalftui) on that server. It does not download
or deploy the desktop checkout. Servers without tmux or without dalftui still
connect silently, as described in [tmux.md](tmux.md#session-policy).

Update from the server's existing checkout, then reconnect:

```sh
git pull --ff-only
./install
```

Protocol version 2 records the move to `bin/`, including the remote editor's
discovery path. Update both desktop and server checkouts and rerun installation
before reconnecting. An old desktop cannot discover a new server's moved editor;
a new desktop refuses bridge credentials for a server using the old root layout.
On Windows, rerun `.\install.cmd` to regenerate the profile and Terminal actions.

The check makes no freshness request to GitHub on login. The authenticated v1
wire format remains supported: requests and responses without the optional
`protocol_version` field are interpreted as v1. Current peers still emit v1
messages, with metadata when it fits the existing 16 KiB limit. At that boundary,
they omit the optional metadata to preserve valid payloads. The decoder also
accepts v2 metadata with the same message semantics. Unsupported declared
versions are rejected before launching VS Code. Recognizing an old wire message
does not make an old root-layout or undeclared installation eligible for setup.

## TCP bridge (Windows and `--bridge tcp`)

Windows connections to servers with a compatible dalftui bridge installed use
a token-authenticated TCP bridge forwarded through SSH. dalftui binds the **desktop listener** to
`127.0.0.1`. It explicitly requests a
**remote SSH listener** with
`-R 127.0.0.1:REMOTE_PORT:127.0.0.1:LOCAL_PORT`, but that listener's effective
bind address also depends on the SSH server's policy. The Linux VM must permit
remote TCP forwarding (`AllowTcpForwarding yes` or `remote`) and have an
effective server-side `GatewayPorts` setting of **`no` or `clientspecified`**
for loopback-only operation:

- `GatewayPorts no` (the OpenSSH default) restricts remote TCP forwards to
  loopback. Prefer this when client-selected public forwards are unnecessary.
- `GatewayPorts clientspecified` honors the client's requested address, so
  dalftui's explicit `127.0.0.1` request also keeps the remote listener on loopback.
- `GatewayPorts yes` forces wildcard binding even when dalftui requests
  `127.0.0.1`. Other machines may then reach the forwarded port, depending on
  routing and firewall rules.

See OpenSSH's [`GatewayPorts` documentation](https://man.openbsd.org/sshd_config#GatewayPorts).
These requirements apply to Windows's default TCP transport and Linux
connections using `--bridge tcp`. Linux's default private Unix socket transport
is unaffected by `GatewayPorts`.

The token is sent through SSH stdin to a private file, then consumed when
attaching; it is not included in remote command-line arguments. Setup uses an
additional SSH connection, so password authentication may prompt twice. SSH
keys and an agent avoid repeated prompts. The launcher chooses a remote
forwarding port for each connection; if SSH reports that port is occupied,
run the connection command again.

Token authentication still prevents unauthorized editor launches. The request
deadlines and concurrency limits described above bound slow-reader handling,
but wider network reachability increases exposure to connection flooding.
This conditional exposure does not imply an authentication bypass or establish
that any particular server is exposed.

Adding client-side `ssh -o GatewayPorts=no` does not override the server's
remote-forwarding policy. `ExitOnForwardFailure=yes` confirms that forwarding
succeeded, not that the listener is loopback-only. A firewall can restrict
reachability, but does not establish the listener's bind address.

To verify loopback-only TCP forwarding on the VM:

1. Have the server administrator inspect the effective configuration for the
   actual connection, including `Include` files and applicable `Match` rules.
   For example, [`sshd -T -C`](https://man.openbsd.org/sshd#T) prints the effective
   policy without starting or restarting a server:

   ```sh
   sudo /usr/sbin/sshd -T \
     -C user=alice,addr=198.51.100.25,host=desktop.example.org,laddr=192.0.2.10,lport=22 \
     | grep '^gatewayports '
   ```

   Replace the examples with the login user, client source address and resolved
   hostname as seen by sshd (the jump host's details when using a jump host),
   and the server address and SSH port. Use the running service's configuration
   path (`-f` if nondefault) and any command-line policy overrides (`-o`).
   Root/sudo access is usually needed to read protected configuration, included
   files, and host keys for this check. Checking only one configuration file
   cannot establish the effective policy. Expect `gatewayports no` or
   `gatewayports clientspecified`; the next check verifies the live listener.

2. While a dalftui TCP connection is active, list the tmux clients on the VM.
   Choose the PID belonging to that connection's terminal and read its endpoint,
   then inspect the remote port's listening address:

   ```sh
   tmux list-clients -F '#{client_pid} #{client_tty}'
   tr '\0' '\n' < /proc/CLIENT_PID/environ | grep '^DALFTUI_EDITOR_SOCKET='
   ss -ltn 'sport = :REMOTE_PORT'
   ```

   Replace `CLIENT_PID` with that PID and `REMOTE_PORT` with the number in
   `tcp:127.0.0.1:REMOTE_PORT`. A pane's shell environment can retain an older
   connection's endpoint, so use the selected tmux client's environment.
   Inspect every result's **Local Address:Port** column. `127.0.0.1` and `::1`
   are loopback addresses; `0.0.0.0`, `::` (often shown as `[::]`), and `*` are
   wildcard addresses, not loopback. A specific non-loopback address also fails
   this check. The endpoint string records dalftui's request, not the actual
   binding. Listing addresses with `ss -ltn` normally needs no elevated
   privileges; `sudo ss -ltnp` may be needed to identify the owning sshd process.

### Update the server

Update and reload dalftui on the VM before connecting from Windows:

```sh
cd ~/code/dalftui
git pull --ff-only
./install
```

## Open a remote folder without dalftui

You can also open a remote folder directly from your **local** terminal:

```sh
code --new-window --folder-uri "vscode-remote://ssh-remote+work-server/home/alice/project"
```

## Changing the editor bridge

[bridge_protocol.py](../bridge_protocol.py) owns the dependency-free wire contract,
including message validation, UTF-8 newline-delimited JSON, the 16 KiB limit, token and
endpoint formats, environment names, and the protocol declaration used during
SSH setup. Read its versioning rules before changing that contract, credential
delivery, or bootstrap behavior. A version bump is required when a previously
supported remote/desktop pairing can no longer perform a valid operation
correctly, even if the JSON field names are unchanged.

[dalftui/linux/remote_bootstrap.py](../dalftui/linux/remote_bootstrap.py) generates
the Linux server's shell programs from portable Python, including on Windows
desktops. [dalftui/ssh.py](../dalftui/ssh.py) runs SSH and manages the desktop bridge.
The generator embeds [dalftui/linux/tmux-start.sh](../dalftui/linux/tmux-start.sh)
so remote tmux startup works without a dalftui installation.
[bin/tmux-start.sh](../bin/tmux-start.sh) forwards local startup to that canonical
policy; Alacritty invokes it through the installed checkout link.

Check both older remote clients with the current desktop bridge and current
remote clients with supported older desktop bridges. The frozen historical peer
in [tests/fixtures/bridge_protocol_v1.py](../tests/fixtures/bridge_protocol_v1.py)
and the tests in [tests/test_bridge_protocol.py](../tests/test_bridge_protocol.py)
capture those pairings. Keep historical fixtures unchanged; add fixtures for
new versions. Refactoring and logging usually do not need a bump. An optional
field avoids a bump only when old peers safely ignore it and new peers accept
its absence. [AGENTS.md](../AGENTS.md) requires agents to record that compatibility
assessment and add a test for affected historical behavior.
The frozen installation probe in
[tests/fixtures/ssh_bootstrap_v1.py](../tests/fixtures/ssh_bootstrap_v1.py) also checks
the deliberate rejection of the new layout by older desktops, while the frozen
v2 probe in [tests/fixtures/ssh_bootstrap_v2.py](../tests/fixtures/ssh_bootstrap_v2.py)
checks the new installed layout. Current bootstrap tests refuse credentials for
old root-only installations and exercise the frozen v2 layout.

The optional plain, saved-check, and ops startup modes keep protocol version 2.
A new desktop embeds the selected startup program, so a supported older remote
does not need new action code. Credentials still travel on SSH stdin into private
files, are consumed before startup, and remain available in the connection's
environment until cleanup. Historical-peer tests exercise these new modes with
the frozen remote client. An older desktop retains its normal startup behavior
against a new remote: installed paths, declarations, wire messages, and credential
semantics are unchanged. Existing historical-peer tests cover that direction too.
The system overview uses the same embedded startup and credential lifecycle;
it requires no protocol bump or remote update. Compatibility tests run both the
ops overview and detailed system check before opening an editor through a frozen
historical remote client.
