# tmux and kitty reference

## Shortcuts

- **Ctrl+B, then F1:** open the keyboard shortcut guide.
- **Ctrl+B, then F2:** desktop mode: choose an SSH host and open it in a new tab of the current kitty window.
- **Ctrl+Shift+F2** (Windows Terminal, not a tmux key): choose an SSH host in a new local tab,
  even from a `dssh` tab running remote tmux.
- **Ctrl+B, then h:** macOS mode: choose an SSH host and open a Terminal.app or iTerm2 window.
- **Ctrl+B, then F3:** open the current pane's directory in a new VS Code window, locally or over SSH.
  **Ctrl+B, then v** does the same.

Other shortcuts are standard tmux keys; see the [README](../README.md#shortcuts).
After Ctrl+B, release it and press the next key. For windows 1 to 9, keeping
Ctrl held also works when the terminal reports Ctrl+digit as a distinct key.
Windows Terminal uses Ctrl+0 to reset the font size, so release
Ctrl for window 0; releasing Ctrl works everywhere.

The guide lists kitty's main keys and shows live tmux
bindings. The terminal font needs glyphs for the rounded Powerline caps (`` and
``) and the status circle (`⬤`). The system monospace font remains the default.

## Selecting and copying

In tmux shells, the same mouse gestures work locally and over SSH:

- **Click and drag** selects text in the pane. Keep the button held and drag to
  the top or bottom edge to scroll through tmux history while selecting.
  Releasing copies the text and returns to the live pane.
- **Double-click / triple-click** copies a word / line.
- **Text in history:** scroll with the mouse wheel, **Shift+Page Up**,
  or **Ctrl+B, then Page Up**, then drag to select.

Programs that use the mouse, such as htop or editors, still receive drags and
clicks. The wheel may also go to an application using the alternate screen;
**Ctrl+B, then Page Up** opens tmux history directly. tmux can only select text
it has retained; an application's own history may need its own scroll controls.

For terminal-native selection, hold **Shift** while dragging in kitty or Windows
Terminal, then use **Ctrl+Shift+C** to copy. This selects the currently displayed
text and cannot scroll through tmux history. A terminal selection crosses split
pane borders: **Ctrl+B, then z** zooms the pane; press it again to restore the
layout. In Windows Terminal, select before copying, or Ctrl+Shift+C may reach
the pane as Ctrl+C. **Ctrl+Shift+V** pastes from the desktop clipboard.

On macOS, terminal-native selection uses Fn in Terminal.app or Option in iTerm2,
then Cmd+C / Cmd+V. Local macOS tmux copies use `pbcopy`; remote copies need a
terminal with OSC 52 support, which Terminal.app does not provide.

dalftui adds no terminal copy bindings and relies on kitty and Windows
Terminal defaults. dalftui's kitty settings also copy selections automatically; Windows
Terminal's `copyOnSelect` setting is left unchanged. tmux sets `set-clipboard on`,
so programs in panes, including on remote servers, may set the desktop
clipboard with OSC 52. They cannot read the desktop clipboard, but an OSC 52
query returns tmux's most recent paste buffer: text copied in tmux history or
set by another pane. Override it in
`~/.config/tmux/local.conf`, for example with `set -s set-clipboard off`.
After updating the checkout on each host, run `./bin/reload` there. Reloading
replaces the earlier selection hints with these bindings while keeping sessions
and running programs. Personal bindings in `~/.config/tmux/local.conf` still
take precedence.

## Session policy

SSH windows use tmux when it is installed on the remote host. Otherwise they
silently open a plain login shell. No remote dalftui installation is required
for either case. Local kitty windows and SSH windows with tmux use the same
session policy:

- No sessions: create session `0`.
- One detached session: attach to it, whatever its name.
- One attached session: create a new independent session with the next numeric name.
- Multiple sessions: list their IDs, names, and client counts. Enter a session ID to
  attach, `n` or Enter for a new session, `s` for a plain login shell, or `q` to cancel.

With remote tmux, **Ctrl+B, then d** detaches and closes the SSH window (after
`dssh` typed at a PowerShell prompt, it returns to that prompt) while leaving its
session running. Connection errors stay visible
until Enter is pressed. A plain shell has no tmux shortcuts, persistence, or
remote **Ctrl+B, then F3** integration. SSH windows skip the local tmux
startup and apply the policy directly on the server.
Installing dalftui locally does not deploy its tmux configuration to remote hosts.
Install `--server` on each server where you want the shared configuration.
Without it, remote tmux uses the server's existing configuration and bindings.
Plain dragging through tmux history needs mouse mode and selection bindings on
the remote host. Clipboard copying also needs working OSC 52 support in tmux and
the desktop terminal. Installing or updating dalftui locally does not update the
remote host's configuration.

## Theme and claude-tabstatus

The required Catppuccin tmux v2.3.1 configuration files are bundled under
`vendor/catppuccin`, including their upstream MIT license. No theme download or
plugin manager is needed. The custom rounded tab design is in `config/tmux.conf`.

Shell tabs keep their prompt-provided title. Other programs show the active
pane's `repository@branch · window-name`, for example `dalftui@main · codex`.
Subdirectories use the repository's root folder name. Outside Git, the label
uses the current directory's name instead. Linked worktrees use their own root
folder and branch; a detached HEAD uses an exact tag or a short commit hash.
Explicit window names remain after `·`, and tmux's actual window names are not
changed by the label helper.

`bin/tmux_label.py` reads only repository/ref metadata, with bounded Git calls.
Tmux runs it through uv, like the dalftui keys, asynchronously; it caches its
last output and refreshes the status every five seconds, so branch changes and
program directory changes are reflected while the program is running. It does
not scan working-tree changes or run the prompt engine. Git failures fall back
to the directory name.
Override `@dalftui_program_label` or `status-interval` in
`~/.config/tmux/local.conf` to customize this behavior. To restore program-only
labels, use `set -g @dalftui_program_label '#{window_name}'`.
These labels affect tmux's status bar. The outer terminal title shows the SSH
launcher's `username@host-alias`, including for shell-only sessions and after
reattaching. Local sessions use the active pane's prompt/application title.
When claude-tabstatus takes over, it adds its status for the attached session,
then `@cctab_label`, which uses the SSH label or else tmux's short host name.
Reload preserves claude-tabstatus's title format. Personal title settings in
`~/.config/tmux/local.conf` take precedence.

Color support is chosen for each attached terminal in every profile, including
over SSH. `xterm-256color` alone does not imply 24-bit color: older Terminal.app
uses that name and needs tmux's 256-color fallback. kitty's own terminal
description, `xterm-kitty`, declares truecolor, and tmux detects iTerm2 automatically.
From tmux 3.6, a client's `COLORTERM=truecolor` setting also enables truecolor.
The dalftui SSH launcher supplies a per-attachment RGB hint for Windows Terminal
and terminals declaring `COLORTERM=truecolor` or `24bit`, including kitty.
This keeps their colors accurate when other clients on the same server need
256 colors; remote tmux versions without the hint option use normal detection.

Programs inside panes choose their colors from `TERM` and `COLORTERM`. tmux
before 3.3 gives panes `TERM=screen` (8 colors), so dalftui replaces that built-in
value with `tmux-256color`, or `screen-256color` when the host lacks that terminfo
entry. It also sets `COLORTERM=truecolor`, which tmux 3.6 and later set themselves
and which SSH does not forward. tmux converts 24-bit colors for each attached
client that cannot display them. Panes opened before `./bin/reload` keep their
old values; restart programs such as Claude Code in a new pane or window. Claude
Code stays at 256 colors inside tmux unless `CLAUDE_CODE_TMUX_TRUECOLOR=1` is set.
Plain `ssh` from a pane sends `tmux-256color` to the next host; set
`default-terminal screen-256color` in `local.conf` if older hosts lack that entry.

When upgrading from the earlier `*:Tc` override, run `./bin/reload` on each
affected host, then detach and reattach existing clients to their original
sessions (Ctrl+B, then d detaches). tmux can retain an attached client's old
color capabilities after reload; fresh clients use the updated capabilities
immediately. Detaching keeps sessions, running programs and other clients
running, so no tmux server restart is needed.

[claude-tabstatus](https://github.com/dalf/claude-tabstatus) is a separate
project that bootstrap installs, including with `--server`; its `tabstatus install`
wires the Claude hooks. It supplies repository/branch labels and status through
pane titles and `@cctab_window_strip`. Without it, shell titles and
the Git/directory-aware program labels above are displayed.

The tab design keeps the optional claude-tabstatus integration: the active
light pill uses dark status circles, and inactive dark pills use light circles.
