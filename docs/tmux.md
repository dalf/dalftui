# tmux and Alacritty reference

## Shortcuts

- **Ctrl+B, then F1:** open the keyboard shortcut guide.
- **Ctrl+B, then F2:** desktop mode: choose an SSH host and open a separate Alacritty window.
- **Ctrl+B, then F3:** open the current pane's directory in a new VS Code window, locally or over SSH.

Other shortcuts are standard tmux keys; see the [README](../README.md#shortcuts).
After Ctrl+B, release it and press the next key. For windows 1 to 9, keeping
Ctrl held also works when the terminal reports Ctrl+digit as a distinct key.
Alacritty and Windows Terminal use Ctrl+0 to reset the font size, so release
Ctrl for window 0; releasing Ctrl works everywhere.

The guide reads Alacritty imports and local overrides, and shows live tmux
bindings. The terminal font needs glyphs for the rounded Powerline caps (`` and
``) and the status circle (`⬤`). The system monospace font remains the default.

## Selecting and copying

Selection works the same way in Alacritty and Windows Terminal, locally or over
SSH, whether the pane runs a shell or a mouse-aware program:

- **Shift+drag** selects text; **Ctrl+Shift+C** copies and **Ctrl+Shift+V** pastes.
- **Split panes:** a terminal selection crosses pane borders. Press **Ctrl+B, then z**
  to zoom the pane, select, then **Ctrl+B, then z** again to restore the layout.
- **Text in history:** scroll with the mouse wheel, **Shift+Page Up** in Alacritty,
  or **Ctrl+B, then Page Up**, then Shift+drag.

On macOS, hold Fn while dragging in Terminal.app or Option in iTerm2, then
press Cmd+C; tmux copies go to the clipboard through `pbcopy`.

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

## Session policy

SSH windows use tmux when it is installed on the remote host. Otherwise they
silently open a plain login shell. No remote dalftui installation is required
for either case. Local Alacritty windows and SSH windows with tmux use the same
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
remote **Ctrl+B, then F3** integration. SSH windows override Alacritty's local
startup and apply the policy directly on the server.
Installing dalftui locally does not deploy its tmux configuration to remote hosts.
Install `--server` on each server where you want the shared configuration.
Without it, remote tmux uses the server's existing configuration and bindings. Shift+drag
selection works either way; the plain-drag reminder and OSC 52 clipboard writes
need the shared configuration.

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
These labels affect tmux's status bar; outer terminal titles retain their
existing configuration, including claude-tabstatus's separate title policy.

Color support is chosen for each attached terminal in every profile, including
over SSH. `xterm-256color` alone does not imply 24-bit color: older Terminal.app
uses that name and needs tmux's 256-color fallback. Alacritty's own terminal
name gets a scoped truecolor override, and tmux detects iTerm2 automatically.
From tmux 3.6, a client's `COLORTERM=truecolor` setting also enables truecolor.
The dalftui SSH launcher supplies a per-attachment RGB hint for Windows Terminal
and terminals declaring `COLORTERM=truecolor` or `24bit`, including Alacritty.
This keeps their colors accurate when other clients on the same server need
256 colors; remote tmux versions without the hint option use normal detection.

When upgrading from the earlier `*:Tc` override, run `./bin/reload` on each
affected host, then detach and reattach existing clients to their original
sessions (Ctrl+B, then d detaches). tmux can retain an attached client's old
color capabilities after reload; fresh clients use the updated capabilities
immediately. Detaching keeps sessions, running programs and other clients
running, so no tmux server restart is needed.

[claude-tabstatus](https://github.com/dalf/claude-tabstatus) is an optional,
separate project. Existing installations continue to supply repository/branch
labels and status through pane titles and `@cctab_window_strip`. dalftui preserves
that integration and does not change Claude hooks. Without it, shell titles and
the Git/directory-aware program labels above are displayed.
Install claude-tabstatus separately on the server too if you want its status
indicators for Claude running there.

The tab design keeps the optional claude-tabstatus integration: the active
light pill uses dark status circles, and inactive dark pills use light circles.
