"""Portable generators for Debian/Ubuntu checks and a separate remote ops session."""
from pathlib import Path
import shlex


LOGIN_SHELL = '"${SHELL:-/bin/sh}" -l\nexit $?\n'


def package_status_script():
    return Path(__file__).resolve().with_name('package-status.sh').read_text(encoding='utf-8')


def system_status_script(*, compact=False):
    view = 'compact' if compact else 'detailed'
    return (f'status_view={view}\n'
            + Path(__file__).resolve().with_name('system-status.sh').read_text(encoding='utf-8'))


def check_script(name, command, timeout, *, overview=False):
    """Bound the command and its process group, then leave a usable login shell."""
    if overview:
        heading = '''overview_error() {
    if [ -t 1 ] && [ "${TERM:-dumb}" != dumb ]; then
        printf '\\033[31mERR\\033[39m  %s\\n' "$1"
    else
        printf 'ERR  %s\\n' "$1"
    fi
}
'''
        result = '''        0) : ;;
        124|137) overview_error 'System overview timed out; some sections may be missing.' ;;
        1) overview_error 'Some status information is unavailable.' ;;
        *) overview_error "System overview could not finish (exit $check_status)." ;;
'''
        missing = "overview_error 'System overview unavailable: timeout is missing.'\n"
    else:
        heading = f'printf "%s\\n" {shlex.quote(f"Check: {name} (limit {timeout}s)")}\n'
        result = ('        124|137) printf "%s\\n" "Check timed out." ;;\n'
                  '        *) printf "Check exit status: %s\\n" "$check_status" ;;\n')
        missing = 'printf "%s\\n" "timeout is unavailable; check was not run."\n'
    return (heading +
            'if command -v timeout >/dev/null 2>&1; then\n'
            f'    timeout --kill-after=5s {timeout}s sh -c {shlex.quote(command)} </dev/null\n'
            '    check_status=$?\n'
            '    case $check_status in\n'
            + result +
            '    esac\n'
            'else\n'
            + missing +
            'fi\n' + LOGIN_SHELL)


def session_script():
    """Create only new panes; failure may clean up only the session we created."""
    monitor = """if command -v htop >/dev/null 2>&1; then
    htop
elif command -v top >/dev/null 2>&1; then
    printf '%s\n' 'htop is unavailable; using top.'
    top
else
    printf '%s\n' 'Neither htop nor top is available.'
fi
""" + LOGIN_SHELL
    journal = """printf '%s\n' 'Live journal for this boot (last 50 entries, then follow).'
printf '%s\n' 'Only permitted entries are shown; no automatic sudo. Ctrl+C stops following.'
if command -v journalctl >/dev/null 2>&1; then
    journalctl --boot --lines=50 --follow --no-pager
    printf 'Journal ended with status %s.\n' "$?"
else
    printf '%s\n' 'journalctl is unavailable.'
fi
""" + LOGIN_SHELL
    shell = check_script('system overview', system_status_script(compact=True), 10, overview=True)
    commands = ''.join(f'{name}={shlex.quote(script)}\n'
                       for name, script in (('ops_monitor_command', monitor),
                                            ('ops_journal_command', journal),
                                            ('ops_shell_command', shell)))
    return commands + """
ops_name=dalftui-ops-$$
ops_cols=120
ops_rows=36
ops_size=$(stty size 2>/dev/null) || ops_size=
if [ -n "$ops_size" ]; then
    ops_rows=${ops_size% *}
    ops_cols=${ops_size#* }
fi
if [ "$ops_cols" -lt 40 ] || [ "$ops_rows" -lt 12 ]; then
    printf '%s\n' 'Ops mode needs at least 40 columns and 12 rows; opening a shell.'
    "${SHELL:-/bin/sh}" -l
    exit $?
fi
ops_created=$(tmux new-session -d -s "$ops_name" -n ops -x "$ops_cols" -y "$ops_rows" \
    -P -F '#{session_id} #{pane_id}' sh -c "$ops_monitor_command") || {
    printf '%s\n' 'Could not create an ops session; opening a shell.'
    "${SHELL:-/bin/sh}" -l
    exit $?
}
ops_session=${ops_created%% *}
ops_monitor=${ops_created#* }
ops_failed() {
    tmux kill-session -t "$ops_session" 2>/dev/null
    printf '%s\n' 'Could not create the ops panes; opening a shell.'
    "${SHELL:-/bin/sh}" -l
    exit $?
}
ops_shell=$(tmux split-window -v -l 45% -t "$ops_monitor" -P -F '#{pane_id}' sh -c "$ops_shell_command") || ops_failed
ops_journal=$(tmux split-window -h -l 50% -t "$ops_monitor" -P -F '#{pane_id}' sh -c "$ops_journal_command") || ops_failed
tmux set-option -w -t "$ops_monitor" automatic-rename off
tmux set-option -w -t "$ops_monitor" pane-border-status top
tmux set-option -w -t "$ops_monitor" pane-border-format '#{pane_title}'
tmux select-pane -t "$ops_monitor" -T Processes
tmux select-pane -t "$ops_journal" -T Journal
tmux select-pane -t "$ops_shell" -T 'Shell / system'
tmux select-pane -t "$ops_shell"
tmux attach-session -t "$ops_session"
exit $?
"""
