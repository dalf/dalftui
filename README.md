# dalftui

A Linux Alacritty/tmux configuration with a black, high-contrast terminal,
rounded tabs, pane shortcuts, a searchable shortcut guide, and an SSH picker.
The tab design preserves the optional claude-tabstatus integration: the active
light pill uses dark status circles, and inactive dark pills use light circles.

## Install once

Requirements: Python 3.11+, Alacritty 0.14+, tmux 3.4+, OpenSSH 9.4+, Git,
and `less`. The installer configures software that is already installed. It
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
| `~/.config/alacritty/alacritty.toml` | Imports shared Alacritty settings, then personal overrides |
| `~/.tmux.conf` | Sources shared tmux settings, then personal overrides |
| `~/.config/tmux/shortcuts.py` | Compatibility link to the shortcut guide |

`XDG_CONFIG_HOME` and `XDG_STATE_HOME` are respected when they contain absolute
paths. The tmux loader remains at `~/.tmux.conf` so tmux finds it consistently.

Running `./install` again preserves personal overrides and leaves an existing
installation untouched. It can also reconnect the configuration link if you
move the checkout. Keep the checkout outside the managed `~/.config/dalftui`
path; the installer refuses to replace an existing directory there.

## Update without reinstalling

After a Git remote is configured:

```sh
cd ~/code/dalftui
git pull --ff-only
./reload
```

The symlink makes new repository files available immediately. The helper
scripts read their configuration whenever you open them. `./reload` requests
an Alacritty refresh and sources tmux's configuration again without ending
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
- **Ctrl+B, then F2:** choose an SSH host and open a separate Alacritty window.
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

## Theme and Claude integration

The required Catppuccin tmux v2.3.1 configuration files are bundled under
`vendor/catppuccin`, including their upstream MIT license. No theme download or
plugin manager is needed. The custom rounded tab design is in `config/tmux.conf`.

[claude-tabstatus](https://github.com/dalf/claude-tabstatus) is an optional,
separate project. Existing installations continue to supply repository/branch
labels and status through pane titles and `@cctab_window_strip`. dalftui preserves
that integration and does not change Claude hooks. Without it, ordinary tmux
window names are displayed.

## Repository

On a new machine, clone your repository to a stable path and run `./install`
and `./reload`. For a local checkout without a remote, create an empty remote
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
personal overrides, the shortcut guide, tag filtering, and reloads that preserve
pane processes and Claude status.
