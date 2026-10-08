# Ops mode and checks reference

## Saved checks

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

## Ops mode

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

## Direct commands

The same actions are available directly:

```sh
python3 bin/ssh_picker.py --connect sibils-api --plain
python3 bin/ssh_picker.py --connect sibils-api --check packages
python3 bin/ssh_picker.py --connect sibils-api --ops
```

On Windows, replace `python3` with `uv run --no-project --python ">=3.11"`. On Linux the desktop picker
opens the selected connection action in a new Alacritty window; `--pick` and
Windows use the current terminal. Plain mode skips dalftui's tmux policy; your
own shell startup files still run. Editor integration follows the same installed
remote compatibility checks as a normal connection.

The system overview also runs over plain SSH, with nothing installed on the
server (`status_view=compact` gives the short form shown in ops mode):

```sh
ssh HOST 'status_view=compact timeout --kill-after=5s 10s sh -s' < dalftui/linux/system-status.sh
```
