# My terminal setup

A Linux Alacritty/tmux configuration with a black, high-contrast terminal,
rounded tabs, pane shortcuts, a searchable shortcut guide, and an SSH picker.
The tab design preserves the optional claude-tabstatus integration: the active
light pill uses dark status circles, and inactive dark pills use light circles.

## Install once

Requirements: Python 3.11+, Alacritty 0.14+, tmux 3.2+, OpenSSH 9.4+, Git,
`less`, and [Oh My Posh](https://ohmyposh.dev/docs/installation/linux) for the
desktop mode. The server mode below needs Python 3.11+, tmux 3.2+, Git, `less`,
and Oh My Posh. The installer configures software that is already installed. It
uses no package manager, root access, or Python packages. The only download is
the desktop mode's icon font: when `fc-list` does not show Symbols Nerd Font,
the installer runs `oh-my-posh font install NerdFontsSymbolsOnly`.

Keep the checkout at a stable path, such as `~/code/dalftui`, then run:

```sh
cd ~/code/dalftui
./install --dry-run
./install
./bin/reload
```

Optional [mise tasks](#repository-tasks) provide named shortcuts for installation,
reloads, spelling, and tests.

On Windows, use `.\install.cmd`; see [Connect from Windows](#connect-from-windows).

Existing configuration files and symlinks are backed up before replacement.
The installer creates these connections:

| Installed path | Purpose |
| --- | --- |
| `~/.config/dalftui` | Symlink to this checkout |
| `~/.config/alacritty/alacritty.toml` | Desktop mode: imports shared Alacritty settings, then personal overrides |
| `~/.tmux.conf` | Sources shared tmux settings, then personal overrides |
| `~/.config/tmux/shortcuts.py` | Link to `bin/shortcuts.py` |
| `~/.bashrc` | Appended line sourcing `config/prompt.bash`, which starts Oh My Posh with `config/oh-my-posh.omp.json` |

The `~/.bashrc` line is added once, after the existing content, and marked
`# dalftui: Oh My Posh prompt`; the rest of the file is kept. Remove your own
`oh-my-posh init` line to avoid initializing the prompt twice.

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
./bin/reload
```

Server requirements are **Python 3.11+, tmux 3.2+, Git, `less`, and Oh My Posh**. Alacritty
and the SSH picker's OpenSSH 9.4 requirement apply to the desktop mode. The
server installer manages the shared configuration link, tmux loader, shortcut
guide link, `~/.config/tmux/local.conf`, and the `~/.bashrc` prompt line. It
preserves existing Alacritty files and installs no font: your local terminal draws the icons.

The server uses the same rounded tabs, Claude status styling, pane bindings,
and history settings. **Ctrl+B, then F1** opens a guide with native tmux keys
and reminders for shortcuts supplied by your local Alacritty, plus the
[selection rules](#selecting-and-copying) shared with Windows Terminal. The guide reads
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
survives Git updates. Both `./bin/reload` and a repeated `./install` recognize it,
so you do not need to repeat the flag after installation. Use `./install --desktop`
or `./install --tmux-only` to explicitly switch modes. Mode changes back up the
previous loader and preserve personal overrides. Older desktop loaders are
recognized and safely migrated on the next installation.

To receive later configuration updates on the server:

```sh
git pull --ff-only
./bin/reload
```

## Update without reinstalling

When updating from the previous root command layout, rerun `./install` on each
Linux machine or `.\install.cmd` on Windows once; see
[Layout and entrypoints](#layout-and-entrypoints). Later updates use the commands below.

After a Git remote is configured:

```sh
cd ~/code/dalftui
git pull --ff-only
./bin/reload
```

The symlink makes new repository files available immediately. The helper
scripts read their configuration whenever you open them. `./bin/reload` requests
an Alacritty refresh in desktop mode and sources tmux's configuration again without ending
sessions or restarting running programs. It rewrites the Alacritty loader in
place because file replacements from Git or an editor may not trigger a reload.

Settings that affect terminal startup apply to new Alacritty windows. If tmux
is not running, `./bin/reload` leaves it stopped; the next server loads the updated
configuration. From inside tmux, reload targets the current server. Outside tmux,
it targets the default server. Use `./bin/reload --socket /path/to/socket` for another
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

Run `./bin/reload` after editing either file. Alacritty merges imported tables and
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

### Selecting and copying

Selection works the same way in Alacritty and Windows Terminal, locally or over
SSH, whether the pane runs a shell or a mouse-aware program:

- **Shift+drag** selects text; **Ctrl+Shift+C** copies and **Ctrl+Shift+V** pastes.
- **Split panes:** a terminal selection crosses pane borders. Press **Ctrl+B, then z**
  to zoom the pane, select, then **Ctrl+B, then z** again to restore the layout.
- **Text in history:** scroll with the mouse wheel, **Shift+Page Up** in Alacritty,
  or **Ctrl+B, then Page Up**, then Shift+drag.

A plain drag in a shell only shows a reminder to hold Shift, and a plain double-
or triple-click no longer selects a word or line; hold Shift for those too.
Programs that use the mouse, such as htop or editors, still receive drags and clicks. In Windows
Terminal, select before pressing Ctrl+Shift+C: without a selection the key may
reach the pane as Ctrl+C.

dalftui adds no terminal copy bindings and relies on Alacritty and Windows
Terminal defaults. Alacritty also copies selections automatically; Windows
Terminal's `copyOnSelect` setting is left unchanged. tmux sets `set-clipboard on`,
so programs in panes, including on remote servers, may set the desktop
clipboard with OSC 52. They cannot read the desktop clipboard, but an OSC 52
query returns tmux's most recent paste buffer: text copied in tmux history or
set by another pane. Override it in
`~/.config/tmux/local.conf`, for example with `set -s set-clipboard off`.
Reloading only re-sources the configuration: if a later version removes these
root mouse bindings, restart the tmux server to drop them.

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

To connect to a destination outside the list, type a hostname, IP address, or
`user@host` and press **Ctrl+O**. This always uses exactly what you typed, even
when another host matches the filter. The shortcut has its own help line in the
picker and works with an empty list. No `Tag dalftui` or SSH config entry is
required for this explicit action; normal SSH settings still apply. It does not
add the destination to your config or cached host list.

Use **F4–F7** directly on the highlighted host; there is no intermediate actions
menu. The shortcut labels stay visible and wrap onto extra lines on narrow
terminals, with the host grid resizing to fit. The same shortcuts work on Windows
and Linux:

| Key | Action |
| --- | --- |
| Enter | Connect using the existing SSH/tmux startup policy |
| F4 | Show effective OpenSSH hostname, user, port, jump/proxy configuration, and identity-file paths |
| F5 | Open a login shell without dalftui's tmux startup |
| F6 | Open ops mode in a new remote tmux session with process, journal, and shell panes |
| F7 | Choose a saved check to run, followed by an interactive login shell |

The footer explicitly shows the action's **Target**. When filtering leaves a
highlighted host, F4–F7 act on that host. With no matches, it shows
**Target (typed)** and the shortcuts use the exact typed destination after
validation. Ctrl+O always connects to exactly what you typed, even if a listed
host is highlighted. **Esc** from connection details or the saved-check chooser
returns to the same host selection and filter; opening the chooser runs nothing
until you select a check and press Enter.

Connection details run `ssh -G` only for the selected destination, with a
five-second timeout. They never read private-key contents. OpenSSH may evaluate
your configured `Match exec` commands or DNS rules. A configured username is
used when connecting; if `User` is unset, dalftui still asks for a login rather
than accepting OpenSSH's local-user default shown in the details. Details and
saved checks are loaded on demand, keeping host-list caching unchanged.

#### Saved checks

Two read-only checks are built in: **packages** (Debian/Ubuntu APT status) and
**system** (the detailed server overview described below).
Add your own checks to `~/.ssh/dalftui-checks.json` on either client platform
(`$HOME\.ssh\dalftui-checks.json` in PowerShell):

```json
{
  "checks": [
    {
      "name": "web-service",
      "hosts": ["sibils-api", "web-*"],
      "command": "systemctl is-active nginx; systemctl --failed --no-pager",
      "timeout": 15
    },
    {
      "name": "disk-space",
      "command": "df -h; df -i",
      "timeout": 10
    }
  ]
}
```

Names must be unique, including the built-in names. `hosts` defaults to `["*"]`
and matches the SSH destination as entered, using case-sensitive glob patterns
(`*`, `?`, and character classes). `timeout` defaults to 30 seconds and accepts
integers from 1 to 3600. Configuration errors appear in the menu.

Commands are trusted local configuration, executed literally by the remote
`sh`; there is no host-variable substitution. They run as your SSH user, with
stdin closed, and should be noninteractive diagnostics. If a check requires
privileges, configure `sudo -n` explicitly. GNU `timeout` terminates the command's
process group at the deadline, with a five-second kill grace period; if it is
missing, the command is skipped. Output remains visible, the exit status or
timeout is reported, and you receive a shell even after failure. No checks run
while browsing or filtering hosts.

#### Ops mode

Ops mode supports Debian and Ubuntu servers from Windows and Linux clients.
It creates a separate `dalftui-ops-PID` tmux session with this layout and focuses
the bottom pane:

```text
+------------------------+------------------------+
| htop (or top)           | Live journal           |
|                        | Current boot, follow   |
+------------------------+------------------------+
| System overview, then interactive shell          |
+-------------------------------------------------+
```

The journal starts with the last 50 entries and follows new messages using your
existing permissions; it never invokes sudo automatically. Stop following with
Ctrl+C. Missing monitoring tools or journal errors leave a shell in that pane.
Missing tmux, a terminal smaller than 40 columns by 12 rows, or failed pane
creation falls back to a shell. Other sessions and their panes are unchanged.
Detaching leaves the new ops session running; a later normal connection can
select it through the existing tmux session picker. Standard tmux pane navigation
works even without dalftui installed on the server (`Ctrl+B`, then an arrow).

The shell pane starts with a compact, read-only snapshot: host and timestamp,
uptime, systemd state and failed units, available memory and swap,
disk space and inode usage, a recorded reboot request, NTP synchronization, and
Linux software RAID status only when arrays or RAID activity are present. CPU
count is left to the process monitor above. Every failed unit is listed on its
own line without truncation, indented beneath the count without repeating `WARN`.
Disk and inode usage at 80% or higher is highlighted.
The root filesystem is included even on an overlay mount. Other mounted data
filesystems, including network mounts, are checked; most pseudo filesystems are
omitted. The compact view limits filesystem warning rows and counts additional
warnings. Status rows reserve a four-character label plus a space: normal rows
leave it blank, warnings show a yellow `WARN`, and unavailable checks show a red
`ERR`. Color applies to the whole label; redirected output and dumb
terminals retain plain text with the same alignment.

**F7 → system** runs the same checks with CPU count, full filesystem tables, memory details,
failed-unit details, a kernel-version comparison, and recent error/OOM excerpts.
Journal queries cover this boot and the last hour, returning at most 15 error
entries and 5 kernel OOM entries. Visibility follows your existing permissions;
access warnings are retained. A different kernel version under `/boot` is a hint,
not proof that a reboot is required or that this kernel will be selected at boot.
No reboot marker means only that no reboot request was recorded.

Each external query has a two-second limit (with a one-second kill grace period).
The whole compact report has a ten-second limit; the detailed report has twenty
seconds. The outer runner allows up to five seconds for forced termination.
Missing tools, failed queries, and timeouts produce **unknown** results, never
an empty healthy result. The report exits nonzero when collection is incomplete;
successful collection does not imply that the server or its applications are
healthy. F6 omits the numeric exit-status footer on success and reports incomplete
or interrupted collection in plain language. Saved checks retain their numeric
exit status. Either way, the runner leaves an interactive shell. This is a snapshot,
not a continuously updated dashboard; application checks remain host-specific
saved checks.

**F7 → packages** runs `apt-get --simulate upgrade` against cached lists, with
a 30-second limit. It reports APT's last recorded successful refresh when a
success stamp exists, otherwise **unknown**. It always labels the result as
cached: zero available upgrades does not establish that the host is up to date.
It also reports a reboot request when `/var/run/reboot-required` exists.
Nothing refreshes package lists or installs upgrades automatically. To check
online, explicitly run `sudo apt-get update` in the shell and rerun the
package check. APT configuration and repository failures can still affect that
refresh; inspect its result.

The same actions are available directly:

```sh
python bin/ssh_picker.py --connect sibils-api --plain
python bin/ssh_picker.py --connect sibils-api --check packages
python bin/ssh_picker.py --connect sibils-api --ops
```

Use `python3` on Linux if `python` is unavailable. On Linux the desktop picker
opens the selected connection action in a new Alacritty window; `--pick` and
Windows use the current terminal. Plain mode skips dalftui's tmux policy; your
own shell startup files still run. Editor integration follows the same installed
remote compatibility checks as a normal connection.

The picker fills the available terminal and adds columns when needed to fit the
hosts. It recalculates the layout on resize and after filtering, keeping hostnames
readable. Up/down move through hosts; left/right move between columns. If all
hosts still cannot fit, use **Page Up/Page Down**; the footer shows the visible
range. **Home/End** select the first/last host and **Ctrl+U** clears the filter.
Filtering is case-insensitive and accepts abbreviated hostnames and multiple
search terms while preserving alphabetical order (ignoring case). Hosts are sorted
down each column, then continue in the next column. The Linux tmux popup uses
the full client size; run `bin/reload` after updating to apply its new dimensions.

Picker tag checks disable `CanonicalizeHostname` so building the list does not
wait for DNS lookups, including when a VPN or private DNS is unavailable. Put
`Tag dalftui` on the original alias or a matching rule; tags that require a
DNS-expanded hostname do not apply to the list. Actual connections retain your
configured hostname canonicalization.

The filtered list is cached between picker launches. Each launch checks the
contents of the configuration and recursively included files, including new or
deleted files matching `Include` patterns. It runs OpenSSH again when those
inputs, the SSH executable, or the cache format change. The first launch and a
launch after edits still rebuild the list.

Configurations with dynamic or unsupported `Match` conditions, environment
expansion, or include paths the scanner cannot track bypass caching. Static
`Match host`, `originalhost`, `tagged`, `all`, `canonical`, and `final` rules can
use the cache. Missing, unreadable, or corrupt caches fall back to discovery;
failed SSH evaluations are never cached. SSH connections still read live settings.

The cache lives at `%LOCALAPPDATA%\dalftui\hosts-cache.json` on Windows, or
`$XDG_CACHE_HOME/dalftui/hosts-cache.json` on Linux (defaulting to
`~/.cache/dalftui/hosts-cache.json`). To force a rebuild, run
`mise run ssh:list -- --refresh-hosts`, or add `--refresh-hosts` when launching
`bin/ssh_picker.py --pick`.

A configured `User`, including one supplied through a wildcard or included
configuration, is used automatically. Otherwise the new window asks for the
login. A destination such as `user@host` already provides its username.
On Linux and Windows, the launcher then sets the window or tab title to
`username@host-alias`, even when remote tmux supplies no title. Remote applications
can still update it. Linux SSH windows enable Alacritty's dynamic titles for this
window only; redirected command output contains no title escape sequences.

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
Without it, remote tmux uses the server's existing configuration and bindings. Shift+drag
selection works either way; the plain-drag reminder and OSC 52 clipboard writes
need the shared configuration.

## Open the current folder in VS Code

Press **Ctrl+Shift+F3** in an Alacritty pane to open its directory in a new local
VS Code window. Install VS Code's `code` command on your desktop.

In an SSH window opened through **Ctrl+Shift+F2** to a server with a compatible
dalftui bridge installed, the same shortcut opens the remote pane's directory
in local VS Code using Microsoft's **Remote - SSH** extension. VS Code uses
the same SSH host alias and login as the picker, so your
SSH configuration supplies the hostname, keys, port, and jump hosts. This uses
VS Code's documented [remote folder command](https://code.visualstudio.com/docs/remote/troubleshooting#_connect-to-a-remote-host-from-the-terminal).

Update dalftui and run `./bin/reload` on both machines. Reconnect older SSH windows
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

### Bridge version compatibility

The desktop checks for `bin/vscode.py` and checks the remote protocol with
`python3 ~/.config/dalftui/bridge_protocol.py --version` before creating
credentials or starting forwarding. The desktop and server need the `bin/`
command layout and a supported protocol declaration; they do not need identical
Git revisions. Installations with the previous root command layout, without a
readable protocol declaration, or declaring an unsupported version keep normal
tmux login but skip the VS Code bridge. The launcher suggests updating dalftui
from [GitHub](https://github.com/dalf/dalftui) on that server. It does not download
or deploy the desktop checkout. Servers without tmux or without dalftui still
connect silently as described above.

Update from the server's existing checkout, then reconnect:

```sh
git pull --ff-only
./install
./bin/reload
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

### Connect from Windows

The Windows launcher runs in PowerShell or Command Prompt. It needs Python
3.11+, Windows OpenSSH, [Oh My Posh](https://ohmyposh.dev/) (`winget install
JanDeDobbeleer.OhMyPosh`), and Windows VS Code with **Remote - SSH**. The `code`
command should be on an absolute PATH entry during setup. The host picker also
needs OpenSSH 9.4+ for `Tag dalftui`. The full-screen grid uses Python's native
Windows console support; no local tmux, Alacritty, or curses package is needed.
The picker requires an interactive terminal. Direct connections with `dssh HOST`
remain available when the console cannot run the picker.

Clone the repository once on Windows, then install from PowerShell:

```powershell
git clone https://github.com/dalf/dalftui.git "$HOME\code\dalftui"
cd "$HOME\code\dalftui"
.\install.cmd
```

`install.cmd` runs `install.ps1` in Windows
PowerShell 5.1 with `-NoProfile -ExecutionPolicy Bypass`. The bypass applies only
to the installer process. The wrapper forwards options and returns the
installer's exit status; it also works from Command Prompt.
It clears inherited module paths for the child so that launching it from
PowerShell 7 uses Windows PowerShell's own modules.

Setup records the absolute `Code.exe` path in
`%LOCALAPPDATA%\dalftui\config.json`. Folder launches use only that configured
installation; they never search the current project. Initial discovery requires
fully qualified drive or UNC paths; empty and relative PATH entries, including
`C:bin` and `\bin`, are ignored. To select an unpackaged or
portable installation explicitly, pass its directory or executable:

```powershell
.\install.cmd -VSCodePath 'C:\Tools\VS Code Portable'
# or: .\install.cmd -VSCodePath 'C:\Tools\VS Code Portable\Code.exe'
```

Explicit `-VSCodePath` values also accept the installation's `bin/code` or
`bin/code.cmd` launcher. From Git Bash, `/c/...` drive paths are supported:

```sh
mise run install:windows -- -VSCodePath '/c/Users/Your Name/AppData/Local/Programs/Microsoft VS Code/bin/code'
```

Setup and folder launches support both flat and versioned VS Code installations.
For versioned installations, the installed `bin/code.cmd` identifies the active
CLI; updates can switch versions without changing the saved `Code.exe` path.

If that installation is moved or removed, folder opening fails without trying
another executable and tells you to rerun setup. Use `-VSCodePath` again when
moving a portable installation.

Setup configures the native SSH picker and shell integration without installing
packages or requiring a package manager.

Setup adds a managed block to the current user's console profiles for Windows
PowerShell 5.1 and PowerShell 7 when installed, regardless of which version runs
the installer. It discovers each shell's
[PowerShell profile](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_profiles).
It backs up an existing profile before changing it, preserves your personal
settings, and loads `bin/profile.ps1` from this checkout. Repeated setup keeps one
managed block per profile; rerun it if you move the checkout or install another
PowerShell version. After `mise run install:windows` or `install.cmd`, open a new
PowerShell session to use `dssh` and **Ctrl+Shift+F3**. Use `-ProfilePath PATH` to
configure only a specific profile, including a different PowerShell host.

The profile draws the prompt with Oh My Posh and `config/oh-my-posh.omp.json`.
Setup installs Hack Nerd Font for the current user when it is missing, and sets
it as the font face in Windows Terminal's `profiles.defaults`. A profile with its
own font face keeps it.

The profile enables bash-like Emacs line editing, with **Ctrl+Left/Right** moving
by word and history suggestions where PSReadLine supports them. As in tmux,
**Ctrl+B** is a prefix: **Ctrl+B, then Ctrl+B** moves back one character. The window title
shortens long paths to their last two folders (`…\Local\Temp`) and starts with 🛡️
in an administrator session.

The profile adds a Unix-like `touch`, and `du`, `df` and `wc` unless such programs
are on PATH. When installed,
`lsd`, `wget2`, `btop`, `gsudo` and `bat` replace `ls`, `wget`, `htop`, `sudo` and
`cat`; setup does not install them.

In **Windows Terminal**, setup also installs **Ctrl+Shift+F2**: open a new local
tab, pick a host, and connect using remote tmux when available or a plain shell.
The shortcut works while the current tab is in SSH, tmux, or another program.
It uses Terminal's
[new-tab action](https://learn.microsoft.com/en-us/windows/terminal/customize-settings/actions#new-tab)
and keeps your default profile and appearance.
After choosing a host, the launcher sets the tab title to `username@host-alias`
using the effective SSH username (or the login you enter). This also works when
remote tmux does not set a terminal title; remote applications can still update it.

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
When PowerShell 7 is installed, setup turns on ClearType in Terminal's own PowerShell
profile and adds **Windows PowerShell 7 (Admin)**, which opens it as administrator
(Terminal 1.13+). Profiles you already have, or later edit, are kept.
If no settings are found, open Windows Terminal once and rerun setup. For a
portable installation, pass its settings path explicitly:

```powershell
.\install.cmd -TerminalSettingsPath 'C:\Tools\Terminal\settings\settings.json'
```

Use `-SkipTerminal` to configure only PowerShell integration. The tab launcher reads
this checkout each time, so later Git updates apply to new tabs. Rerun setup
after moving the checkout or replacing the PowerShell installation used by setup.

If a new PowerShell session reports that scripts are disabled when loading
your profile, enable local scripts for your user, then open a new session:

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
to cancel. **Ctrl+O** connects to exactly what you typed, including a destination
outside the list. The grid uses the full tab and adds columns when space permits; resizing
the tab immediately updates the layout. Selection connects in the current terminal window. SSH uses the
configured username; if none is configured, the launcher asks for one. It
creates or reattaches tmux using the usual session policy when tmux is installed,
or silently opens a plain login shell otherwise. With a compatible remote
dalftui bridge installed, **Ctrl+Shift+F3** opens the active pane's remote folder
in Windows VS Code.
**Ctrl+B, then F3** remains available as a tmux fallback.

Without PowerShell setup, including from Command Prompt, you can run the
launcher directly:

```powershell
py -3 "$HOME\code\dalftui\bin\ssh_picker.py" --pick
py -3 "$HOME\code\dalftui\bin\ssh_picker.py" --connect my-vm
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
./bin/reload
```

For later Windows updates, run `git pull --ff-only` in the Windows checkout,
reload your profile with `. $PROFILE` or open a new PowerShell session, and start
a new connection. After the one-time `bin/` layout migration, the profile follows
the checkout; no reinstall is needed for later updates.

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
and `./bin/reload`, adding `--tmux-only` when installing on a server. For a local checkout without a remote, create an empty remote
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
│   ├── host_picker.py
│   ├── vscode.py
│   ├── linux/
│   │   ├── alacritty_config.py
│   │   ├── setup.py
│   │   ├── shortcuts.py
│   │   ├── ssh_picker.py
│   │   ├── tmux_editor.py
│   │   ├── remote_bootstrap.py
│   │   ├── ops.py
│   │   ├── package-status.sh
│   │   ├── system-status.sh
│   │   └── tmux-start.sh
│   └── windows/
│       ├── ssh.py
│       ├── host_picker.py
│       ├── vscode.py
│       ├── terminal_settings.py
│       ├── setup.ps1
│       ├── profile.ps1
│       └── ssh-tab.ps1
├── bridge_protocol.py
├── mise.toml
├── install
├── install.cmd
├── install.ps1
├── bin/
│   ├── reload
│   ├── shortcuts.py
│   ├── ssh_picker.py
│   ├── vscode.py
│   ├── terminal_settings.py
│   ├── profile.ps1
│   ├── ssh-tab.ps1
│   └── tmux-start.sh
├── config/
├── tests/
│   ├── test_windows_launcher.py
│   ├── test_windows_terminal.py
│   ├── test_bridge_protocol.py
│   ├── test_bridge_lifecycle.py
│   ├── test_remote_bootstrap.py
│   └── fixtures/
│       ├── bridge_protocol_v1.py
│       ├── bridge_protocol_v2.py
│       ├── ssh_bootstrap_v1.py
│       └── ssh_bootstrap_v2.py
└── vendor/
    └── catppuccin/
```

[dalftui/ssh.py](dalftui/ssh.py) owns shared host/tag/login evaluation, picker dispatch,
SSH arguments, and connection orchestration. [dalftui/host_picker.py](dalftui/host_picker.py)
owns the responsive grid, filtering, and navigation; platform adapters handle console I/O.
[dalftui/vscode.py](dalftui/vscode.py)
owns URI construction, editor launching, both Unix and TCP bridge transports,
authentication, and lifecycle handling. Platform modules own local operating-system
integration. Directory placement describes the environment targeted by code;
portable helpers can be imported on other operating systems.
In particular, [dalftui/linux/remote_bootstrap.py](dalftui/linux/remote_bootstrap.py)
generates Linux-server shell programs from portable Python and is also used by
Windows desktops. [dalftui/linux/ops.py](dalftui/linux/ops.py) generates the
optional ops layout and bounded saved-check runner, embedding the read-only
checks from `dalftui/linux/package-status.sh` and `dalftui/linux/system-status.sh`.
[dalftui/linux/tmux-start.sh](dalftui/linux/tmux-start.sh) is
the canonical startup policy: `bin/tmux-start.sh` forwards local startup, while
remote execution embeds the canonical policy directly.

Installation entrypoints stay at the root; runtime and maintenance commands
live in `bin/`:

| Path | Role |
| --- | --- |
| [install](install) | Linux installation CLI |
| [install.cmd](install.cmd) | Windows installation launcher with a process-scoped execution-policy bypass |
| [install.ps1](install.ps1) | Windows PowerShell installation CLI |
| [bin/reload](bin/reload) | Linux configuration reload CLI |
| [bin/shortcuts.py](bin/shortcuts.py) | Shortcut-guide launcher |
| [bin/ssh_picker.py](bin/ssh_picker.py) | Shared SSH launcher |
| [bin/vscode.py](bin/vscode.py) | Shared editor launcher and remote discovery target |
| [bin/profile.ps1](bin/profile.ps1) | PowerShell profile loader |
| [bin/ssh-tab.ps1](bin/ssh-tab.ps1) | Terminal SSH-tab launcher |
| [bin/terminal_settings.py](bin/terminal_settings.py) | Terminal settings CLI |
| [bin/tmux-start.sh](bin/tmux-start.sh) | Local terminal startup target |
| [bridge_protocol.py](bridge_protocol.py) | Canonical standalone contract and version declaration |

Each launcher resolves the checkout and forwards to the package implementation.
No pip installation or particular working directory is required. The previous
root runtime paths have been removed. After updating from that layout, rerun
`./install` and `./bin/reload` on Linux, or `.\install.cmd` on Windows, to
regenerate links, profile entries, and Terminal actions. `bridge_protocol.py`
contains the actual contract and version declaration; it is not a forwarding
wrapper.

### Filename conventions

These conventions apply to filenames, directories, and placement:

- Importable Python modules and package directories use `snake_case`.
- Python command launchers in `bin/` also use `snake_case`.
- Shell and PowerShell script filenames use lowercase words, with hyphens when
  needed. Prefer purpose-specific names such as `profile.ps1`, `ssh-tab.ps1`,
  and `terminal_settings.py`.
- Platform directories normally supply the platform context; avoid redundant
  platform prefixes within them.
- Tests stay flat and use `test_<feature>.py`. Windows-focused launcher and
  integration suites may use `test_windows_<feature>.py`; shared bridge tests
  use feature names without a Windows label.
- Historical fixtures keep their versioned names and remain frozen. Vendored
  upstream filenames remain unchanged.

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
so remote tmux startup works without a dalftui installation.
[bin/tmux-start.sh](bin/tmux-start.sh) forwards local startup to that canonical
policy; Alacritty invokes it through the installed checkout link.

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
the deliberate rejection of the new layout by older desktops, while the frozen
v2 probe in [tests/fixtures/ssh_bootstrap_v2.py](tests/fixtures/ssh_bootstrap_v2.py)
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

## Repository tasks

[mise](https://mise.jdx.dev/getting-started.html) 2026.7.5+ runs the commands
defined in [mise.toml](mise.toml). It uses your existing Python and uv installations;
tasks run from the repository root even when invoked from a subdirectory.
After installing mise, trust the checkout and list its tasks:

```sh
mise trust
mise tasks
```

| Task | Purpose |
| --- | --- |
| `mise run check` | Spelling, Pylint, then all tests for the current platform |
| `mise run spellcheck` | Pinned codespell check through uv |
| `mise run pylint` | Pinned Pylint check of Python source, entrypoints, and tests (alias: `lint`) |
| `mise run test` | Full Linux discovery, or Windows Python and PowerShell suites |
| `mise run test:linux` | Full Python discovery, including Linux integration tests |
| `mise run test:windows` | Windows launcher/Terminal and shared bridge Python suites |
| `mise run test:bridge` | Shared bridge lifecycle and historical compatibility tests |
| `mise run test:powershell` | Windows setup and profile integration |
| `mise run install:linux` | Linux installation through `./install` |
| `mise run install:windows` | Windows installation through `install.ps1` |
| `mise run reload:linux` | Reload Linux settings through `./bin/reload` |
| `mise run ssh:list` | List SSH picker hosts without opening a connection |

`mise run` defaults to `check`. Use installation and reload tasks on their target
platform. They accept the existing scripts' options after `--`:

```sh
mise run install:linux -- --dry-run
mise run install:linux -- --tmux-only --dry-run
mise run reload:linux -- --socket /path/to/socket
```

Windows tasks use Windows PowerShell 5.1 by default. To install or test using
PowerShell 7 instead, set `DALFTUI_POWERSHELL` to `pwsh`:

```powershell
$env:DALFTUI_POWERSHELL = 'pwsh'
mise run test:powershell
mise run install:windows -- -VSCodePath 'C:\Tools\VS Code Portable'
```

The selected shell runs the installer; setup configures both installed PowerShell
versions unless `-ProfilePath` selects a single profile. The installers and
`bin/` launchers remain available for direct use. GitHub Actions uses these same tasks while
selecting Python and PowerShell versions through its existing matrix.

## Verification

Run spelling, Python lint, and functionality checks from the repository root with
[uv](https://docs.astral.sh/uv/getting-started/installation/) installed:

```sh
mise run check
mise run ssh:list
```

Codespell checks documentation, source, tests, configuration, and hidden files
such as CI workflows using [.codespellrc](.codespellrc). Vendored code, frozen
historical fixtures, and local artifacts are excluded. The pinned version in the
`spellcheck` task keeps local and CI checks consistent. uv manages the tool's isolated
environment automatically.

`mise run pylint` runs Pylint 4.1.2 through uv using the current platform's
`python3` or `python` interpreter and [.pylintrc](.pylintrc). It checks `dalftui/`,
the Python command entrypoints (including `install` and `bin/reload`), the standalone
bridge contract, and `tests/`. Vendored code and frozen historical fixtures are
excluded. The configuration targets Python 3.11, disables docstring requirements,
line-length and size heuristics, and recognizes the checkout's import/bootstrap
and resource-lifecycle patterns. Error and warning checks such as undefined names,
bad calls, unused imports, and unsafe defaults remain enabled. Output contains
diagnostics without reports or scores; any enabled diagnostic fails the task.
Both CI workflows run this same check before functionality tests. Use
`mise run pylint` or `mise run lint` to run it separately.

On Windows, the task exempts only the exact Unix API names listed in
`windows_lint_members` in [mise.toml](mise.toml) from member inference. Those APIs
are used by Linux code or guarded tests and are unavailable to Windows Python.
Linux lint checks them normally; other missing-member checks remain enabled on
both platforms.

Tests use disposable directories, OpenSSH's configuration evaluator, and private
tmux sockets. They do not open SSH connections or touch your live tmux sessions.
They cover backups, rollback, repeated installation, updates through the link,
personal overrides, both shortcut guides, tag filtering, mode switching,
reloads that preserve pane processes and Claude status, and the clipboard and
mouse-selection bindings loaded into a real tmux server. The CLI is also tested
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
System overview tests use fake tools and local files to cover unavailable tools,
permission failures, timeouts, empty journal matches, overlay roots, disk/inode
warnings, and degraded software RAID without contacting an SSH server.
Bridge protocol tests exercise frozen v1 messages and historical peers in both
directions, reject unsupported versions without editor launches, and check the
remote declaration before credential setup.

The Windows-compatible launcher and Terminal suites run separately without tmux
or curses. In PowerShell, run spelling and Pylint before the Python suites:

```powershell
mise run spellcheck
mise run pylint
```

Run the launcher, Terminal, and shared bridge suites:

```sh
mise run test:windows
```

This runs `test_windows*.py` discovery, selecting
[tests/test_windows_launcher.py](tests/test_windows_launcher.py)
and [tests/test_windows_terminal.py](tests/test_windows_terminal.py), followed by
`test_bridge*.py` discovery.
Run the shared bridge lifecycle and historical compatibility suites separately:

```sh
mise run test:bridge
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
mise run test:powershell
```

GitHub Actions runs the full Linux suite on Ubuntu with Python 3.11 and 3.14,
installing tmux, OpenSSH, Git, and less for the integration tests.
Both Linux and Windows CI run the same pinned spelling and Pylint checks before
the Python test suites. CI also runs native Windows tests with Python 3.11 and 3.14, in
PowerShell 5.1 and 7. They cover installation without package managers,
profile backups and repeated setup, safe VS Code discovery and portable-path
configuration, the `dssh` command, native picker rendering and navigation, SSH tag and login
resolution, TCP authentication, and connection token handling. Isolated bridge
tests also cover slow input deadlines, concurrent requests, capacity rejection
and recovery, shutdown races, and interruption of readers and editor CLI waits.
A harmless native executable probe verifies that a project-local `Code.exe` is not run;
another verifies the configured `Code.exe` + `cli.js` argument list and encoded
local and remote folder URIs. Linux runs the cross-platform suite and simulated
Windows launch tests. GUI launches and interactive SSH connections remain
mocked; no automated test opens the VS Code GUI or an SSH connection.
