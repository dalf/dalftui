# Installation reference

Full detail behind the install steps in the [README](../README.md#install-everything).

## Linux desktop

Requirements: Python 3.11+, Alacritty 0.14+, tmux 3.2+, OpenSSH 9.4+, Git,
`less`, and [Oh My Posh](https://ohmyposh.dev/docs/installation/linux) for the
desktop mode. The server mode below needs Python 3.11+, tmux 3.2+, Git, `less`,
and Oh My Posh. The installer configures software that is already installed. It
uses no package manager, root access, or Python packages. The only download is
the desktop mode's font: when `fc-list` does not show Hack Nerd Font, the
installer runs `oh-my-posh font install Hack`.

Keep the checkout at a stable path, such as `~/code/dalftui`, then run:

```sh
cd ~/code/dalftui
./install --dry-run
./install
./bin/reload
```

Optional [mise tasks](development.md#repository-tasks) provide named shortcuts for installation,
reloads, spelling, and tests.

On Windows, use `.\install.cmd`; see [Connect from Windows](#windows).

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

When the `code` command or `~/.config/Code` exists, the desktop mode sets
`terminal.integrated.fontFamily` and `terminal.integrated.fontSize` in VS Code's
user settings, replacing your values and keeping the rest of the file.

`XDG_CONFIG_HOME` and `XDG_STATE_HOME` are respected when they contain absolute
paths. The tmux loader remains at `~/.tmux.conf` so tmux finds it consistently.

Running `./install` again preserves personal overrides and leaves an existing
installation in its current mode. It can also reconnect the configuration link if you
move the checkout. Keep the checkout outside the managed `~/.config/dalftui`
path; the installer refuses to replace an existing directory there.

## Linux server (`--tmux-only`)

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
[selection rules](tmux.md#selecting-and-copying) shared with Windows Terminal. The guide reads
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

## macOS

For Terminal.app or iTerm2 with zsh. Requirements: Python 3.11+, tmux 3.2+, Git,
`less` and Oh My Posh. Git, `less` and an older `python3` come with macOS; get the
rest from Homebrew and make sure `brew shellenv` runs in your shell setup so
`python3`, `tmux` and `oh-my-posh` resolve to Homebrew's:

```sh
brew install python tmux oh-my-posh
./install --dry-run
./install
./bin/reload
```

On a Mac, `./install` uses the `macos` mode; `--desktop` (Alacritty) is refused
and `--tmux-only` still works (`./install --macos` switches back). Compared with
the server mode, it also:

- appends the marked prompt line pair sourcing `config/prompt.zsh` to `~/.zshrc`
  (or `$ZDOTDIR/.zshrc`), not `~/.bashrc`;
- installs Hack Nerd Font into `~/Library/Fonts` unless `~/Library/Fonts` or
  `/Library/Fonts` already holds it, but does not select it: choose *Hack Nerd
  Font* under Settings > Profiles > Text (Terminal.app: Font > Change; iTerm2: Font);
- sets VS Code's terminal font in `~/Library/Application Support/Code/User/settings.json`
  when that folder or the `code` command exists;
- does not force 24-bit color, which Terminal.app lacks before macOS 26; tmux
  detects it in iTerm2 and, from tmux 3.6, in terminals setting `COLORTERM=truecolor`;
- makes tmux copy-mode copies use `pbcopy`, because Terminal.app does not support
  OSC 52. A program's own OSC 52 write did not reach the clipboard on CI (no
  terminal attached there); in iTerm2 it needs *Applications in terminal may
  access clipboard*.

Keys and terminals:

- **Ctrl+B, then F1 / F3** open the guide and VS Code. Apple keyboards need Fn for
  F-keys unless they are set as standard function keys.
- **Ctrl+Shift+F1 / F3** should work in iTerm2 without configuration (untested). In Terminal.app
  add them under Settings > Profiles > Keyboard: Ctrl+Shift+F1 sends `\033[1;6P`,
  Ctrl+Shift+F3 sends `\033[1;6R`.
- **Ctrl+B, then F2** (SSH picker) is not bound, as on a server.
- **F3** opens local VS Code only and needs its `code` command on the PATH of the
  shell that started tmux (VS Code: *Shell Command: Install 'code' command in PATH*).
  Relaying to the editor of a client connected over SSH is not supported on a Mac.
- **Selecting:** hold Fn (Terminal.app) or Option (iTerm2) while dragging;
  Cmd+C copies.
- **Ctrl+Alt+arrow** pane keys need Option to act as Meta (Terminal.app: *Use
  Option as Meta key*; iTerm2: *Left Option key: Esc+*). dalftui does not set it:
  it stops Option from typing characters such as `@`, `#`, `[` on AZERTY and other
  non-US layouts. Ctrl+Left/Right also switch Mission Control spaces by default.

Uninstall works as on Linux; the font is kept. GitHub's macOS CI checks
installation, the prompt, tmux settings, copy-mode copies and uninstall in a
temporary home. Keys and selection are untested in a real Terminal.app or iTerm2.

## Update without reinstalling

When updating from the previous root command layout, rerun `./install` on each
Linux machine or `.\install.cmd` on Windows once; see
[Layout and entrypoints](development.md#layout-and-entrypoints). Later updates use the commands below.

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

## Personal settings and backups

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

## Uninstall

Uninstall removes what the installer created, only while it still holds the
installer's content, and backs up every file it changes or removes. Preview it first:

```sh
./install --uninstall --dry-run
./install --uninstall
```

On Linux and macOS it removes the `~/.config/dalftui` link, the `~/.config/tmux/shortcuts.py`
link, the generated `~/.tmux.conf` and Alacritty loaders, the marked prompt line
pair in `~/.bashrc` and `~/.zshrc`, and VS Code's `terminal.integrated.fontFamily` and
`terminal.integrated.fontSize` while they are still `Hack Nerd Font` and `12`.
When a backup holds the `~/.tmux.conf` or `alacritty.toml` file or link you had
before dalftui, it is put back. An edited loader (with the `~/.config/dalftui` link
it sources), an edited prompt line, symlinks the
installer did not create, and personal `local.conf` and `local.toml` files are kept
and reported; the override files are removed only while they are the unchanged
templates. The removed VS Code values may have replaced your own: the earlier
values are in the backups. Fonts, Oh My Posh, the backups, and the checkout are
kept. Running tmux and Alacritty keep their current configuration until restarted.

On Windows:

```powershell
.\install.cmd -Uninstall -DryRun
.\install.cmd -Uninstall
```

This removes the managed block from each PowerShell profile (or the one given
with `-ProfilePath`). A block that contains other lines is kept and reported. It
removes the Ctrl+Shift+F2 and F3 actions and their keybindings from Windows
Terminal, the **Windows PowerShell 7 (Admin)** profile, ClearType from Terminal's
PowerShell 7 profile, and the default `Hack Nerd Font` face, and the VS Code font
settings above, in each case while they still hold the values setup wrote.
`-TerminalSettingsPath`, `-VSCodePath` and `-SkipTerminal` work as for setup;
`-VSCodePath` may name a directory whose `Code.exe` was removed.
Each changed file is first copied to `<file>.dalftui-<id>.bak`, where earlier
values can be found. `%LOCALAPPDATA%\dalftui\config.json`, the font, and the
checkout are kept. PowerShell sessions that are already open keep `dssh` until
you open a new one.

Running uninstall again reports that nothing is left to remove, and installing
again afterwards works as a fresh installation.

## Windows

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
It also sets `terminal.integrated.fontFamily` to Hack Nerd Font and
`terminal.integrated.fontSize` to 12 in the configured VS Code's `settings.json`
(in `data\user-data` for a portable installation), creating the file when needed.

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

### Update on Windows

For later Windows updates, run `git pull --ff-only` in the Windows checkout,
reload your profile with `. $PROFILE` or open a new PowerShell session, and start
a new connection. After the one-time `bin/` layout migration, the profile follows
the checkout; no reinstall is needed for later updates.
