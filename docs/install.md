# Installation reference

Full detail behind the install steps in the [README](../README.md#installation-and-update-strategy).

## Linux desktop

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Alacritty 0.14+,
tmux 3.2+, OpenSSH 9.4+, Git, `less`, and
[Oh My Posh](https://ohmyposh.dev/docs/installation/linux) for the desktop mode.
The server mode below needs Python 3.11+, uv, tmux 3.2+, Git, `less`, and Oh My
Posh. `./install`, `./bootstrap` and `bin/reload` run with `python3`; the tmux
keys run dalftui's Python with `uv run` and also look for uv in `~/.local/bin`,
which a tmux server started over SSH may lack on its PATH. The installer
configures software that is already installed. It uses no package manager, root access, or Python packages; on Fedora, Debian and
Ubuntu, the separate [`./bootstrap`](#new-machine-fedora-debian-ubuntu) installs them with dnf or apt
(on Windows, with [Scoop](#new-machine-windows)). The only download is
the desktop mode's font: when `fc-list` does not show Hack Nerd Font, the
installer runs `oh-my-posh font install Hack`.

Keep the checkout at a stable path, such as `~/code/dalftui`, then run:

```sh
cd ~/code/dalftui
./install --dry-run
./install
```

`./install` then reloads running tmux and Alacritty.

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
```

Server requirements are **Python 3.11+, uv, tmux 3.2+, Git, `less`, and Oh My Posh**. Alacritty
and the SSH picker's OpenSSH 9.4 requirement apply to the desktop mode. The
server installer manages the shared configuration link, tmux loader, shortcut
guide link, `~/.config/tmux/local.conf`, and the `~/.bashrc` prompt line. It
preserves existing Alacritty files and installs no font: your local terminal draws the icons.

The server uses the same rounded tabs, Claude status styling, pane bindings,
and history settings. **Ctrl+B, then F1** opens a guide with native tmux keys,
plus the [selection rules](tmux.md#selecting-and-copying) shared with Windows Terminal. The guide reads
live tmux bindings and does not try to read Alacritty settings on the server.
**Ctrl+B, then F2** is disabled in server mode because its picker launches a
local Alacritty window.

On tmux 3.2, popup windows use a plain border and the terminal's default colors,
and history searches share the normal command prompt history. tmux 3.3+ adds
the styled popup border and separate search history. The rounded tab design and
Claude status colors are the same on every supported version.

Your local terminal renders the fonts and rounded glyphs. Use the desktop SSH
picker to open a direct remote tmux session; tmux keys then reach remote tmux.
An SSH connection started inside a local tmux pane creates nested sessions,
where the local tmux handles **Ctrl+B** first.

The installation mode is recorded in the private `~/.tmux.conf` loader and
survives Git updates. Both `./bin/reload` and a repeated `./install` recognize it,
so you do not need to repeat the flag after installation. Use `./install --desktop`
or `./install --tmux-only` to explicitly switch modes. Mode changes back up the
previous loader and preserve personal overrides. Older desktop loaders are
recognized and safely migrated on the next installation.

To receive later configuration updates on the server:

```sh
git pull --ff-only
./install
```

## New machine (Fedora, Debian, Ubuntu)

`./bootstrap` is opt-in and separate from `./install`, which keeps configuring
software only. Its package list is the owner's personal tool set. Python 3.11+
and Git must exist first; on a new machine:

```sh
sudo dnf install -y python3 git && git clone https://github.com/dalf/dalftui ~/code/dalftui && ~/code/dalftui/bootstrap
```

On Debian or Ubuntu (a server):

```sh
sudo apt-get update && sudo apt-get install -y python3 git && git clone https://github.com/dalf/dalftui ~/code/dalftui && ~/code/dalftui/bootstrap --tmux-only
```

Debian installed with a root password gives your user no sudo: run
`su -c "apt-get install -y sudo && usermod -aG sudo $USER"`, then log out and
back in. The desktop mode needs Alacritty 0.14+,
so it works on Fedora and Debian 13; on Debian 12 and Ubuntu 24.04 the packages
install but `./install` then fails, so use `--tmux-only` there. Ubuntu 22.04 is
refused: its Python is 3.10.

Each run, in order (a failed step does not stop the next ones):

1. Updates its own checkout with `git pull --ff-only` and restarts if new
   commits arrived. It skips this on a detached HEAD, without an upstream branch,
   or with uncommitted changes to tracked files.
2. Asks for the sudo password once and adds
   [GitHub CLI's repository](https://github.com/cli/cli/blob/trunk/docs/install_linux.md)
   (its key and `/etc/yum.repos.d/gh-cli.repo`, or `/etc/apt/sources.list.d/github-cli.sources`
   on apt) when that file, or the `github-cli.list` from GitHub's instructions, is missing; the
   distribution's `gh` is old or broken and is upgraded from it. Unless `--tmux-only`, it adds Microsoft's
   [VS Code repository](https://code.visualstudio.com/docs/setup/linux) (its key
   and `/etc/yum.repos.d/vscode.repo`, or `/etc/apt/sources.list.d/vscode.sources`
   on apt) when that file is missing. A `code` package installed from a download
   is then upgraded from the repository. It adds [DVC's repository](https://dvc.org/doc/install/linux)
   the same way (`/etc/yum.repos.d/dvc.repo` or `/etc/apt/sources.list.d/dvc.sources`)
   on x86-64 only; elsewhere it skips both the repository and the `dvc` package.
   DVC's signing key expires 2027-03-04; if DVC rotates it, delete that file and
   rerun bootstrap.
3. Installs each missing package from
   [packages/fedora.txt](../packages/fedora.txt) or
   [packages/debian.txt](../packages/debian.txt) with its own `dnf install` or
   `apt-get install` (after one `apt-get update`), so one failure does not stop
   the others, and upgrades the listed installed packages with `dnf upgrade` or
   `apt-get install --only-upgrade`. Other system packages are not upgraded.
4. Installs Oh My Posh, mise and uv with their official installers
   ([Oh My Posh](https://ohmyposh.dev/docs/installation/linux), [mise.run](https://mise.jdx.dev/installing-mise.html),
   [uv](https://docs.astral.sh/uv/getting-started/installation/))
   into `~/.local/bin` when they are missing, otherwise runs `oh-my-posh upgrade`,
   `mise self-update --yes --no-plugins` and `uv self update`. A copy that the user cannot write,
   such as an rpm, is left alone.
5. Runs `./install` (with `--tmux-only` when given; otherwise the existing
   profile, or desktop on a new machine), which also reloads.
6. Prints a summary (`Installed`, `Upgraded`, `Skipped`, `Failed`) and exits
   with 1 when anything failed.

The package lists have one package per line; `#` starts a comment. The
packages after `[desktop]` (OpenSSH, Alacritty, VS Code, DVC, AWS CLI, rclone and fido2-tools) are skipped with
`--tmux-only`. On apt, bat's command is `batcat`, and yq is not installed:
Debian's `yq` package is a different program from the mikefarah/yq that Fedora has.

`--dry-run` changes nothing and writes no bootstrap log (`dnf` may refresh its
own cache; apt uses the package lists from the last `apt-get update`): it reads the installed and upgradable packages, does not fetch Git,
and previews `./install` once nothing is missing. Real runs append their commands and output to
`~/.local/state/dalftui/bootstrap.log` (or under `XDG_STATE_HOME`).

GitHub CI runs the bootstrap twice in fresh Fedora 44 and Debian 13 containers
(desktop) and Debian 12 and Ubuntu 24.04 containers (`--tmux-only`), weekly and
when the bootstrap changes, and checks that the second run changes nothing. It
also checks that Ubuntu 22.04 is refused.

## New machine (Windows)

The same `bootstrap` installs and updates the apps in
[packages/windows.txt](../packages/windows.txt) with [Scoop](https://scoop.sh/),
per user and without administrator rights, then runs `install.cmd`. In a
non-elevated Windows PowerShell on a new Windows 10 or 11 machine:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force; irm get.scoop.sh | iex; scoop install git uv; git clone https://github.com/dalf/dalftui "$HOME\code\dalftui"; & "$HOME\code\dalftui\bootstrap.cmd"
```

Run `& "$HOME\code\dalftui\bootstrap.cmd"` again at any time to update (`--dry-run` previews). It
checks for Scoop, Git and uv first. uv downloads a suitable Python when none is installed;
no `python` command is added. An elevated run is refused, as Scoop installs per user.

Each run updates the checkout as on Linux, adds the `extras` bucket when it is
missing, runs `scoop update`, installs each missing app with its own
`scoop install`, and runs `scoop update APP` for each listed app that its bucket
has newer; other apps are not updated. Installed versions, not Scoop's exit
status, decide the result. It then sets up OpenSSH, checks Windows Terminal,
runs `install.cmd`, and prints the same summary. The log is
`%LOCALAPPDATA%\dalftui\bootstrap.log`. A dry run changes nothing, compares
with the buckets as of the last `scoop update`, and does not run `install.cmd`.

Some steps need an administrator once. Bootstrap prints them and runs them
through `gsudo` in one UAC prompt, each only when needed: the VC++ runtime that
bat and mise need (Scoop's `vcredist2022` cannot run its installer elevated, so
bootstrap runs the `vc_redist.x64.exe` it downloaded), `Add-WindowsCapability
-Online -Name OpenSSH.Client~~~~0.0.1.0` when no client is installed, and
`Set-Service ssh-agent -StartupType Automatic; Start-Service ssh-agent`. On a standard account the prompt asks for an
administrator's password. Without a desktop (over SSH, or in CI) it changes
nothing and lists what is left to run. The client in `C:\Program Files\OpenSSH` (winget
`Microsoft.OpenSSH.Preview`) counts as installed. `Tag dalftui` needs 9.4+.

Bootstrap also sets `git config --global core.sshCommand` to that Windows
`ssh.exe` when it is unset, so Git uses the agent's keys; an existing value is
kept and listed. See [manual configuration](manual-configuration.md#windows-ssh-agent-and-forwarding)
for loading keys and forwarding them.

Not installed, only reported: Windows Terminal (from the Microsoft Store on
Windows 10; open it once so setup finds its settings). Scoop cannot update an
app that is running: PowerShell 7, when you run bootstrap from it, is reported
as in use; close it and run `scoop update pwsh` from Windows PowerShell.
`bootstrap.cmd` asks uv for a Python 3.11+ path (uv downloads one if needed)
and runs `bootstrap` with it, so uv is not running and can be updated.

GitHub CI runs the command on windows-latest as a standard user, twice, and
checks that the second run and a dry run change nothing. It runs as a scheduled
task, where msiexec is unavailable, so Scoop extracts MSIs with lessmsi there.

## New machine (macOS)

The same `bootstrap` installs and upgrades the formulae and casks in
[packages/Brewfile](../packages/Brewfile) with [Homebrew](https://brew.sh/), then
runs `./install`. On a new Apple Silicon Mac, in Terminal.app:

```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" && eval "$(/opt/homebrew/bin/brew shellenv)" && brew install uv && git clone https://github.com/dalf/dalftui ~/code/dalftui && ~/code/dalftui/bootstrap
```

Homebrew's installer asks for an administrator password once and installs the
Command Line Tools, which provide Git for the clone. The `eval` applies only to
that shell; as Homebrew's installer suggests, add it to `~/.zprofile` so that new
shells use Homebrew's `git` and `nano` rather than Apple's. An
existing Intel Homebrew in `/usr/local` should work but is untested. Apple's
`python3` is 3.9, so `bootstrap`, `install` and `bin/reload` run themselves
through `uv run --no-project --python ">=3.11" --script`; Homebrew's Python is not needed.

Run `~/code/dalftui/bootstrap` again at any time to update (`--dry-run` previews).
Each run updates the checkout as on Linux, runs `brew update`, then one
`brew bundle --file packages/Brewfile`, which installs the missing entries and
upgrades the outdated listed ones; other formulae are not upgraded. VS Code
updates itself, so Homebrew leaves it alone. Installed versions decide the
summary, which is the same as on Linux, and so is the log. A dry run changes
nothing and compares with `brew outdated` as of the last `brew update`. A root
run and `--tmux-only` are refused.

The Brewfile also installs the VS Code cask, which provides the `code` command,
and Hack Nerd Font into `~/Library/Fonts`.

GitHub CI runs the bootstrap on macos-latest (Homebrew preinstalled) twice, starting
with Apple's `python3`, checks that the second run and a dry run change nothing,
and that a tmux server started from a zsh login shell finds uv.

## macOS

For Terminal.app or iTerm2 with zsh. Requirements: uv, tmux 3.2+, Git, `less` and
Oh My Posh. Git and `less` come with macOS; get the rest from Homebrew, or run
the bootstrap above, and make sure `brew shellenv` runs in your shell setup:

```sh
brew install tmux oh-my-posh uv
./install --dry-run
./install
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
- makes tmux copy-mode copies use `pbcopy`, because Terminal.app does not support
  OSC 52. A program's own OSC 52 write did not reach the clipboard on CI (no
  terminal attached there); in iTerm2 it needs *Applications in terminal may
  access clipboard*.

Every profile, including `--tmux-only` on a Mac or a Linux SSH server, keeps
older Terminal.app clients in 256 colors. tmux detects iTerm2's 24-bit color
support automatically and, from tmux 3.6, also uses a client's
`COLORTERM=truecolor` setting. The dalftui SSH launcher supplies a per-attachment
RGB hint for Windows Terminal and other terminals declaring truecolor support;
the hint does not affect an older Terminal.app attached to the same server.

After upgrading from the earlier `*:Tc` override, run `./bin/reload` on each
affected server. Detach and reattach existing clients to their original sessions
to clear cached color capabilities; new clients already use the corrected
settings. Sessions and running programs are kept, without restarting tmux.

Keys and terminals:

- **Ctrl+B, then F1 / F3** open the guide and VS Code. Apple keyboards need Fn for
  F-keys unless they are set as standard function keys.
- **Ctrl+B, then F2** (SSH picker) is not bound, as on a server.
- **F3** opens local VS Code only and needs its `code` command on the PATH of the
  shell that started tmux (the Homebrew cask provides it; otherwise VS Code:
  *Shell Command: Install 'code' command in PATH*).
  Relaying to the editor of a client connected over SSH is not supported on a Mac.
- **Selecting:** hold Fn (Terminal.app) or Option (iTerm2) while dragging;
  Cmd+C copies.
- **Ctrl+B, then Ctrl+arrow** (resize pane): by default macOS takes all four
  Ctrl+arrow keys (Left/Right switch spaces, Up opens Mission Control, Down shows
  the app's windows); drag the pane border instead, or turn them off in System
  Settings > Keyboard > Keyboard Shortcuts > Mission Control.

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
./install
```

The symlink makes new repository files available immediately. The helper
scripts read their configuration whenever you open them. `./install` writes
nothing when nothing changed, then requests
an Alacritty refresh in desktop mode and sources tmux's configuration again without ending
sessions or restarting running programs. It rewrites the Alacritty loader in
place because file replacements from Git or an editor may not trigger a reload.

Settings that affect terminal startup apply to new Alacritty windows. If tmux
is not running, the reload leaves it stopped; the next server loads the updated
configuration. From inside tmux, reload targets the current server. Outside tmux,
it targets the default server. Use `--socket /path/to/socket` with `./install` or `./bin/reload` for
another server.

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
removes from Windows Terminal the Ctrl+Shift+F2 and F3 actions and keybindings
that earlier versions installed, the **Windows PowerShell 7 (Admin)** profile, ClearType from Terminal's
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

The Windows launcher runs in PowerShell or Command Prompt. It needs uv (which
provides Python 3.11+), Windows OpenSSH, [Oh My Posh](https://ohmyposh.dev/) (`winget install
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
PowerShell session to use `dssh`, **Ctrl+B, then F2** and **Ctrl+B, then F3**. Use `-ProfilePath PATH` to
configure only a specific profile, including a different PowerShell host.

The profile draws the prompt with Oh My Posh and `config/oh-my-posh.omp.json`.
Setup installs Hack Nerd Font for the current user when it is missing, and sets
it as the font face in Windows Terminal's `profiles.defaults`. A profile with its
own font face keeps it.
It also sets `terminal.integrated.fontFamily` to Hack Nerd Font and
`terminal.integrated.fontSize` to 12 in the configured VS Code's `settings.json`
(in `data\user-data` for a portable installation), creating the file when needed.

The profile enables bash-like Emacs line editing, with **Ctrl+Left/Right** moving
by word and history suggestions where PSReadLine supports them (2.1+;
Windows PowerShell 5.1 ships 2.0). As in tmux,
**Ctrl+B** is a prefix: **Ctrl+B, then Ctrl+B** moves back one character. The window title
shortens long paths to their last two folders (`…\Local\Temp`) and starts with 🛡️
in an administrator session.

The profile adds a Unix-like `touch`, and `du`, `df` and `wc` unless such programs
are on PATH. When installed,
`lsd`, `wget2`, `btop`, `gsudo`, `notepad++` and `bat` replace `ls`, `wget`, `htop`,
`sudo`, `notepad` and `cat`, and a `curl` outside Windows' folder replaces `curl`; setup does not install them.

At a local PowerShell prompt, **Ctrl+B, then F2** runs `dssh` to pick a host and
connect, using remote tmux when available or a plain shell. After choosing a
host, `dssh` sets the tab title to `username@host-alias` using the effective SSH
username (or the login you enter). This also works when remote tmux does not set
a terminal title; remote applications can still update it.

**Ctrl+B, then F3** opens the current directory in a new VS Code window:

- At a local PowerShell prompt, it uses the current filesystem directory and
  preserves any command you are typing.
- In remote tmux connected through `dssh`, it opens the active pane's directory
  in Windows VS Code with Remote - SSH, including while an app is running.

PowerShell setup installs the prompt handlers through
[PSReadLine](https://learn.microsoft.com/en-us/powershell/module/psreadline/set-psreadlinekeyhandler).
Other local shells and running
local programs need their own handler; use a PowerShell prompt for local folders.

Setup finds existing Stable, Preview, Canary, and unpackaged Terminal settings.
It backs up each changed `settings.json`, preserves comments and other settings,
and adds no duplicates on repeated runs. It removes the Ctrl+Shift+F2 and F3
actions installed by earlier versions.
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
