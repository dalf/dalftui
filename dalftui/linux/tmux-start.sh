#!/bin/sh
# Start an independent tmux client without silently mirroring an attached session.

unset TMUX TMUX_PANE

if ! command -v tmux >/dev/null 2>&1; then
    printf '%s\n' 'tmux is not installed on this host.' >&2
    exit 127
fi

# The SSH launcher sets dalftui_host_label; @cctab_label shows it in the terminal title.
# Without one the session drops an earlier launch's label, so the title is this host.
tmux_client() {
    if [ -n "${dalftui_host_label:-}" ]; then
        tmux "$@" \; set-option @dalftui_host "$dalftui_host_label"
    else
        tmux "$@" \; set-option -u @dalftui_host
    fi
}

start_new_session() {
    tmux_client new-session "$@"
    exit $?
}

start_login_shell() {
    shell=${SHELL:-/bin/sh}
    "$shell" -l
    exit $?
}

session_rows=$(tmux list-sessions -F '#{session_id} #{session_attached}' 2>/dev/null || :)
session_count=0
only_session=
only_attached=0
while IFS=' ' read -r session_id attached; do
    [ -n "$session_id" ] || continue
    session_count=$((session_count + 1))
    only_session=$session_id
    only_attached=$attached
done <<EOF
$session_rows
EOF

if [ "$session_count" -eq 0 ]; then
    # -A makes two simultaneous first connections converge safely on session 0.
    start_new_session -A -s 0
fi

if [ "$session_count" -eq 1 ]; then
    if [ "$only_attached" -eq 0 ]; then
        tmux_client attach-session -t "$only_session"
        exit $?
    fi
    # tmux assigns the next numeric name. This keeps a second terminal independent.
    start_new_session
fi

while :; do
    printf '\n%s\n' 'Tmux sessions:'
    tmux list-sessions -F '  #{session_id}  #{session_name}  clients=#{session_attached}'
    printf '%s' 'Session id, [n] new (default), [s] shell, [q] cancel: '
    if ! IFS= read -r selection; then
        exit 1
    fi
    case $selection in
        ''|n|N)
            start_new_session
            ;;
        s|S)
            start_login_shell
            ;;
        q|Q)
            exit 0
            ;;
        *)
            if tmux has-session -t "$selection" 2>/dev/null; then
                tmux_client attach-session -t "$selection"
                exit $?
            fi
            printf 'No such tmux session: %s\n' "$selection" >&2
            ;;
    esac
done
