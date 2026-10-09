# dalftui: overview, installation, and updates

dalftui is a personal terminal environment stored in Git: configuration files
plus Python, shell, and PowerShell programs that make existing tools work
together. Its purpose is to give local and remote terminals consistent
shortcuts, appearance, SSH access, and VS Code integration.

## What it does

| | Linux desktop | Linux server | Windows 10/11 | macOS |
| --- | --- | --- | --- | --- |
| **Set up with** | `./bootstrap` | `./bootstrap --server` | `.\bootstrap.cmd` | `./bootstrap` |
| **Terminal window**: text, keyboard, clipboard | Alacritty | the terminal you connect from | Windows Terminal (installed separately) | Terminal.app or iTerm2 |
| **tmux**: tabs, splits, sessions that survive detaching | yes | yes | no; tmux runs on the server over SSH | yes |
| **Shell with Oh My Posh prompt**: directory, Git state, durations, failures | bash | bash | PowerShell | zsh |
| **Hack Nerd Font** | yes | no; your local terminal draws the glyphs | yes | yes; select it in Terminal.app or iTerm2 |
| **SSH host picker** | F2, opens an Alacritty window | no | F2 or `dssh` | Ctrl+B h, opens a Terminal.app or iTerm2 window |
| **VS Code (F3)** | local and remote folders | server end of the bridge | local and remote folders | local folders only |

The usual Linux arrangement is **Alacritty → tmux → bash**. A tmux *session*
contains *windows*, displayed like tabs; each window contains one or more
*panes*, the splits. Windows uses local PowerShell without local tmux; tmux
runs on the Linux server when connecting remotely.

The intended everyday workflow on a configured Linux desktop is (keys in
[Shortcuts](#shortcuts)):

1. Open Alacritty. It creates or attaches to a tmux session.
2. Work in tmux tabs and split panes.
3. Choose an SSH host. The connection opens in a separate Alacritty window,
   using remote tmux when available and a login shell otherwise.
4. Open the active pane's folder in VS Code. For a remote pane with editor
   integration available, the request travels back to the desktop and opens
   that folder through VS Code Remote - SSH.

### Shortcuts

`Ctrl+B` `c` means press `Ctrl+B`, release, then `c`.

All shortcuts are tmux keys: they work in any terminal, including over SSH.
`F1`–`F3`, macOS `h`, `Shift+PgUp` and `Ctrl+F` need dalftui's tmux config.

| Action | Keys | Notes |
| --- | --- | --- |
| Shortcut guide | `Ctrl+B` `F1` | |
| Pick SSH host | `Ctrl+B` `F2` | Linux desktop profile only; opens a separate Alacritty window. On Windows, works at the PowerShell prompt (not in dssh tabs), or run `dssh`. On macOS, `Ctrl+B` `h` opens a Terminal.app or iTerm2 window; iTerm2 asks once to confirm and may open a tab |
| Open folder in VS Code | `Ctrl+B` `F3` | Also at the Windows PowerShell prompt. Remote needs dalftui on the server and a picker or `dssh` connection; macOS opens local folders only |
| New tab | `Ctrl+B` `c` | |
| Previous / next tab | `Ctrl+B` `p` / `n` | |
| Rename tab | `Ctrl+B` `,` | |
| Close tab | `Ctrl+B` `&` | Asks for confirmation |
| Split side by side | `Ctrl+B` `%` | |
| Split top / bottom | `Ctrl+B` `"` | |
| Move to pane | `Ctrl+B` arrow | |
| Resize pane | `Ctrl+B` `Ctrl+arrow` | On macOS, Mission Control and Spaces take the `Ctrl+arrow` keys |
| Zoom pane / restore | `Ctrl+B` `z` | |
| Close pane | `Ctrl+B` `x` | Asks for confirmation |
| Scrollback | `Ctrl+B` `PgUp` or `Shift+PgUp` | `Esc` leaves |
| Search history | `Ctrl+F`, text, `Enter` while in scrollback | |
| Detach | `Ctrl+B` `d` | The session keeps running. Closes the SSH window or tab; after `dssh` typed at a prompt, returns to that prompt |
| tmux key list | `Ctrl+B` `?` | |

In Windows Terminal, tmux keys apply in `dssh` tabs, where tmux runs on the
server. Apple keyboards need Fn for F-keys.

SSH picker keys:

| Key | Action |
| --- | --- |
| Type | Filter hosts |
| Arrows, `Home` / `End`, `PgUp` / `PgDn` | Select |
| `Enter` | Connect |
| `Ctrl+O` | Connect to exactly what was typed: hostname, IP or `user@host` |
| `Ctrl+U` | Clear the filter |
| `F4` | Connection details (`ssh -G`) |
| `F5` | Login shell without tmux |
| `F6` | Ops mode: process monitor, journal and shell |
| `F7` | Choose a saved check, then a shell |
| `Esc` | Cancel, or go back from `F4` / `F7` |

PowerShell prompt keys (Windows):

| Key | Action |
| --- | --- |
| `Ctrl+Left` / `Ctrl+Right` | Move by word |
| `Ctrl+B` `Ctrl+B` | Move back one character |
| `Ctrl+B` `F2` | Choose an SSH host with `dssh`, keeping the typed line |
| `Ctrl+B` `F3` | Open the folder in VS Code, keeping the typed line |
| Other keys | Emacs editing, as in bash |

Select, copy, paste:

- **Alacritty:** `Shift`+drag selects and copies; `Ctrl+Shift+C` / `Ctrl+Shift+V`.
  `Shift+Insert` or `Shift`+middle click pastes the primary selection.
- **Windows Terminal:** `Shift`+drag, then `Ctrl+Shift+C` (select first, or it
  may reach the pane as `Ctrl+C`); `Ctrl+Shift+V` pastes.
- **macOS:** `Fn`+drag (Terminal.app) or `Option`+drag (iTerm2), then `Cmd+C` / `Cmd+V`.
- **tmux:** a plain drag in a shell only shows a hint; mouse programs such as
  htop still receive it. To select inside one split pane, zoom it first with `Ctrl+B` `z`.

The setup also provides rounded tmux tabs, Git-aware titles, scrollback
search, and optional status circles from the separately installed
claude-tabstatus project. Ops mode and checks: [docs/ops-mode.md](docs/ops-mode.md).

The Oh My Posh prompt is shared by bash, zsh and PowerShell. It shows
`user@host` only over SSH, the path, the Python environment, Git branch and
changes, run time over 2 s, and failed exit codes. The window title is
`repo@branch` in Git, otherwise the path; on Windows it starts with 🛡️ when
elevated. Git conflicts appear as a red `!N` count of unresolved files, separately
from the `~N` modified count. The prompt also activates mise when it is installed.

On Windows, the PowerShell profile also adds a few Unix-like commands and the
`dssh` command (open the SSH picker, or `dssh HOST` to connect directly), and setup
adds a **Windows PowerShell 7 (Admin)** Windows Terminal profile. Setup also
sets VS Code's terminal font on Linux, Windows and macOS. See
[Windows](docs/install.md#windows).

## Built on standard tools

The building blocks are conventional: Git-managed terminal settings, a
customized prompt, tmux sessions, OpenSSH configuration, and VS Code Remote -
SSH. SSH aliases, users, ports, keys, and jump hosts remain in the user's SSH
configuration. The repository's installer does not populate that configuration.

The implementation uses shared logic with operating-system adapters, unit and
integration tests, and GitHub Actions.

## What works differently

- **Opening a remote folder in VS Code goes through dalftui's own bridge.** A
  remote pane sends an authenticated request through SSH forwarding to a
  temporary desktop listener. The desktop launches VS Code with a fixed SSH destination. Linux and
  macOS desktops use Unix sockets by default; Windows desktops use TCP.
  Credentials belong to the connection, so two desktops attached to the same
  tmux session can open folders on their respective desktops. The bridge has a
  versioned protocol, cleanup logic, timeouts, and frozen historical
  compatibility tests.
- **SSH performs an extra setup connection.** Before the interactive
  connection, dalftui checks remote editor compatibility and prepares
  credentials when supported. Password authentication can therefore ask twice.
  Ordinary SSH/tmux access works without dalftui installed remotely; the
  integrated remote editor shortcut requires a compatible remote installation.
- **The checkout stays part of the running setup.** Python launchers run
  directly from it without a pip installation. Installed links and configuration
  loaders point back to the checkout. Many shortcuts use `uv run --no-project`
  to run a suitable Python. Keep the checkout at a stable path.
- **Mouse selection is opinionated.** A plain drag in a shell displays a hint
  (over SSH, only with dalftui on the server); Shift+drag selects text on Linux
  and Windows.
- **Startup avoids automatically sharing an occupied session.** With no tmux
  session, it creates one. With one detached session, it reattaches. With one
  attached session, it creates another. With several, it asks which to use.

## Installed software

Bootstrap installs dalftui's requirements plus the author's personal tools.
Review the package list for your platform:

| Platform | Package list | Installed with |
| --- | --- | --- |
| Fedora | [packages/fedora.txt](packages/fedora.txt) | dnf |
| Debian and Ubuntu | [packages/debian.txt](packages/debian.txt) | apt-get |
| Windows | [packages/windows.txt](packages/windows.txt) | Scoop |
| macOS | [packages/Brewfile](packages/Brewfile) | Homebrew (`brew bundle`) |

Bootstrap and installation also handle the following:

**Linux (Fedora, Debian, Ubuntu)**

- **Oh My Posh, mise, uv:** official installers, then each tool's own updates.
- **Hack Nerd Font:** Oh My Posh, desktop only.
- **GitHub CLI repository:** added on every machine, including `--server`.
- **VS Code and DVC repositories:** added for desktop packages; DVC is x86-64 only.

**Windows**

- **Python:** uv downloads it when needed.
- **OpenSSH:** Windows capability if missing; ssh-agent service configured.
- **VC++ runtime:** Scoop download; elevated installer when needed.
- **Hack Nerd Font:** Oh My Posh, if missing.

Install [Windows Terminal separately](#windows-10-or-11), then open it once.

**macOS**

- **Python:** uv downloads it when needed.
- **Hack Nerd Font:** Homebrew cask; Oh My Posh fallback if missing.

Install Homebrew and uv before running bootstrap.

## Installation and update strategy

**Use bootstrap for a full setup, and rerun it for full updates.** A successful
bootstrap run installs or upgrades the [software listed above](#installed-software)
and applies dalftui's configuration. You do not need to run the installer
separately afterward.

Remote folder opening also requires VS Code's Remote - SSH extension on the
desktop, dalftui installed on the Linux server, a connection made through the
picker or `dssh` (plain `ssh` has no bridge), and an sshd allowing Unix-socket
forwarding.
Add your SSH hosts with `Tag dalftui` ([example](#personal-configuration-and-backups)).

Bootstrap first runs `git pull --ff-only` when the checkout is clean. Check its
final summary: a failed step does not stop later steps, and it exits nonzero
when failures remain.

To install without bootstrap, when the tools are already present, or for the
Windows installer options (`-VSCodePath`, `-ProfilePath`, `-TerminalSettingsPath`,
`-SkipTerminal`), see the [installation reference](docs/install.md).

### Linux desktop: Fedora or Debian 13

The desktop requirements include Alacritty 0.14+, tmux 3.2+, and OpenSSH 9.4+
for the tagged host picker. The documented bootstrap coverage includes Fedora
44 and Debian 13. Debian 12 and Ubuntu 24.04 need the server path below
because their packaged desktop tools do not meet all requirements. Ubuntu
22.04 is refused because its Python is 3.10.

Start with Python 3.11+, Git, and sudo available. On Fedora, install those
prerequisites with:

```sh
sudo dnf install -y python3 git
```

On Debian 13:

```sh
sudo apt-get update
sudo apt-get install -y python3 git
```

Debian installed with a root password gives your user no sudo. Fix that first,
then log out and back in:

```sh
su -c "apt-get install -y sudo && usermod -aG sudo $USER"
```

Clone once if the checkout does not already exist:

```sh
git clone https://github.com/dalf/dalftui.git ~/code/dalftui
```

Then preview and run bootstrap as your normal user; it asks for sudo when needed:

```sh
cd ~/code/dalftui
./bootstrap --dry-run
./bootstrap
```

Bootstrap adds GitHub CLI's package repository, then installs or upgrades the listed
packages, Oh My Posh, mise, and uv. Desktop mode also adds Microsoft's VS Code
repository and, on x86-64, DVC's. Installation
then configures Alacritty, tmux, the prompt, and installs Hack Nerd Font. Open a new
Alacritty window afterward.

### Linux server setup

Use this on a Linux server, or when you want tmux and the prompt without the
Alacritty desktop setup. Python 3.11+, Git, and sudo must exist first. On
Debian or Ubuntu:

```sh
sudo apt-get update
sudo apt-get install -y python3 git
```

On Fedora, use `sudo dnf install -y python3 git` instead. Clone once if needed,
then run:

```sh
git clone https://github.com/dalf/dalftui.git ~/code/dalftui
cd ~/code/dalftui
./bootstrap --server --dry-run
./bootstrap --server
```

On an existing checkout, skip the clone. This still adds GitHub CLI's repository
but skips the `[desktop]` package section and the VS Code and DVC repositories, configures tmux and the bash prompt,
leaves Alacritty alone, and installs no font; the terminal you connect from
needs Hack Nerd Font for the prompt's glyphs. `./install` remembers the server profile; `./bootstrap`
does not, so keep passing `--server`.

Remote tmux startup itself does not require a dalftui installation. Install on
the server when you want its tmux theme, shortcuts, prompt, and the remote half
of the VS Code bridge.

### Windows 10 or 11

Use a normal, non-elevated Windows PowerShell session. Install Scoop, Git, and
uv first if they are missing:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
irm get.scoop.sh | iex
scoop install git uv
```

**Windows Terminal is not installed by bootstrap.** Windows 11 22H2 and later
include it. If it is missing, install it with WinGet:

```powershell
winget install --id Microsoft.WindowsTerminal --exact
```

Without WinGet, install it from the [Microsoft Store](https://aka.ms/terminal).

Open Windows Terminal once before running bootstrap so setup can find its
settings. If bootstrap already ran, rerun `.\install.cmd` from the checkout
after opening Terminal.

The SSH picker needs
OpenSSH 9.4+ for `Tag dalftui`; providing a Windows OpenSSH client alone does
not guarantee that version. Add the Remote - SSH extension to VS Code for
remote folder opening.

Clone once, then preview and run bootstrap:

```powershell
git clone https://github.com/dalf/dalftui.git "$HOME\code\dalftui"
& "$HOME\code\dalftui\bootstrap.cmd" --dry-run
& "$HOME\code\dalftui\bootstrap.cmd"
```

Skip the clone on an existing checkout. uv supplies Python when needed.
Bootstrap installs or upgrades the listed Scoop apps, sets up Windows OpenSSH
and its agent, sets Git's global `core.sshCommand` to Windows `ssh.exe` when
unset, and runs `install.cmd` to configure PowerShell and Terminal
integration. Administrator steps (VC++ runtime, missing OpenSSH client,
ssh-agent service) share one gsudo UAC prompt; without a desktop session it
lists them instead. Bootstrap itself must remain
non-elevated.

Open a new PowerShell session afterward.

Scoop cannot update an app that is running. If bootstrap reports PowerShell 7
as in use, close it and run `scoop update pwsh` from Windows PowerShell.

### macOS: Terminal.app or iTerm2 with zsh

Homebrew and uv must exist before bootstrap. On a new Apple Silicon Mac:

```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
eval "$(/opt/homebrew/bin/brew shellenv)"
brew install uv
git clone https://github.com/dalf/dalftui.git ~/code/dalftui
cd ~/code/dalftui
./bootstrap --dry-run
./bootstrap
```

Skip the prerequisite setup and clone when already present. Follow Homebrew's
instructions to add its shell environment to `~/.zprofile` for future shells.
The `/opt/homebrew` example is for Apple Silicon; the code also recognizes
Intel Homebrew at `/usr/local`, but that path is documented as untested.

Bootstrap runs `brew update` and `brew bundle` for `packages/Brewfile`, then
installation and reload. It configures tmux and the zsh prompt, installs Hack
Nerd Font, and sets VS Code's terminal font. Select Hack Nerd Font yourself in
Terminal.app or iTerm2. If Apple's Python is too old, `bootstrap`, `install`,
and `bin/reload` rerun themselves through uv; the other launchers always use
uv. Run bootstrap as your normal user; `--server` is
refused by the macOS bootstrap.

macOS support has been exercised on CI; interactive keys and selection are
documented as untested in real terminals. Local VS Code opening uses `code`
(CI-tested only with a stand-in). Remote editor forwarding from a Mac desktop is
untested, and macOS is not a supported server target for the bridge.

## Applying repository changes without upgrading tools

For a lighter update that only pulls repository changes, use the following.
This is useful when the required tools are already installed and current.

On Linux, including a server, or macOS:

```sh
cd ~/code/dalftui
git pull --ff-only
./install
```

`./install` changes nothing when nothing changed, then reloads running tmux, and
Alacritty in desktop mode. Reload preserves running
pane programs. New shell sessions load prompt changes; startup settings apply
to new terminal windows. Removing a tmux binding from a file does not remove
an already loaded binding automatically.

On Windows:

```powershell
Set-Location "$HOME\code\dalftui"
git pull --ff-only
```

Then open a new PowerShell session, or reload the current profile with
`. $PROFILE`. Reconnect SSH sessions to use new bridge and connection code.

If an update changes installed launcher paths or loaders, or you move the
checkout, rerun the installer: `./install` on Linux/macOS,
or `.\install.cmd` on Windows. A full bootstrap run already includes these
steps, with a new PowerShell session still needed on Windows. For remote editor
integration, keep desktop and server installations compatible and reconnect
after updates; Git revisions do not have to be identical.

## Uninstall

Uninstall removes what the installer created and backs up every file it
changes. Fonts, tools, backups and the checkout are kept. Preview first.

On Linux or macOS:

```sh
cd ~/code/dalftui
./install --uninstall --dry-run
./install --uninstall
```

On Windows:

```powershell
Set-Location "$HOME\code\dalftui"
.\install.cmd -Uninstall -DryRun
.\install.cmd -Uninstall
```

Details: [Uninstall](docs/install.md#uninstall).

## Personal configuration and backups

Keep Linux personal overrides outside the checkout:

```text
~/.config/alacritty/local.toml
~/.config/tmux/local.conf
```

Server and macOS profiles use the tmux override file. Run `./bin/reload` after
editing these files. On Windows, keep personal settings in your PowerShell
profile, outside dalftui's block. Linux and macOS installers back up replaced
configuration under `~/.local/state/dalftui/backups/`; Windows uses adjacent
`.dalftui-<id>.bak` files.

For the SSH picker, add hosts to your own SSH configuration, for example:

```sshconfig
Host work-server
    HostName server.example.org
    User alice
    Tag dalftui
```

Use `~/.ssh/config` on Linux or macOS, or `$HOME\.ssh\config` on Windows.
`Tag` requires OpenSSH 9.4+.
SSH keys and credentials remain outside the repository.

## Repository map and references

| Location | Responsibility |
| --- | --- |
| `config/` | Appearance, keybindings, and prompt theme |
| [packages/](packages/) | Platform package lists used by bootstrap |
| `bin/` | Public command launchers |
| `dalftui/ssh.py` | Shared SSH and connection orchestration |
| `dalftui/host_picker.py` | Shared picker layout, filtering, and navigation |
| `dalftui/vscode.py` | Editor launching and bridge lifecycle |
| `dalftui/linux/`, `dalftui/windows/` | Integration for the target environment |
| `bridge_protocol.py` | Standalone editor bridge contract and version rules |
| `tests/`, `mise.toml` | Verification and task definitions |

- [Installation reference](docs/install.md)
- [tmux and shortcuts](docs/tmux.md)
- [SSH picker](docs/ssh-picker.md)
- [Ops mode and checks](docs/ops-mode.md)
- [VS Code bridge](docs/vscode-bridge.md)
- [Manual configuration](docs/manual-configuration.md)
- [Development guide](docs/development.md)

MIT licensed; see [LICENSE](LICENSE). Vendored code keeps its own license.
