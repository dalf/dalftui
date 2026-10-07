# dalftui

My terminal setup. On Linux: Alacritty, tmux with rounded tabs, an Oh My Posh
prompt, an SSH host picker, and a key to open the current folder in VS Code,
also on a remote server. On Windows: the same prompt, picker and VS Code key
in PowerShell and Windows Terminal, plus a few Unix-like commands. On macOS
(Terminal.app or iTerm2, zsh): tmux, the prompt and the VS Code key, tested
only on CI so far.

## Try one thing

You do not need to install everything. Clone the repo (the examples use
`~/code/dalftui`), pick a feature below and follow its **Take it alone** step.
Each feature says what it needs, where it works, and how to turn parts off.

## Install everything

Linux desktop. Needs Python 3.11+, Alacritty 0.14+, tmux 3.2+, OpenSSH 9.4+,
Git, `less` and [Oh My Posh](https://ohmyposh.dev/docs/installation/linux):

```sh
cd ~/code/dalftui
./install --dry-run
./install
./bin/reload
```

Linux server (tmux, prompt and shortcut guide only; Python 3.11+, tmux 3.2+,
Git, `less`, Oh My Posh): `./install --tmux-only`.

Windows. Needs Python 3.11+, Windows OpenSSH, Oh My Posh
(`winget install JanDeDobbeleer.OhMyPosh`) and VS Code with Remote - SSH:

```powershell
git clone https://github.com/dalf/dalftui.git "$HOME\code\dalftui"
cd "$HOME\code\dalftui"
.\install.cmd
```

Options: `-VSCodePath` (portable VS Code), `-ProfilePath` (one profile only),
`-TerminalSettingsPath`, `-SkipTerminal`. If PowerShell then says scripts are
disabled, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

macOS (Terminal.app or iTerm2, zsh; no Alacritty). Needs Python 3.11+, tmux
3.2+ and Oh My Posh, from Homebrew: `brew install python@3.13 tmux oh-my-posh`.
Then `./install --dry-run`, `./install`, `./bin/reload`. It sets up tmux, the
zsh prompt, Hack Nerd Font and VS Code's terminal font. Tested on macOS CI only;
see [macOS](docs/install.md#macos).

With [mise](docs/development.md#repository-tasks):
`mise run install:linux -- --dry-run`, `mise run install:windows`.

Linux and macOS: existing files are backed up to `~/.local/state/dalftui/backups/`
before they are replaced. Personal overrides go in `~/.config/tmux/local.conf`
and `~/.config/alacritty/local.toml`; installs keep them. Windows: the profile,
Terminal `settings.json` and VS Code `settings.json` are copied to
`<file>.dalftui-<id>.bak` next to the original.

Update: `git pull --ff-only && ./bin/reload` on Linux and macOS. On Windows,
`git pull --ff-only`, then open a new PowerShell session.

Uninstall: `./install --uninstall` on Linux and macOS, `.\install.cmd -Uninstall` on Windows
(preview with `--dry-run` or `-DryRun`); see [Uninstall](docs/install.md#uninstall).

Details: [docs/install.md](docs/install.md).

## tmux bindings and look

What: tabs at the top as rounded pills on a black bar, Catppuccin Mocha
colours, mouse on, 100000 lines of history. Ctrl+Alt+arrow moves between
panes, Ctrl+Alt+Shift+arrow resizes them. Shift+Page Up scrolls back through
history; once scrolled, Ctrl+F searches it. Select with Shift+drag; a plain drag in a shell only shows a
hint. Programs can set the desktop clipboard (OSC 52). Ctrl+B F1 opens a
shortcut guide. The prefix stays Ctrl+B.

Files: `config/tmux.conf`, `vendor/catppuccin/` (Catppuccin tmux v2.3.1, MIT),
`bin/shortcuts.py`, `dalftui/linux/shortcuts.py`.

Needs: tmux 3.2+ (3.3+ for styled popups). Python 3.11+ and `less` for the
guide. A font with the rounded caps and `⬤`, such as Hack Nerd Font, in the
terminal you look at (for a server, your local terminal).

Works on: Linux. Windows: only inside tmux on a Linux server. macOS: installed
and loaded on macOS CI, where tmux copies go to the clipboard through `pbcopy`;
keys not tried in a real Terminal.app or iTerm2.

Take it alone: in your own `~/.tmux.conf`:

```tmux
set -g @dalftui_profile tmux-only
source-file ~/code/dalftui/config/tmux.conf
# your own overrides after this line
```

Keep the `tmux-only` line before `source-file`. Without it, Ctrl+B F2 opens the
SSH picker, which needs Alacritty.

Turn off / parts: lines after `source-file` (or in `~/.config/tmux/local.conf`)
win. For example:

```tmux
unbind -n C-M-Left            # also C-M-Right/Up/Down, C-M-S-Left/...
unbind F1                     # shortcut guide
unbind F3                     # VS Code
set -s set-clipboard off      # no OSC 52
set -g status-position bottom
bind -n MouseDrag1Pane if -F '#{||:#{pane_in_mode},#{mouse_any_flag}}' { send -M } { copy-mode -M }
```

The last line gives back the plain drag. If you later delete a `bind` line (or
stop sourcing dalftui), restart the tmux server; a reload does not remove
bindings that are no longer in the config. You cannot skip loading Catppuccin, only
override its options. The double- and triple-click change can only be undone
by rebinding those keys.

Details: [docs/tmux.md](docs/tmux.md).

## claude-tabstatus tab labels

What: with [claude-tabstatus](https://github.com/dalf/claude-tabstatus)
installed, each tab shows status circles (idle grey, question orange, working
blue, workflow purple) and `repository@branch` for a Claude pane. Without it,
a shell tab shows the pane title and other tabs the window name.

Files: `config/tmux.conf` (`@claude_window_label`, `@claude_tab_active_strip`,
`@claude_tab_inactive_strip`, the `window-status-*format` lines).

Needs: the tmux feature above, claude-tabstatus installed separately (also on
the server if Claude runs there), a font with `⬤`.

Works on: Linux. Windows: through tmux on a Linux server. macOS: untested.

Take it alone: comes with `config/tmux.conf`. To copy only the labels, take the
three `@claude_*` options and use `#{E:@claude_window_label}` and
`#{E:@claude_tab_active_strip}` / `#{E:@claude_tab_inactive_strip}` in your own
window formats. Not tested with a real claude-tabstatus.

Turn off / parts: stop claude-tabstatus. For window names everywhere:
`set -g @claude_window_label '#{window_name}'` (untested). dalftui does not
touch Claude hooks.

## Alacritty

What: black background, high-contrast colours, font size 10.5, copy on
select, and Windows-Terminal-like keys: Ctrl+Shift+T new window,
Ctrl+Page Up/Down switch, Ctrl+Shift+D/E split, Ctrl+Shift+F1/F2/F3 for guide,
SSH picker and VS Code. Each new window starts in tmux: no session: create one;
one session: attach if it is detached, else create a new one; several: ask.

Files: `config/alacritty.toml`, `bin/tmux-start.sh`,
`dalftui/linux/tmux-start.sh`, `bin/reload`.

Needs: Alacritty 0.14+, the dalftui tmux config (the keys send Ctrl+B
sequences), and the `~/.config/dalftui` link to the checkout (the startup
command uses that path).

Works on: Linux. Windows: not configured (Windows Terminal is used instead).
macOS: not used.

Take it alone: `ln -s ~/code/dalftui ~/.config/dalftui`, then in
`~/.config/alacritty/alacritty.toml`:

```toml
[general]
import = ["~/code/dalftui/config/alacritty.toml"]
```

Turn off / parts: add to `~/.config/alacritty/local.toml` (or after the
import). `[terminal]` then `shell = "bash"` skips tmux at startup; it must be
this string form, because `[terminal.shell]` args are appended to the imported
ones. At the startup prompt, `s` gives a plain shell. You cannot remove the
imported key bindings: Alacritty appends arrays. To drop them, do not import;
copy the `[colors.*]`, `[font]` and `[selection]` parts you want.

Details: [docs/tmux.md](docs/tmux.md#shortcuts),
[docs/install.md](docs/install.md#update-without-reinstalling) (reload).

## Oh My Posh prompt and window title

What: one theme for bash and PowerShell. It shows job counts, `user@host` only
over SSH, the path, venv or conda env, git branch and changes, run time over
2 s, and the exit code with a name like `130(interrupted)`. The window title is
`repo@branch` in git, else the path; over SSH the host comes first. On Windows
the title keeps the last two folders and starts with 🛡️ when admin. In tmux a
shell's title becomes the tab label.

Files: `config/oh-my-posh.omp.json`, `config/prompt.bash`,
`dalftui/windows/profile.ps1`.

Needs: Oh My Posh (tested with 31.5.0) and a Nerd Font in the terminal you look
at. In PowerShell, PSReadLine.

Works on: Linux (bash), Windows (PowerShell 5.1 and 7; not cmd or Git Bash).
macOS (zsh, `config/prompt.zsh`): loads and counts jobs on macOS CI; not seen in
a real terminal.

Take it alone: bash, in `~/.bashrc` after any other prompt setup:

```sh
[ -f ~/code/dalftui/config/prompt.bash ] && . ~/code/dalftui/config/prompt.bash
```

PowerShell, in `$PROFILE`:

```powershell
oh-my-posh init pwsh --config "$HOME\code\dalftui\config\oh-my-posh.omp.json" | Invoke-Expression
```

Remove your own `oh-my-posh init` line.

Turn off / parts: Linux: delete the `prompt.bash` line from `~/.bashrc` but
keep the `# dalftui: Oh My Posh prompt` marker line, or `./install` adds it
back. Both installers require Oh My Posh. On Windows the prompt comes with the
whole profile and has no switch of its own. The title cannot be turned off
separately; edit a copy of the theme.

## Hack Nerd Font

What: the installers install Hack Nerd Font so prompt and tab glyphs render.
On Windows it also becomes Windows Terminal's default font. On Linux,
Alacritty keeps the system monospace font and gets the glyphs by fallback.

Files: `dalftui/linux/setup.py`, `dalftui/windows/setup.ps1`,
`dalftui/windows/terminal_settings.py`.

Needs: Oh My Posh (it downloads the font), network access once. Linux:
`fc-list`.

Works on: Linux (desktop mode only), Windows. macOS: detection in
`~/Library/Fonts` tested on CI; the download is not run there.

Take it alone: `oh-my-posh font install Hack`. To name it in Alacritty, put
`normal.family = "Hack Nerd Font"` under `[font]` in `local.toml`. In Windows
Terminal's `settings.json`, under `profiles`:
`"defaults": { "font": { "face": "Hack Nerd Font" } }`.

Turn off / parts: no flag. Install the font yourself first and Linux skips the
download. On Windows, `-SkipTerminal` leaves Terminal's font alone (and skips
all Terminal and VS Code font changes). A Terminal profile with its own font
keeps it.

## dssh SSH picker

What: a full-screen list of the hosts in `~/.ssh/config` tagged
`Tag dalftui`. Type to filter, Enter connects, Esc cancels. Ctrl+O connects to
exactly what you typed (host, IP or `user@host`). F4 shows `ssh -G` details,
F5 opens a plain shell, F6 ops mode, F7 a saved check. A connection attaches
remote tmux if the server has it, else a plain shell; nothing is needed on the
server. The title becomes `user@host`. Linux: Ctrl+Shift+F2 (or Ctrl+B F2)
opens it and connects in a new Alacritty window. Windows: `dssh` in PowerShell,
Ctrl+Shift+F2 in Windows Terminal.

Files: `bin/ssh_picker.py`, `dalftui/ssh.py`, `dalftui/host_picker.py`,
`dalftui/linux/ssh_picker.py`, `dalftui/windows/` (`ssh.py`, `host_picker.py`,
`profile.ps1`, `ssh-tab.ps1`).

Needs: Python 3.11+, OpenSSH 9.4+ for `Tag`. Linux default mode: Alacritty on
PATH. Windows: `py` or `python` on PATH.

Works on: Linux, Windows. macOS: untested; `--pick` and `--connect` should
work.

Take it alone: tag hosts (Windows: `%USERPROFILE%\.ssh\config`):

```sshconfig
Host work-server
    HostName server.example.org
    User alice
    Tag dalftui
```

Then run it from the clone, nothing installed:

```sh
python3 ~/code/dalftui/bin/ssh_picker.py --pick            # pick, this terminal
python3 ~/code/dalftui/bin/ssh_picker.py --connect HOST    # direct
```

On Windows use `py -3 "$HOME\code\dalftui\bin\ssh_picker.py" --pick`. A
minimal `dssh` for `$PROFILE`:

```powershell
function dssh {
    param([string]$HostName)
    $picker = "$HOME\code\dalftui\bin\ssh_picker.py"
    if ($HostName) { py -3 $picker --connect $HostName } else { py -3 $picker --pick }
}
```

Turn off / parts: `unbind F2` in tmux; `./install --tmux-only` never binds it.
`-SkipTerminal` drops the Windows Terminal key (and the other Terminal
changes). Cannot turn off: the tag filter, the F4-F7 keys, and an extra SSH
connection that checks for the VS Code bridge, so password logins ask twice
(keys or an agent avoid it). Without `User` in your SSH config it asks for a
login.

Details: [docs/ssh-picker.md](docs/ssh-picker.md).

## Open folder in VS Code

What: Ctrl+Shift+F3 (or Ctrl+B F3 in tmux) opens the current pane's folder in
a new VS Code window. In an SSH window opened by the picker, it opens the
remote folder with Remote - SSH, through a forwarded and authenticated bridge.
On Windows it also works at a local PowerShell prompt.

Files: `config/tmux.conf` (the F3 binding), `bin/vscode.py`,
`dalftui/vscode.py`, `dalftui/linux/tmux_editor.py`,
`dalftui/linux/remote_bootstrap.py`, `bridge_protocol.py`,
`dalftui/windows/profile.ps1`.

Needs: VS Code with `code` on PATH (Windows: the installer records
`Code.exe`). Python 3.11+. For remote: the Remote - SSH extension; on the
server tmux, python3 and a current dalftui at `~/.config/dalftui`
(`./install --tmux-only`); sshd allowing `AllowStreamLocalForwarding` (Linux)
or remote TCP forwarding with `GatewayPorts` `no` or `clientspecified`
(Windows). Connect through the picker, `dssh` or `--connect`; a plain `ssh`
has no bridge. Desktop and server need compatible versions, or F3 is skipped.

Works on: Linux (local and remote), Windows (local PowerShell prompt and remote
tmux). macOS: local VS Code only, which needs VS Code's `code` command on PATH;
launch tested with a fake `code` on CI. Remote from a Mac is untested.
Servers: Linux only.

Take it alone: in your `tmux.conf`:

```tmux
bind-key F3 run-shell -b 'python3 ~/code/dalftui/bin/vscode.py --pane #{pane_id} --client #{client_pid} --client-tty #{q:client_tty}'
```

For remote, do the same on the server and link the clone there:
`ln -s ~/code/dalftui ~/.config/dalftui`. Without dalftui at all:
`code --new-window --folder-uri "vscode-remote://ssh-remote+HOST/path"`.

Turn off / parts: `unbind F3` in tmux. No dalftui on the server means no
bridge. `-SkipTerminal` drops the Windows Terminal key. Cannot turn off: the
bridge check on each picker connection (see the double password prompt above).

Details: [docs/vscode-bridge.md](docs/vscode-bridge.md).

## PowerShell Emacs editing and Ctrl+B prefix

What: bash-like (Emacs) line editing, Ctrl+Left/Right by word, history
suggestions where PSReadLine supports them. Ctrl+B is a prefix like in tmux:
Ctrl+B Ctrl+B moves back one character, Ctrl+B F3 opens VS Code.

Files: `dalftui/windows/profile.ps1`, `bin/profile.ps1`.

Needs: PowerShell 5.1 or 7. Suggestions need PSReadLine 2.1+ (5.1 ships 2.0).

Works on: Windows. pwsh on Linux works by hand. macOS: untested.

Take it alone: in `$PROFILE`, before any `oh-my-posh init` line (changing the
edit mode drops existing key handlers):

```powershell
if ((Get-PSReadLineOption).EditMode -ne 'Emacs') { Set-PSReadLineOption -EditMode Emacs }
Set-PSReadLineKeyHandler -Chord 'Ctrl+LeftArrow' -Function BackwardWord
Set-PSReadLineKeyHandler -Chord 'Ctrl+RightArrow' -Function ForwardWord
Set-PSReadLineOption -HistorySearchCursorMovesToEnd
try { Set-PSReadLineOption -PredictionSource History -ErrorAction Stop } catch { }
Set-PSReadLineKeyHandler -Chord 'Ctrl+b,Ctrl+b' -Function BackwardChar
```

Turn off / parts: the installed profile is all or nothing. After its block in
`$PROFILE`, to get plain Ctrl+B back:

```powershell
Remove-PSReadLineKeyHandler -Chord 'Ctrl+b,Ctrl+b','Ctrl+b,F3'
Set-PSReadLineKeyHandler -Chord 'Ctrl+b' -Function BackwardChar
```

That also breaks local Ctrl+Shift+F3 in Windows Terminal, which sends Ctrl+B F3.
Switching back to `-EditMode Windows` drops every handler, including Oh My
Posh's.

## PowerShell Unix-like commands

What: `touch`, `du` (MB only, flags ignored), `df` and `wc`. `du`, `df` and
`wc` are skipped when a real program has that name on PATH. If installed,
`lsd`, `wget2`, `btop`, `gsudo` and `bat` replace `ls`, `wget`, `htop`, `sudo`
and `cat`; setup does not install them.

Files: `dalftui/windows/profile.ps1` (from `# Unix-like commands` to
`# Bash-like line editing`).

Needs: PowerShell 5.1 or 7.

Works on: Windows. macOS: untested.

Take it alone: copy that block of `profile.ps1` into `$PROFILE`; it does not
need the checkout. Or load the whole profile:
`. "$HOME\code\dalftui\bin\profile.ps1"`.

Turn off / parts: after the profile block, e.g. `Remove-Item Function:\wc` or
`Set-Alias ls Get-ChildItem -Option AllScope -Scope Global`.

## Windows Terminal PowerShell 7 profiles

What: when PowerShell 7 is installed, setup turns on ClearType for Terminal's
PowerShell 7 profile and adds a **Windows PowerShell 7 (Admin)** profile that
runs it elevated. It also adds the Ctrl+Shift+F2/F3 actions and the default
font. `settings.json` is backed up; comments are kept.

Files: `dalftui/windows/terminal_settings.py`, `dalftui/windows/setup.ps1`.

Needs: Windows Terminal 1.13+, opened once. PowerShell 7 on PATH at setup.

Works on: Windows only.

Take it alone: in Terminal's `settings.json`, add
`"antialiasingMode": "cleartype"` to the PowerShell 7 profile, and add:

```json
{"guid": "{267e52e6-0ec9-495c-a8b0-e4437770bc55}", "name": "Windows PowerShell 7 (Admin)", "commandline": "\"C:\\Program Files\\PowerShell\\7\\pwsh.exe\"", "elevate": true, "startingDirectory": "%USERPROFILE%", "icon": "ms-appx:///ProfileIcons/pwsh.png", "antialiasingMode": "cleartype"}
```

Turn off / parts: `-SkipTerminal` skips all Terminal changes. To keep the rest,
set `"hidden": true` on the Admin profile; deleting it does not stick, setup
adds it back. Your own `antialiasingMode` is kept.

## VS Code terminal font

What: sets VS Code's terminal to Hack Nerd Font, size 12. The rest of
`settings.json` is kept.

Files: `dalftui/linux/setup.py`, `dalftui/windows/terminal_settings.py`,
`dalftui/windows/setup.ps1`.

Needs: VS Code, Hack Nerd Font.

Works on: Linux (desktop mode), Windows. macOS: settings written on CI under
`~/Library/Application Support/Code/User/`; not checked in VS Code.

Take it alone: in VS Code's user `settings.json`:

```json
"terminal.integrated.fontFamily": "Hack Nerd Font",
"terminal.integrated.fontSize": 12
```

Turn off / parts: Linux desktop has no flag; every `./install` resets these two
keys. Windows: only `-SkipTerminal`, which skips the Terminal changes too.

## Ops mode and system checks

What: F6 in the picker (or `--ops`) opens a new remote tmux session with htop,
a live journal, and a shell that starts with a short system overview. F7 (or
`--check NAME`) runs a saved check, then gives a shell. Built in: `system`
(detailed overview) and `packages` (APT, from cached lists). Nothing uses sudo
or changes the server.

Files: `dalftui/linux/ops.py`, `dalftui/linux/system-status.sh`,
`dalftui/linux/package-status.sh`, `~/.ssh/dalftui-checks.json` (your checks).

Needs: on the server nothing from dalftui; `sh`, GNU `timeout`, tmux for the
layout, `journalctl`, `apt-get` for `packages`.

Works on: Linux and Windows clients; macOS client untested. Servers: Debian and
Ubuntu; other systemd Linux mostly works except `packages`.

Take it alone:

```sh
python3 ~/code/dalftui/bin/ssh_picker.py --connect HOST --ops
python3 ~/code/dalftui/bin/ssh_picker.py --connect HOST --check system
ssh HOST 'status_view=compact timeout --kill-after=5s 10s sh -s' < ~/code/dalftui/dalftui/linux/system-status.sh
```

Your own checks in `~/.ssh/dalftui-checks.json`:

```json
{"checks": [{"name": "disk-space", "command": "df -h; df -i", "timeout": 10, "hosts": ["web-*"]}]}
```

Turn off / parts: nothing runs unless you press F6/F7. The two built-in checks
always appear. Detaching leaves the ops session running.

Details: [docs/ops-mode.md](docs/ops-mode.md).

## Reference

- [docs/install.md](docs/install.md): installed paths, server mode, reload,
  overrides, backups, Windows setup.
- [docs/tmux.md](docs/tmux.md): shortcuts, selecting and copying, session
  policy, theme.
- [docs/ssh-picker.md](docs/ssh-picker.md): tags, keys, cache, login, `dssh`.
- [docs/ops-mode.md](docs/ops-mode.md): saved checks, ops layout, reports.
- [docs/vscode-bridge.md](docs/vscode-bridge.md): bridge security, TCP bridge,
  version compatibility, changing the bridge.
- [docs/development.md](docs/development.md): layout, conventions, mise tasks,
  [verification](docs/development.md#verification).
- [docs/manual-configuration.md](docs/manual-configuration.md): settings dalftui
  does not apply.
