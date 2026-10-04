# dalftui

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

- **Ctrl+B, then F1:** open the keyboard shortcut guide.
- **Ctrl+B, then F2:** desktop mode: choose an SSH host and open a separate Alacritty window.
- **Ctrl+B, then F3:** open the current pane's directory in a new VS Code window, locally or over SSH.
- **Ctrl+Shift+T:** new tmux window.
- **Ctrl+Page Up / Page Down:** previous / next window.
- **Ctrl+Shift+D / Ctrl+Shift+E:** split side by side / top and bottom.
- **Ctrl+Alt+arrow:** change pane.
- **Ctrl+Alt+Shift+arrow:** resize pane.

The guide reads Alacritty imports and local overrides, and shows live tmux
bindings. The terminal font needs glyphs for the rounded Powerline caps (`` and
``) and the status circle (`⬤`). The system monospace font remains the default.

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

The SSH window starts tmux on the remote host:

- No sessions: create session `0`.
- One session: attach to it, whatever its name.
- Multiple sessions: open tmux's session chooser.

The remote host must have tmux installed. **Ctrl+B, then d** detaches and closes
the SSH window while leaving its session running. Connection errors stay visible
until Enter is pressed. Ordinary Alacritty windows create or reattach to local
session `0`; SSH windows override that startup and connect directly to the server.
Installing dalftui locally does not deploy its tmux configuration to remote hosts.
Install `--tmux-only` on each server where you want the shared configuration.

## Open the current folder in VS Code

Press **Ctrl+B, then F3** in a local pane to open its directory in a new local
VS Code window. Install VS Code's `code` command on your desktop.

In an SSH window opened through **Ctrl+B, then F2**, the same shortcut opens
the remote pane's directory in local VS Code using Microsoft's **Remote - SSH**
extension. VS Code uses the same SSH host alias and login as the picker, so your
SSH configuration supplies the hostname, keys, port, and jump hosts. This uses
VS Code's documented [remote folder command](https://code.visualstudio.com/docs/remote/troubleshooting#_connect-to-a-remote-host-from-the-terminal).

Update dalftui and run `./reload` on both machines. Reopen older SSH windows
with the picker to enable F3. The picker creates a private Unix socket bridge
through that window's SSH connection, and removes it when the connection ends.
No desktop VS Code installation is needed on the server; Remote - SSH manages
its own server component when you first connect.

The bridge follows the tmux client that pressed F3, including when several
clients attach to the same session. Your SSH server must allow Unix socket
forwarding (`AllowStreamLocalForwarding`). A plain `ssh host` connection lacks
the bridge; reconnect with the picker, or run
`python3 ~/code/dalftui/ssh-picker.py --connect HOST` from your local terminal.
If VS Code cannot open, tmux displays the error in its status line.

### Connect from Windows

The Windows launcher runs in PowerShell or Command Prompt. It needs Python
3.11+, Windows OpenSSH, and Windows VS Code with **Remote - SSH**. The `code`
command must be on PATH. No local tmux, Alacritty, curses package, or Windows
installation of the dalftui configuration is needed.

Clone the repository once on Windows, then connect using an alias from
`%USERPROFILE%\.ssh\config`:

```powershell
git clone https://github.com/dalf/dalftui.git "$HOME\code\dalftui"
cd "$HOME\code\dalftui"
py -3 .\ssh-picker.py --connect my-vm
```

For a shorter command in PowerShell, define `dssh`:

```powershell
function dssh {
    param([Parameter(Mandatory)][string]$HostName)
    py -3 "$HOME\code\dalftui\ssh-picker.py" --connect $HostName
}

dssh my-vm
```

The function works from any directory. Adjust the script path if you cloned the
repository elsewhere. It connects through the same launcher, so remote tmux and
**Ctrl+B, then F3** keep working. This function connects directly to the supplied
host alias; it does not open a host picker.

To keep `dssh` available in new PowerShell sessions, create your
[PowerShell profile](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_profiles)
if needed, then open it:

```powershell
if (-not (Test-Path -LiteralPath $PROFILE)) {
    New-Item -ItemType File -Path $PROFILE -Force | Out-Null
}
notepad $PROFILE
```

Add the `function dssh { ... }` definition above to the profile and save it.
Reload the profile in your current PowerShell session:

```powershell
. $PROFILE
dssh my-vm
```

A `git pull --ff-only` updates the launcher used by this function; you do not
need to redefine it when the checkout stays at the same path.

SSH uses the configured username; if none is configured, the launcher asks for
one. It creates or reattaches tmux using the usual session policy. Once attached,
**Ctrl+B, then F3** opens the active pane's remote folder in Windows VS Code.
The Windows launcher uses the current terminal window.

Windows uses a loopback TCP bridge authenticated with a connection token,
forwarded through SSH. The Linux VM must permit remote TCP forwarding
(`AllowTcpForwarding yes` or `remote`). The token is sent through SSH stdin to
a private file, then consumed when attaching; it is not included in remote
command-line arguments. Setup uses an additional SSH connection, so password
authentication may prompt twice. SSH keys and an agent avoid repeated prompts.
The launcher chooses a remote forwarding port for each connection; if SSH
reports that port is occupied, run the connection command again.

Update and reload dalftui on the VM before connecting from Windows:

```sh
cd ~/code/dalftui
git pull --ff-only
./reload
```

For later Windows updates, run `git pull --ff-only` in the Windows checkout and
start a new connection. Linux connections keep using their private Unix socket
bridge by default. `--bridge tcp` also allows testing TCP connections on Linux.

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

The Windows-compatible launcher tests run separately without tmux or curses:

```sh
python -m unittest discover -s tests -p test_windows.py -v
```

GitHub Actions runs these tests on Windows with Python 3.11 and 3.14. They cover
TCP authentication, native VS Code CLI arguments, SSH login resolution, and
connection-token handling. GUI launches are mocked in the automated tests.
