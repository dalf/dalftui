# My terminal setup

A Linux Alacritty/tmux configuration with a black, high-contrast terminal,
rounded tabs, pane shortcuts, a searchable shortcut guide, and an SSH picker.
The tab design preserves the optional claude-tabstatus integration: the active
light pill uses dark status circles, and inactive dark pills use light circles.

## Install once

Requirements: Python 3.11+, Alacritty 0.14+, tmux 3.2+, OpenSSH 9.4+, Git,
and `less` for the desktop mode. The server mode below needs Python 3.11+,
tmux 3.2+, Git, and `less`. The installer configures software that is already installed. It
uses no package manager, downloads, root access, or Python packages.

Keep the checkout at a stable path, such as `~/code/dalftui`, then run:

```sh
cd ~/code/dalftui
./install --dry-run
./install
./reload
```

Existing configuration files and symlinks are backed up before replacement.
The installer creates these connections:

| Installed path | Purpose |
| --- | --- |
| `~/.config/dalftui` | Symlink to this checkout |
| `~/.config/alacritty/alacritty.toml` | Desktop mode: imports shared Alacritty settings, then personal overrides |
| `~/.tmux.conf` | Sources shared tmux settings, then personal overrides |
| `~/.config/tmux/shortcuts.py` | Compatibility link to the shortcut guide |

`XDG_CONFIG_HOME` and `XDG_STATE_HOME` are respected when they contain absolute
paths. The tmux loader remains at `~/.tmux.conf` so tmux finds it consistently.

Running `./install` again preserves personal overrides and leaves an existing
installation in its current mode. It can also reconnect the configuration link if you
move the checkout. Keep the checkout outside the managed `~/.config/dalftui`
path; the installer refuses to replace an existing directory there.

## Install on an SSH server

Clone this repository to a stable directory on the server, then run:

```sh
cd ~/code/dalftui
./install --tmux-only --dry-run
./install --tmux-only
./reload
```

Server requirements are **Python 3.11+, tmux 3.2+, Git, and `less`**. Alacritty
and the SSH picker's OpenSSH 9.4 requirement apply to the desktop mode. The
server installer manages the shared configuration link, tmux loader, shortcut
guide link, and `~/.config/tmux/local.conf`. It preserves existing Alacritty files.

The server uses the same rounded tabs, Claude status styling, pane bindings,
and history settings. **Ctrl+B, then F1** opens a guide with native tmux keys
and reminders for shortcuts supplied by your local Alacritty. The guide reads
live tmux bindings and does not try to read Alacritty settings on the server.
From dalftui Alacritty, **Ctrl+Shift+F1** also opens that guide.
**Ctrl+B, then F2** is disabled in server mode because its picker launches a
local Alacritty window.

On tmux 3.2, popup windows use a plain border and the terminal's default colors,
and history searches share the normal command prompt history. tmux 3.3+ adds
the styled popup border and separate search history. The rounded tab design and
Claude status colors are the same on every supported version.

Your local terminal renders the fonts and rounded glyphs. Use the desktop SSH
picker to open a direct remote tmux session; the Alacritty shortcuts then reach
remote tmux. An SSH connection started inside a local tmux pane creates nested
sessions, where the local tmux may handle those shortcuts first.

The installation mode is recorded in the private `~/.tmux.conf` loader and
survives Git updates. Both `./reload` and a repeated `./install` recognize it,
so you do not need to repeat the flag after installation. Use `./install --desktop`
or `./install --tmux-only` to explicitly switch modes. Mode changes back up the
previous loader and preserve personal overrides. Older desktop loaders are
recognized and safely migrated on the next installation.

To receive later configuration updates on the server:

```sh
git pull --ff-only
./reload
```

## Update without reinstalling

After a Git remote is configured:

```sh
cd ~/code/dalftui
git pull --ff-only
./reload
```

The symlink makes new repository files available immediately. The helper
scripts read their configuration whenever you open them. `./reload` requests
an Alacritty refresh in desktop mode and sources tmux's configuration again without ending
sessions or restarting running programs. It rewrites the Alacritty loader in
place because file replacements from Git or an editor may not trigger a reload.

Settings that affect terminal startup apply to new Alacritty windows. If tmux
is not running, `./reload` leaves it stopped; the next server loads the updated
configuration. From inside tmux, reload targets the current server. Outside tmux,
it targets the default server. Use `./reload --socket /path/to/socket` for another
server.

Terminal capability entries occupy fixed tmux array slots (`[100]`), so repeated
reloads do not append duplicates. New terminal capabilities can require a new
terminal connection. Existing history buffers retain their original limit;
the configured history limit applies to new panes.

## Personal settings

These files stay outside the repository and are preserved across installs:

- `~/.config/alacritty/local.toml`
- `~/.config/tmux/local.conf`

Server mode uses only the tmux override file.

For example, put this in `local.toml` to override the font size:

```toml
[font]
size = 11.0
```

Or put this in `local.conf` to change the history limit for new panes:

```tmux
set -g history-limit 50000
```

Run `./reload` after editing either file. Alacritty merges imported tables and
appends arrays, including keyboard bindings; tmux executes local settings last.
Keep personal changes in these files so repository updates remain easy to pull.
The small generated loader files are managed by the installer.

Backups are stored under `~/.local/state/dalftui/backups/` (or `XDG_STATE_HOME`).
Each backup directory contains the original files or symlinks and a
`manifest.json` mapping them to their original paths. The backup directories are
private. Backups and Python caches are excluded from Git.

## Shortcuts

- **Ctrl+Shift+F1:** open the keyboard shortcut guide.
- **Ctrl+Shift+F2:** desktop mode: choose an SSH host and open a separate Alacritty window.
- **Ctrl+Shift+F3:** open the current pane's directory in a new VS Code window, locally or over SSH.
- **Ctrl+Shift+T:** new tmux window.
- **Ctrl+Page Up / Page Down:** previous / next window.
- **Ctrl+Shift+D / Ctrl+Shift+E:** split side by side / top and bottom.
- **Ctrl+Alt+arrow:** change pane.
- **Ctrl+Alt+Shift+arrow:** resize pane.

The guide reads Alacritty imports and local overrides, and shows live tmux
bindings. The terminal font needs glyphs for the rounded Powerline caps (`` and
``) and the status circle (`⬤`). The system monospace font remains the default.

Alacritty translates Ctrl+Shift+F1/F2/F3 to the existing tmux actions. The
tmux prefix bindings remain available as fallbacks. Reload locally to use
the new Alacritty shortcuts; existing remote tmux configurations already
understand the translated keys.

## SSH hosts and login

The picker reads named `Host` entries from `~/.ssh/config` whenever it opens,
including entries in `Include` files. It lists only hosts whose effective SSH
tag is `dalftui`. Mark each login server with `Tag dalftui`, for example:

```sshconfig
Host work-server
    HostName server.example.org
    User alice
    Tag dalftui
```

The installer does not change your SSH configuration. SSH hosts, keys and
credentials stay outside the repository. Git service entries such as GitHub
and GitLab can remain untagged and stay out of the picker.

In the picker, type to filter, use the arrows to select, and press **Enter** to
connect. **Esc** cancels. OpenSSH resolves tags, so wildcard, `Match`, and included
settings apply. Wildcard rules are not individual hosts. You can type a full
hostname covered by a tagged wildcard rule and press Enter to connect.

A configured `User`, including one supplied through a wildcard or included
configuration, is used automatically. Otherwise the new window asks for the
login. A destination such as `user@host` already provides its username.

## Remote tmux

SSH windows use tmux when it is installed on the remote host. Otherwise they
silently open a plain login shell. No remote dalftui installation is required
for either case. Local Alacritty windows and SSH windows with tmux use the same
session policy:

- No sessions: create session `0`.
- One detached session: attach to it, whatever its name.
- One attached session: create a new independent session with the next numeric name.
- Multiple sessions: list their IDs, names, and client counts. Enter a session ID to
  attach, `n` or Enter for a new session, `s` for a plain login shell, or `q` to cancel.

With remote tmux, **Ctrl+B, then d** detaches and closes the SSH window while
leaving its session running. Connection errors stay visible
until Enter is pressed. A plain shell has no tmux shortcuts, persistence, or
remote **Ctrl+Shift+F3** integration. SSH windows override Alacritty's local
startup and apply the policy directly on the server.
Installing dalftui locally does not deploy its tmux configuration to remote hosts.
Install `--tmux-only` on each server where you want the shared configuration.
Without it, remote tmux uses the server's existing configuration and bindings.

## Open the current folder in VS Code

Press **Ctrl+Shift+F3** in an Alacritty pane to open its directory in a new local
VS Code window. Install VS Code's `code` command on your desktop.

In an SSH window opened through **Ctrl+Shift+F2** to a server with a compatible
dalftui bridge installed, the same shortcut opens the remote pane's directory
in local VS Code using Microsoft's **Remote - SSH** extension. VS Code uses
the same SSH host alias and login as the picker, so your
SSH configuration supplies the hostname, keys, port, and jump hosts. This uses
VS Code's documented [remote folder command](https://code.visualstudio.com/docs/remote/troubleshooting#_connect-to-a-remote-host-from-the-terminal).

Update dalftui and run `./reload` on both machines. Reconnect older SSH windows
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
`python3 ~/code/dalftui/ssh-picker.py --connect HOST` from your local terminal.
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

### Bridge version compatibility

The desktop checks the remote protocol with
`python3 ~/.config/dalftui/bridge_protocol.py --version` before creating
credentials or starting forwarding. A supported protocol is sufficient; the
desktop and server do not need identical Git revisions. Old installations
without a readable protocol declaration, and installations declaring an
unsupported version, keep normal tmux login but skip the VS Code bridge. The
launcher suggests updating dalftui from [GitHub](https://github.com/dalf/dalftui)
on that server. It does not download or deploy the desktop checkout. Servers
without tmux or without dalftui still connect silently as described above.

Update from the server's existing checkout, then reconnect:

```sh
git pull --ff-only
./reload
```

This checks compatibility, not whether GitHub has a newer release. It makes no
freshness request to GitHub on login. Protocol version 1 retains the historical
authenticated wire format: older requests and responses without the optional
`protocol_version` field are interpreted as v1. Current peers include that
field when it fits the existing 16 KiB limit; v1 messages at that boundary omit
the optional metadata to preserve previously valid payloads. Unsupported declared
versions are rejected before launching VS Code.
Recognizing an old wire message does not make an undeclared remote installation
eligible for bridge setup.

### Connect from Windows

The Windows launcher runs in PowerShell or Command Prompt. It needs Python
3.11+, Windows OpenSSH, and Windows VS Code with **Remote - SSH**. The `code`
command should be on an absolute PATH entry during setup. The host picker also
needs fzf and OpenSSH 9.4+ for `Tag dalftui`. No local tmux, Alacritty, or
curses package is needed.

Clone the repository once on Windows, then run setup in PowerShell:

```powershell
git clone https://github.com/dalf/dalftui.git "$HOME\code\dalftui"
cd "$HOME\code\dalftui"
.\setup-windows.ps1
```

Setup records the absolute `Code.exe` path in
`%LOCALAPPDATA%\dalftui\config.json`. Folder launches use only that configured
installation; they never search the current project. Initial discovery requires
fully qualified drive or UNC paths; empty and relative PATH entries, including
`C:bin` and `\bin`, are ignored. To select an unpackaged or
portable installation explicitly, pass its directory or executable:

```powershell
.\setup-windows.ps1 -VSCodePath 'C:\Tools\VS Code Portable'
# or: .\setup-windows.ps1 -VSCodePath 'C:\Tools\VS Code Portable\Code.exe'
```

If that installation is moved or removed, folder opening fails without trying
another executable and tells you to rerun setup. Use `-VSCodePath` again when
moving a portable installation.

Setup reuses fzf when it is already on PATH. Otherwise it installs fzf using
WinGet if available, or Chocolatey. You can choose a package manager explicitly:

```powershell
.\setup-windows.ps1 -PackageManager winget
.\setup-windows.ps1 -PackageManager choco
```

If neither package manager is available, setup prints the manual install
commands and configures direct connections. Use `-SkipFzf` to configure `dssh`
without installing fzf. The package commands are
[documented by fzf](https://junegunn.github.io/fzf/installation/).
Chocolatey installations may require an administrator PowerShell.

Setup adds a managed block to your current
[PowerShell profile](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_profiles).
It backs up an existing profile before changing it, preserves your personal
settings, and loads `windows.ps1` from this checkout. Repeated setup keeps one
managed block; rerun it if you move the checkout or use another PowerShell host
or version. Setup makes `dssh` available immediately and in new sessions.

In **Windows Terminal**, setup also installs **Ctrl+Shift+F2**: open a new local
tab, pick a host, and connect using remote tmux when available or a plain shell.
The shortcut works while the current tab is in SSH, tmux, or another program.
It uses Terminal's
[new-tab action](https://learn.microsoft.com/en-us/windows/terminal/customize-settings/actions#new-tab)
and keeps your default profile and appearance.

**Ctrl+Shift+F3** opens the current directory in a new VS Code window:

- At a local PowerShell prompt, it uses the current filesystem directory and
  preserves any command you are typing.
- In remote tmux connected through `dssh`, it opens the active pane's directory
  in Windows VS Code with Remote - SSH, including while an app is running.

Terminal translates this shortcut to the existing **Ctrl+B, then F3** sequence,
so existing remote dalftui configurations already support it. PowerShell setup
installs the local handler through
[PSReadLine](https://learn.microsoft.com/en-us/powershell/module/psreadline/set-psreadlinekeyhandler).
Other local shells and running
local programs need their own handler; use a PowerShell prompt for local folders.

Setup finds existing Stable, Preview, Canary, and unpackaged Terminal settings.
It backs up each changed `settings.json`, preserves comments and other settings,
and adds no duplicates on repeated runs. An existing Ctrl+Shift+F2 or F3 binding is
preserved; setup reports the conflict so you can remove that binding and rerun.
If no settings are found, open Windows Terminal once and rerun setup. For a
portable installation, pass its settings path explicitly:

```powershell
.\setup-windows.ps1 -TerminalSettingsPath 'C:\Tools\Terminal\settings\settings.json'
```

Use `-SkipTerminal` to configure only PowerShell and fzf. The tab launcher reads
this checkout each time, so later Git updates apply to new tabs. Rerun setup
after moving the checkout or replacing the PowerShell installation used by setup.

If PowerShell reports that scripts are disabled, enable local scripts for your
user, then rerun setup:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Connect from any directory:

```powershell
dssh        # Pick a host
dssh my-vm  # Connect directly
```

The picker reads `%USERPROFILE%\.ssh\config`, including `Include` files, and
lists hosts tagged `dalftui`. Git service hosts remain out of the list when
untagged. Mark your login servers, for example:

```sshconfig
Host my-vm
    HostName vm.example.org
    User alice
    Tag dalftui
```

Type to filter, use the arrows to select, press **Enter** to connect, or **Esc**
to cancel. Selection connects in the current terminal window. SSH uses the
configured username; if none is configured, the launcher asks for one. It
creates or reattaches tmux using the usual session policy when tmux is installed,
or silently opens a plain login shell otherwise. With a compatible remote
dalftui bridge installed, **Ctrl+Shift+F3** opens the active pane's remote folder
in Windows VS Code.
**Ctrl+B, then F3** remains available as a tmux fallback.

Without PowerShell setup, including from Command Prompt, you can run the
launcher directly:

```powershell
py -3 "$HOME\code\dalftui\ssh-picker.py" --pick
py -3 "$HOME\code\dalftui\ssh-picker.py" --connect my-vm
```

In Command Prompt, replace `$HOME` with `%USERPROFILE%`.

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

Update and reload dalftui on the VM before connecting from Windows:

```sh
cd ~/code/dalftui
git pull --ff-only
./reload
```

For later Windows updates, run `git pull --ff-only` in the Windows checkout,
reload your profile with `. $PROFILE` or open a new PowerShell session, and start
a new connection. The profile follows the checkout; no reinstall is needed.

You can also open a remote folder directly from your **local** terminal:

```sh
code --new-window --folder-uri "vscode-remote://ssh-remote+work-server/home/alice/project"
```

## Theme and Claude integration

The required Catppuccin tmux v2.3.1 configuration files are bundled under
`vendor/catppuccin`, including their upstream MIT license. No theme download or
plugin manager is needed. The custom rounded tab design is in `config/tmux.conf`.

[claude-tabstatus](https://github.com/dalf/claude-tabstatus) is an optional,
separate project. Existing installations continue to supply repository/branch
labels and status through pane titles and `@cctab_window_strip`. dalftui preserves
that integration and does not change Claude hooks. Without it, ordinary tmux
window names are displayed.
Install claude-tabstatus separately on the server too if you want its status
indicators for Claude running there.

## Repository

On a new machine, clone your repository to a stable path and run `./install`
and `./reload`, adding `--tmux-only` when installing on a server. For a local checkout without a remote, create an empty remote
repository and connect it once:

```sh
git remote add origin YOUR_REPOSITORY_URL
git push -u origin main
```

Once the remote exists, the update commands above work on other installations.

### Layout and entrypoints

The Python package runs directly from the checkout; no pip installation is
needed. Representative layout:

```text
.
├── dalftui/
│   ├── ssh.py
│   ├── vscode.py
│   ├── linux/
│   │   ├── alacritty_config.py
│   │   ├── setup.py
│   │   ├── shortcuts.py
│   │   ├── ssh_picker.py
│   │   ├── tmux_editor.py
│   │   ├── remote_bootstrap.py
│   │   └── tmux-start.sh
│   └── windows/
│       ├── ssh.py
│       ├── vscode.py
│       ├── terminal_settings.py
│       ├── setup.ps1
│       ├── profile.ps1
│       └── ssh-tab.ps1
├── bridge_protocol.py
├── install
├── reload
├── shortcuts.py
├── ssh-picker.py
├── vscode.py
├── setup-windows.ps1
├── windows.ps1
├── windows-terminal.ps1
├── windows-terminal.py
├── tmux-start.sh
├── config/
├── tests/
│   ├── test_windows_launcher.py
│   ├── test_windows_terminal.py
│   ├── test_bridge_protocol.py
│   ├── test_bridge_lifecycle.py
│   ├── test_remote_bootstrap.py
│   └── fixtures/
│       ├── bridge_protocol_v1.py
│       └── ssh_bootstrap_v1.py
└── vendor/
    └── catppuccin/
```

[dalftui/ssh.py](dalftui/ssh.py) owns shared host/tag/login evaluation, fzf,
SSH arguments, and connection orchestration. [dalftui/vscode.py](dalftui/vscode.py)
owns URI construction, editor launching, both Unix and TCP bridge transports,
authentication, and lifecycle handling. Platform modules own local operating-system
integration. Directory placement describes the environment targeted by code;
portable helpers can be imported on other operating systems.
In particular, [dalftui/linux/remote_bootstrap.py](dalftui/linux/remote_bootstrap.py)
generates Linux-server shell programs from portable Python and is also used by
Windows desktops. [dalftui/linux/tmux-start.sh](dalftui/linux/tmux-start.sh) is
the canonical startup policy: the root script forwards local startup, while
remote execution embeds the canonical policy directly.

The root paths are deliberate public and compatibility entrypoints:

| Path | Role |
| --- | --- |
| [install](install) | Linux installation CLI |
| [reload](reload) | Linux configuration reload CLI |
| [shortcuts.py](shortcuts.py) | Shortcut-guide launcher and installed compatibility target |
| [ssh-picker.py](ssh-picker.py) | Shared SSH launcher |
| [vscode.py](vscode.py) | Shared editor launcher and remote discovery target |
| [setup-windows.ps1](setup-windows.ps1) | Windows setup CLI |
| [windows.ps1](windows.ps1) | Existing PowerShell profile-loader target |
| [windows-terminal.ps1](windows-terminal.ps1) | Existing Terminal-tab launcher target |
| [windows-terminal.py](windows-terminal.py) | Terminal settings CLI |
| [tmux-start.sh](tmux-start.sh) | Existing local terminal startup target |
| [bridge_protocol.py](bridge_protocol.py) | Canonical standalone contract and version declaration |

Existing profile entries, tmux bindings, Alacritty configuration, installed paths,
and historical SSH probes depend on these locations. Keep them stable.
`bridge_protocol.py` contains the actual contract and version declaration;
it is not a forwarding wrapper.

### Filename conventions

These conventions apply to filenames, directories, and placement:

- Importable Python modules and package directories use `snake_case`.
- Shell and PowerShell script filenames use lowercase words, with hyphens when
  needed. Prefer purpose-specific names such as `profile.ps1`, `ssh-tab.ps1`,
  and `terminal_settings.py`.
- Platform directories normally supply the platform context; avoid redundant
  platform prefixes within them.
- Tests stay flat and use `test_<feature>.py`. Windows-focused launcher and
  integration suites may use `test_windows_<feature>.py`; shared bridge tests
  use feature names without a Windows label.
- Historical fixtures keep their versioned names and remain frozen. Existing
  root command names are compatibility exceptions; vendored upstream filenames
  remain unchanged.

Keep `config/`, `vendor/`, and the flat test layout. Apply these rules when adding
or moving files; they do not call for renaming functions, classes, variables,
already-clear files, or adding speculative platform directories.

### Changing the editor bridge

[bridge_protocol.py](bridge_protocol.py) owns the dependency-free wire contract,
including message validation, UTF-8 newline-delimited JSON, the 16 KiB limit, token and
endpoint formats, environment names, and the protocol declaration used during
SSH setup. Read its versioning rules before changing that contract, credential
delivery, or bootstrap behavior. A version bump is required when a previously
supported remote/desktop pairing can no longer perform a valid operation
correctly, even if the JSON field names are unchanged.

[dalftui/linux/remote_bootstrap.py](dalftui/linux/remote_bootstrap.py) generates
the Linux server's shell programs from portable Python, including on Windows
desktops. [dalftui/ssh.py](dalftui/ssh.py) runs SSH and manages the desktop bridge.
The generator embeds [dalftui/linux/tmux-start.sh](dalftui/linux/tmux-start.sh)
so remote tmux startup works without a dalftui installation. The root
[tmux-start.sh](tmux-start.sh) forwards local startup to that canonical policy;
existing Alacritty configuration and installed checkout links keep working.

Check both older remote clients with the current desktop bridge and current
remote clients with supported older desktop bridges. The frozen historical peer
in [tests/fixtures/bridge_protocol_v1.py](tests/fixtures/bridge_protocol_v1.py)
and the tests in [tests/test_bridge_protocol.py](tests/test_bridge_protocol.py)
capture those pairings. Keep historical fixtures unchanged; add fixtures for
new versions. Refactoring and logging usually do not need a bump. An optional
field avoids a bump only when old peers safely ignore it and new peers accept
its absence. [AGENTS.md](AGENTS.md) requires agents to record that compatibility
assessment and add a test for affected historical behavior.
The frozen installation probe in
[tests/fixtures/ssh_bootstrap_v1.py](tests/fixtures/ssh_bootstrap_v1.py) also checks
older desktops against the current installed layout, while current bootstrap
tests check supported historical root layouts before delivering credentials.

## Verification

```sh
python3 -m unittest discover -s tests -v
python3 ssh-picker.py --list
```

Tests use disposable directories, OpenSSH's configuration evaluator, and private
tmux sockets. They do not open SSH connections or touch your live tmux sessions.
They cover backups, rollback, repeated installation, updates through the link,
personal overrides, both shortcut guides, tag filtering, mode switching, and
reloads that preserve pane processes and Claude status. The CLI is also tested
with Alacritty and SSH absent from PATH. Desktop picker tests are skipped when
OpenSSH's Tag directive is unavailable; it is not required by server mode.
Unix authentication tests include a deliberately mode-0666 socket in a
mode-0755 directory: they prove that reaching the endpoint does not authorize
editor launches. This is a same-account local test, not a cross-user or remote
sshd test. Remote credential scripts run locally with fake tmux clients to
check private/exclusive creation, consumption, failed setup, signal cleanup,
and resource isolation. SSH startup tests cover silent shell fallback, native
tmux without dalftui, installation detection with custom configuration paths,
and connections that never start or forward a bridge. Real tmux tests route
separate clients' endpoints and tokens even with deliberately stale server
environment values.
Bridge protocol tests exercise frozen v1 messages and historical peers in both
directions, reject unsupported versions without editor launches, and check the
remote declaration before credential setup.

The Windows-compatible launcher and Terminal suites run separately without tmux
or curses:

```sh
python -m unittest discover -s tests -p "test_windows*.py" -v
```

This selects [tests/test_windows_launcher.py](tests/test_windows_launcher.py)
and [tests/test_windows_terminal.py](tests/test_windows_terminal.py).
Run the shared bridge lifecycle and historical compatibility suites separately:

```sh
python -m unittest discover -s tests -p "test_bridge*.py" -v
```

This selects [tests/test_bridge_lifecycle.py](tests/test_bridge_lifecycle.py)
and [tests/test_bridge_protocol.py](tests/test_bridge_protocol.py). Together,
the Windows and bridge selections cover native Windows CI's Python tests;
platform and dependency skips still apply. Linux-targeted startup and remote
bootstrap coverage lives in
[tests/test_remote_bootstrap.py](tests/test_remote_bootstrap.py) and runs with
full Linux discovery.

Check the PowerShell setup and profile integration separately:

```powershell
.\tests\test_windows_setup.ps1
```

GitHub Actions runs the full Linux suite on Ubuntu with Python 3.11 and 3.14,
installing tmux, OpenSSH, fzf, Git, and less for the integration tests.
It also runs native Windows tests with Python 3.11 and 3.14, in
PowerShell 5.1 and 7. They cover package manager selection and failures,
profile backups and repeated setup, safe VS Code discovery and portable-path
configuration, the `dssh` command, real fzf filtering, SSH tag and login
resolution, TCP authentication, and connection token handling. Isolated bridge
tests also cover slow input deadlines, concurrent requests, capacity rejection
and recovery, shutdown races, and interruption of readers and editor CLI waits.
A harmless native executable probe verifies that a project-local `Code.exe` is not run;
another verifies the configured `Code.exe` + `cli.js` argument list and encoded
local and remote folder URIs. Linux runs the cross-platform suite and simulated
Windows launch tests. GUI launches and interactive SSH connections remain
mocked; no automated test opens the VS Code GUI or an SSH connection.
