#!/bin/sh
# Start or resume tmux so that a session keeps one client: attach with -d, and
# ask before creating, attaching or taking over whenever the choice is unclear.

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

# Over SSH, an installed host whose tmux server runs the dalftui hooks, or will
# load them when it starts, gives each new session a private, stable agent alias
# (bin/session_owner.py). Other hosts, and local terminals, keep tmux's usual
# SSH_AUTH_SOCK handling.
new_agent_alias() {
    [ -n "${SSH_CONNECTION:-}" ] && [ -r /proc/self/environ ] || return 1
    case ${XDG_CONFIG_HOME:-} in
        /*) agent_helper=$XDG_CONFIG_HOME/dalftui/bin/session_owner.py ;;
        *) agent_helper=$HOME/.config/dalftui/bin/session_owner.py ;;
    esac
    [ -r "$agent_helper" ] && command -v python3 >/dev/null 2>&1 || return 1
    agent_alias=$(python3 "$agent_helper" new 2>/dev/null) || return 1
    case $agent_alias in
        /*/*) ;;
        *) return 1 ;;
    esac
    case $agent_alias in *[!-A-Za-z0-9/._]*) return 1 ;; esac
}

# Every session this launcher creates starts here. tmux spawns the first pane
# before session-created, and creation emits no client-attached, so the first
# shell gets the alias from new-session -e. The helper has already pointed the
# alias at this connection's agent, because this process's tmux client becomes
# the owner. The option records it, unless -A attached an existing session that
# already has one.
start_new_session() {
    if new_agent_alias; then
        tmux_client new-session -e "SSH_AUTH_SOCK=$agent_alias" "$@" \; \
            if-shell -F '#{?@dalftui_agent_alias,,1}' "set-option @dalftui_agent_alias $agent_alias"
    else
        tmux_client new-session "$@"
    fi
    exit $?
}

# -d detaches the session's other clients, so two terminals never mirror it.
attach_session() {
    tmux_client attach-session -d -t "$1"
    exit $?
}

# detach-client -E (tmux 2.4+) replaces each other client with a message, so the
# closing terminal says why. The pause keeps it readable: the SSH launcher closes
# a window that exits 0 at once. attach -d detaches any remaining client regardless.
take_over_session() {
    tmux detach-client -s "$1" -E \
        "printf '%s\\n' 'Another terminal took over this tmux session.'; sleep 3" >/dev/null 2>&1
    attach_session "$1"
}

# Ops sessions (dalftui-ops-*) belong to their own window and destroy themselves
# once unattached, so they never count here. Names are display-only data;
# sessions are always targeted by ID.
load_sessions() {
    session_count=0
    session_rows=$(tmux list-sessions -F '#{session_id} #{session_attached} #{session_name}' \
        2>/dev/null) || session_rows=
    while IFS=' ' read -r row_id row_attached row_name; do
        [ -n "$row_id" ] || continue
        case $row_name in dalftui-ops-*) continue ;; esac
        case $row_attached in ''|*[!0-9]*) row_attached=0 ;; esac
        session_count=$((session_count + 1))
        eval "session_id_$session_count=\$row_id"
        eval "session_attached_$session_count=\$row_attached"
        eval "session_name_$session_count=\$row_name"
    done <<EOF
$session_rows
EOF
}

load_sessions

if [ "$session_count" -eq 0 ]; then
    # Two simultaneous first connections converge on session 0; -D makes the
    # later one take it over instead of mirroring it.
    start_new_session -A -D -s 0
fi

if [ "$session_count" -eq 1 ]; then
    if [ "$session_attached_1" -eq 0 ]; then
        attach_session "$session_id_1"
    fi
    # A local terminal's client cannot be a dead connection: open another session.
    if [ -z "${SSH_CONNECTION:-}" ]; then
        start_new_session
    fi
fi

# A remote client still counted as attached may be a live tab or a connection
# that died while its laptop slept. Only the user can tell, so ask.
if [ ! -t 0 ]; then
    printf '%s\n' 'Choosing a tmux session needs a terminal; nothing was started.' >&2
    exit 1
fi

# Client details describe a session; they never choose or suggest one.
load_clients() {
    menu_now=$(date +%s 2>/dev/null) || menu_now=
    case $menu_now in ''|*[!0-9]*) menu_now= ;; esac
    client_rows=$(tmux list-clients \
        -F '#{session_id} #{client_pid} #{client_created} #{client_activity} #{client_tty}' \
        2>/dev/null) || client_rows=
}

format_age() {
    case $1 in ''|*[!0-9]*) return 1 ;; esac
    [ -n "$menu_now" ] || return 1
    age=$((menu_now - $1))
    [ "$age" -ge 0 ] || age=0
    if [ "$age" -lt 60 ]; then
        printf '%ss' "$age"
    elif [ "$age" -lt 3600 ]; then
        printf '%sm' $((age / 60))
    elif [ "$age" -lt 86400 ]; then
        printf '%sh%02dm' $((age / 3600)) $((age % 3600 / 60))
    else
        printf '%sd%02dh' $((age / 86400)) $((age % 86400 / 3600))
    fi
}

# The client's own environment tells where it connected from; the session
# environment may describe an older connection.
client_origin() {
    case $1 in ''|*[!0-9]*) return 1 ;; esac
    [ -r "/proc/$1/environ" ] || return 1
    client_environment=$(tr '\0' '\n' < "/proc/$1/environ" 2>/dev/null) || return 1
    [ -n "$client_environment" ] || return 1
    client_address=
    while IFS= read -r client_entry; do
        case $client_entry in
            SSH_CONNECTION=*)
                client_address=${client_entry#SSH_CONNECTION=}
                client_address=${client_address%% *}
                break
                ;;
        esac
    done <<EOF
$client_environment
EOF
    case $client_address in
        '') printf 'local' ;;
        *[!0-9A-Za-z.:%_-]*) return 1 ;;
        *) printf 'from %s' "$client_address" ;;
    esac
}

client_summary() {
    summary=${3#/dev/}
    if origin=$(client_origin "$1"); then
        summary="$summary $origin"
    fi
    if age=$(format_age "$2"); then
        summary="$summary, connected $age ago"
    fi
    if age=$(format_age "$4"); then
        summary="$summary, last key $age ago"
    fi
    printf '%s' "$summary"
}

# $1: session ID; $2: indentation for any further clients.
print_clients() {
    clients_printed=0
    while IFS=' ' read -r client_session client_pid client_created client_activity client_tty; do
        [ "$client_session" = "$1" ] || continue
        [ "$clients_printed" -eq 0 ] || printf '\n%s' "$2"
        printf '  %s' "$(client_summary "$client_pid" "$client_created" "$client_tty" "$client_activity")"
        clients_printed=$((clients_printed + 1))
    done <<EOF
$client_rows
EOF
    printf '\n'
}

print_sessions() {
    menu_host=$(tmux display-message -p '#{host_short}' 2>/dev/null) || menu_host=
    if [ -n "$menu_host" ]; then
        printf '\ntmux sessions on %s:\n' "$menu_host"
    else
        printf '\n%s\n' 'tmux sessions:'
    fi
    number_width=1
    [ "$session_count" -lt 10 ] || number_width=2
    name_width=1
    index=1
    while [ "$index" -le "$session_count" ]; do
        eval "name=\$session_name_$index"
        [ "${#name}" -le "$name_width" ] || name_width=${#name}
        index=$((index + 1))
    done
    [ "$name_width" -le 24 ] || name_width=24
    indent=$(printf "  %${number_width}s  %-${name_width}s  %-8s" '' '' '')
    index=1
    while [ "$index" -le "$session_count" ]; do
        eval "id=\$session_id_$index attached=\$session_attached_$index name=\$session_name_$index"
        if [ "$attached" -eq 0 ]; then
            printf "  %${number_width}s  %-${name_width}s  %s\n" "$index" "$name" detached
        else
            printf "  %${number_width}s  %-${name_width}s  %-8s" "$index" "$name" attached
            print_clients "$id" "$indent"
        fi
        index=$((index + 1))
    done
}

menu_newline='
'
menu_return=$(printf '\r')
menu_eot=$(printf '\004')
menu_tty=
menu_restore() {
    if [ -n "$menu_tty" ]; then
        stty "$menu_tty" 2>/dev/null
        menu_tty=
    fi
}
# Ctrl+C cancels like q, exiting through any caller's EXIT trap.
menu_cancel() {
    menu_restore
    printf '\n'
    exit 0
}
trap menu_cancel INT

menu_single_key=
if command -v stty >/dev/null 2>&1 && command -v dd >/dev/null 2>&1; then
    menu_single_key=1
fi

# Discard keys typed just after a choice, such as an Enter out of habit, so they
# never reach the pane or answer the next question. Wait until no key has come
# for 0.5 s, at most ten times: over SSH, an Enter can follow the key by 0.3 s.
menu_settle() {
    if [ -z "$menu_single_key" ] || ! menu_tty=$(stty -g 2>/dev/null) ||
            [ -z "$menu_tty" ] || ! stty -icanon -echo min 0 time 5 2>/dev/null; then
        menu_restore
        return 0
    fi
    menu_drained=0
    while [ "$menu_drained" -lt 10 ] &&
            [ "$(dd bs=64 count=1 2>/dev/null; printf x)" != x ]; do
        menu_drained=$((menu_drained + 1))
    done
    menu_restore
}

# Return Ctrl+C to the normal interrupt status before tmux starts.
leave_menu() {
    trap 'exit 130' INT
}

# Set menu_answer; return 1 at end of input. With "key", read one keystroke
# when possible, without waiting for Enter.
menu_read() {
    menu_answer=
    if [ "$1" = key ] && [ -n "$menu_single_key" ] &&
            menu_tty=$(stty -g 2>/dev/null) && [ -n "$menu_tty" ] &&
            stty -icanon -echo min 1 time 0 2>/dev/null; then
        menu_answer=$(dd bs=1 count=1 2>/dev/null; printf x)
        # Discard the rest of a multi-byte key, such as an arrow or an accent.
        menu_rest=$(stty min 0 time 0 2>/dev/null && dd bs=64 count=1 2>/dev/null; printf x)
        menu_restore
        menu_answer=${menu_answer%x}
        case $menu_answer in
            ''|"$menu_eot")
                printf '\n'
                return 1
                ;;
            "$menu_newline"|"$menu_return") menu_answer= ;;
        esac
        # An Enter that arrived with the key, typed out of habit, ends the answer.
        menu_rest=${menu_rest%x}
        while :; do
            case $menu_rest in
                *"$menu_newline"|*"$menu_return") menu_rest=${menu_rest%?} ;;
                *) break ;;
            esac
        done
        menu_answer=$menu_answer$menu_rest
        case $menu_answer in
            [[:print:]]) printf '%s\n' "$menu_answer" ;;
            *) printf '\n' ;;
        esac
        return 0
    fi
    menu_restore
    read -r menu_answer
}

# Print the picked session's client count, or report that it has gone and fail.
# display-message prints nothing for a missing session, yet succeeds.
current_clients() {
    if tmux has-session -t "$picked_id" 2>/dev/null; then
        picked_count=$(tmux display-message -p -t "$picked_id" '#{session_attached}' 2>/dev/null)
        if [ -n "$picked_count" ]; then
            printf '%s\n' "$picked_count"
            return 0
        fi
    fi
    printf 'Session %s no longer exists.\n' "${picked_name:-$picked_id}" >&2
    return 1
}

not_a_choice() {
    case $1 in
        ''|*[![:print:]]*) printf '%s\n' 'Not a choice.' >&2 ;;
        *) printf 'Not a choice: %s\n' "$1" >&2 ;;
    esac
}

while :; do
    load_sessions
    load_clients
    print_sessions
    # A typed number is needed only beyond nine sessions.
    menu_mode=key
    [ "$session_count" -le 9 ] || menu_mode=line
    case $session_count in
        0) range= ;;
        1) range='[1] attach   ' ;;
        *) range="[1-$session_count] attach   " ;;
    esac
    printf '%s[n] new session (default)   [q] cancel\nChoice [n]: ' "$range"
    menu_read "$menu_mode" || exit 1
    menu_settle
    case $menu_answer in
        ''|n|N)
            leave_menu
            start_new_session
            ;;
        q|Q)
            exit 0
            ;;
        *[!0-9]*)
            not_a_choice "$menu_answer"
            continue
            ;;
    esac
    # A typed 01 means 1: the number becomes part of a variable name below.
    menu_number=$menu_answer
    while :; do
        case $menu_number in
            0?*) menu_number=${menu_number#0} ;;
            *) break ;;
        esac
    done
    if [ "${#menu_number}" -gt 4 ] || [ "$menu_number" -lt 1 ] ||
            [ "$menu_number" -gt "$session_count" ]; then
        not_a_choice "$menu_answer"
        continue
    fi
    eval "picked_id=\$session_id_$menu_number picked_name=\$session_name_$menu_number"
    if [ -z "$picked_id" ]; then
        not_a_choice "$menu_answer"
        continue
    fi
    # Use the session's current state: another terminal may have changed it.
    picked_clients=$(current_clients) || continue
    case $picked_clients in *[!0-9]*) picked_clients=0 ;; esac
    if [ "$picked_clients" -eq 0 ]; then
        leave_menu
        attach_session "$picked_id"
    fi
    if [ "$picked_clients" -eq 1 ]; then
        printf 'Session %s has a client. Take it over (its window closes)? [y/N] ' \
            "${picked_name:-$picked_id}"
    else
        printf 'Session %s has %s clients. Take it over (their windows close)? [y/N] ' \
            "${picked_name:-$picked_id}" "$picked_clients"
    fi
    menu_read key || exit 1
    menu_settle
    case $menu_answer in
        y|Y)
            # The session may have closed while the question waited.
            current_clients >/dev/null || continue
            leave_menu
            take_over_session "$picked_id"
            ;;
    esac
done
