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
session policy, which keeps one terminal per session: it never attaches a
second terminal that mirrors a session already in use.

| Sessions on the host | SSH window | Local kitty window |
| --- | --- | --- |
| None | Create session `0` | Same |
| Exactly one, detached | Attach to it, whatever its name | Same |
| Exactly one, attached | Show the session list | Create a new independent session with the next numeric name |
| Two or more | Show the session list | Same |

Every attachment uses `attach -d`, so a terminal that attaches detaches any other
client of that session; two windows connecting at the same moment cannot end up
sharing one. `dalftui-ops-*` sessions never count (see [Ops mode](ops-mode.md#ops-mode)).

Over SSH, an attached session may belong to a live tab or to a connection that
died while its laptop slept: the server keeps counting that client until the
connection times out. tmux cannot tell them apart, so the launcher asks:

```text
tmux sessions on vm:
  1  0     attached  pts/4 from 10.8.0.2, connected 3h05m ago, last key 2h13m ago
  2  work  detached
  3  2     attached  pts/7 from 10.8.0.3, connected 20m ago, last key 12s ago
[1-3] attach   [n] new session (default)   [q] cancel
Choice [n]: 1
Session 0 has a client. Take it over (its window closes)? [y/N]
```

- **A number** picks a session; with up to nine sessions, one keystroke is enough.
  With more, type the number and press Enter.
- **A detached session** is attached at once.
- **An attached session** asks before a takeover; No (the default) returns to the
  list, so a wrong key never closes a live tab. Yes detaches that session's other
  clients, whose windows show *Another terminal took over this tmux session.*
  and close, then attaches. Clients of other sessions are not affected.
- **`n` or Enter** creates a new independent session. **`q` or Ctrl+C** cancels.
- The tty, source address (from the client's own `SSH_CONNECTION`, or `local`),
  connection time and time since its last key are information only. They never
  choose or suggest a session: tabs from one desktop share an address, and an idle
  live tab looks the same as a dead one.

There is no shell-without-tmux choice here; the SSH picker's **F5** opens one.
Without a terminal on standard input, the launcher prints an error and exits
with status 1 instead of choosing; it never takes over a session unattended.
There is no countdown for the same reason.

The launcher alone cannot enforce one client per session: `choose-tree`,
`switch-client`, a manual `tmux attach`, or an older desktop's launcher can still
attach a second client. On hosts with dalftui's tmux configuration (any
installation mode, after `./bin/reload`), tmux hooks enforce it: when a client
attaches to a session or switches into it, that session's other clients are
detached with the same *Another terminal took over this tmux session.* message.
The newcomer always wins, so a dead client that still counts as attached never
locks you out; when two clients arrive almost together, the later one wins.
Clients of other sessions are never detached. Read-only clients
(`attach -r`) are not special: they count, and they take over like any other.
Only attaching and switching take over. With `detach-on-destroy off` (or
`previous`/`next`), closing a session makes tmux move its clients into another
session; a moved client that lands in a session another terminal is using is
detached instead, with *Your tmux session closed, and the session tmux moved you
to is in use by another terminal.* `detach-on-destroy no-detached` avoids that
by moving only into a detached session.
On tmux 3.2, which does not tell the hook which client arrived, the most
recently active client keeps the session. Hosts without dalftui's configuration
keep tmux's own behaviour.

Server keepalives make the list rare. With OpenSSH's default
`ClientAliveInterval 0`, a server keeps a slept laptop's connection, tmux client
and forwarded agent socket until TCP gives up, which can take hours for an idle
pane. Meanwhile its session counts as attached, and agent requests through the
stale socket can hang. On servers you administer, consider adding to
`/etc/ssh/sshd_config` (then reload sshd):

```text
ClientAliveInterval 60
ClientAliveCountMax 5
```

sshd then drops a silent client after about five minutes, its session becomes
detached and its [agent alias](#ssh-agent-in-tmux-sessions) goes away, so `git`
fails at once instead of hanging, and the next connection reattaches without a
question. The cost is
that a sleep longer than that always ends the connection; tmux keeps the work
and only the window is lost. On desktops, `ServerAliveInterval 60` in
`~/.ssh/config` makes a dead window exit soon after waking instead of staying
frozen, although it does not help the server notice the sleep. dalftui
documents these settings but does not change SSH configuration.

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

## SSH agent in tmux sessions

A shell keeps the `SSH_AUTH_SOCK` it started with. With agent forwarding, each
SSH connection gets a new socket path, so after a reconnect, or after moving
from the laptop to another desktop, `git` in an existing pane would fail while a
new pane works.

On a Linux host where dalftui is installed and the tmux server has loaded its
configuration, each session that the SSH launcher creates gets a private, stable
*agent alias*: a symbolic link such as
`$XDG_RUNTIME_DIR/dalftui-agent/<random key>`. Every shell in the session,
including the first one, starts with `SSH_AUTH_SOCK` set to the alias, and the
alias points at the forwarded agent of the client attached now:

| Event | Alias |
| --- | --- |
| The launcher creates the session | Points at this connection's forwarded agent before the first shell starts |
| A client takes the session over, attaches or switches into it | Replaced atomically with that client's agent |
| The attached client detaches, disconnects or switches away | Removed |
| The attached client has no forwarded agent (`ssh -a`, `ForwardAgent no`) | Absent; never borrowed from another client |
| The session closes | Removed with its record |

Existing shells and background jobs follow the attached desktop from their next
agent connection; connections already open keep their agent. While the session
is detached, new agent connections through the alias fail until a client
reattaches. This is intended: a detached session has no desktop to ask.

Details:

- The key is random for each new session and is recorded in the session's
  `@dalftui_agent_alias` option, so a tmux server restart or a second server
  never reuses another session's alias.
- The directory is `$XDG_RUNTIME_DIR/dalftui-agent`, or `/tmp/dalftui-agent-<uid>`
  without a runtime directory. It must be a real directory that you own with
  mode 0700; otherwise no alias is used.
- The target is read from the attaching tmux client's own process environment,
  never from the session environment or from helper connections. The global
  `update-environment` keeps tmux's default, which sessions without an alias and
  older desktops rely on. An alias session gets its own copy without
  `SSH_AUTH_SOCK`, so attaching never puts a raw socket in its environment, and
  new panes and windows, even one created in the attach command itself, inherit
  the alias. A later change to the global list reaches alias sessions at their
  next attach, detach or switch.
- A record next to the alias (`<key>.json`) names the owner client (tty, PID,
  start time) and a generation. Updates take a lock and follow tmux's current
  state, so a late detach from a dead laptop cannot remove the alias that the
  other desktop now uses. Cleanup removes only the alias, never OpenSSH's socket.

Scope: only sessions created by the SSH launcher (the SSH picker, `dssh`, or
`bin/tmux-start.sh` run over SSH) on hosts with `python3` and `/proc`. Local
kitty sessions, ops sessions, sessions started with a plain `tmux new`, hosts
without dalftui, and servers not reloaded since an update keep tmux's usual
`SSH_AUTH_SOCK`. A window moved or linked into another session keeps the alias
of the session where its shell started. Outside tmux, a login shell keeps the
socket that SSH gave it.

To see where a session's agent requests go, run in one of its panes:

```sh
python3 ~/.config/dalftui/bin/session_owner.py status
```

```text
Session:      $0
Agent alias:  /run/user/1000/dalftui-agent/3f9c…
Alias target: /tmp/ssh-XXXXabcd/agent.4242 (socket)
Owner client: /dev/pts/4, pid 4243, from 10.8.0.2, owner for 12m, generation 3
This shell:   uses the alias
The alias routes to the attached client; it does not prove which agent or keys answer.
```

`ssh-add -l` lists the identities that the agent behind it offers.

**Migration.** After updating dalftui on a server, run `./bin/reload` there.
Sessions created by the updated launcher need nothing else. A session created
before has no alias, and its shells still hold the raw socket of the connection
that started them. In such a session, run once:

```sh
python3 ~/.config/dalftui/bin/session_owner.py enable
```

From a shell outside tmux, name the session instead, for example
`enable --session '$3'` (`tmux list-sessions -F '#{session_id} #{session_name}'`
shows the IDs). New panes then use the alias. In each existing shell of that session, run the
`export SSH_AUTH_SOCK=…` line it prints. Programs that are already running, such
as editors, keep their old socket until restarted.

**Overrides.** Nothing rewrites a running shell's environment. To use another
agent in one shell, set or unset `SSH_AUTH_SOCK` there. To follow the session
again, run `export SSH_AUTH_SOCK="$(tmux show-options -v @dalftui_agent_alias)"`.

The alias routes requests; it is not isolation. Processes of the same account,
and root, can use whichever agent is reachable, and removing the alias does not
close agent connections that are already open or revoke anything. Editor bridge
credentials stay specific to each attachment and are not affected.

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
