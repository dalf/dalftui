# SSH picker reference

## Hosts, tags and actions

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
connect. **Esc** cancels. On macOS, **Ctrl+B, then h** opens the picker and Enter
opens a Terminal.app window, or iTerm2 from an iTerm2 client; iTerm2 asks once to
confirm running the file and may open a tab. OpenSSH resolves tags, so wildcard, `Match`, and included
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

Remote tmux and the session policy are described in [tmux.md](tmux.md#session-policy).

## Grid, filtering and cache

The picker fills the available terminal and adds columns when needed to fit the
hosts. It recalculates the layout on resize and after filtering, keeping hostnames
readable. Up/down move through hosts; left/right move between columns. If all
hosts still cannot fit, use **Page Up/Page Down**; the footer shows the visible
range. **Home/End** select the first/last host and **Ctrl+U** clears the filter.
Filtering is case-insensitive and accepts abbreviated hostnames and multiple
search terms while preserving alphabetical order (ignoring case). Hosts are sorted
down each column, then continue in the next column. The Linux tmux popup uses
the full client size; run `./install` after updating to apply its new dimensions.

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

## Login and window title

A configured `User`, including one supplied through a wildcard or included
configuration, is used automatically. Otherwise the new window asks for the
login. A destination such as `user@host` already provides its username.
On Linux, macOS and Windows, the launcher then sets the window or tab title to
`username@host-alias`, even when remote tmux supplies no title. Remote applications
can still update it. Linux SSH windows enable Alacritty's dynamic titles for this
window only; redirected command output contains no title escape sequences.

## Windows: `dssh`

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
dalftui bridge installed, **Ctrl+B, then F3** opens the active pane's remote folder
in Windows VS Code.

Without PowerShell setup, including from Command Prompt, you can run the
launcher directly:

```powershell
uv run --no-project --python ">=3.11" "$HOME\code\dalftui\bin\ssh_picker.py" --pick
uv run --no-project --python ">=3.11" "$HOME\code\dalftui\bin\ssh_picker.py" --connect my-vm
```

In Command Prompt, replace `$HOME` with `%USERPROFILE%`.
