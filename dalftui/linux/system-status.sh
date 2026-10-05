#!/bin/sh
# Read-only snapshot; the caller also bounds the whole report before opening a shell.
export LC_ALL=C
status_view=${status_view:-detailed}
incomplete=0
status_warn='WARN '
status_error='ERR  '
if [ -t 1 ] && [ "${TERM:-dumb}" != dumb ]; then
    status_warn=$(printf '\033[33mWARN\033[39m ')
    status_error=$(printf '\033[31mERR\033[39m  ')
fi
line() {
    case $1 in
        WARN) printf '%s' "$status_warn" ;;
        ERR) printf '%s' "$status_error" ;;
        *) printf '     ' ;;
    esac
    shift
    printf '%s\n' "$*"
}
for tool in timeout awk; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        line ERR "System overview unavailable: $tool is missing."
        exit 127
    fi
done

capture() {
    if command -v "$1" >/dev/null 2>&1; then
        output=$(timeout --kill-after=1s 2s "$@" 2>&1)
        status=$?
    else
        output="$1 is unavailable"
        status=127
    fi
}

unknown() {
    incomplete=1
    case $status in
        124|137) line ERR "$1: unknown (timed out)" ;;
        *) printf '%s%s: unknown - ' "$status_error" "$1"
           printf '%s\n' "${output:-command failed (exit $status)}" |
               awk '{printf "%s%s", (NR == 1 ? "" : " "), $0} END {print ""}' ;;
    esac
}

value() {
    label=$1
    shift
    capture "$@"
    if [ "$status" -eq 0 ] && [ -n "$output" ]; then
        line '' "$label: $output"
    else
        unknown "$label"
    fi
}

line '' 'System overview (snapshot; no automatic sudo)'
value Host hostname
value Time date '+%F %T %Z'
value Uptime uptime
[ "$status_view" = detailed ] && value CPUs nproc
capture systemctl is-system-running
case "$status:$output" in
    0:running) line '' "Systemd: $output" ;;
    1:degraded|1:starting|1:initializing|1:maintenance|1:stopping|1:offline)
        line WARN "Systemd: $output" ;;
    *) unknown Systemd ;;
esac
capture systemctl list-units --failed --no-legend --plain --no-pager
if [ "$status" -eq 0 ]; then
    printf '%s\n' "$output" | awk -v view="$status_view" -v warn="$status_warn" '
        NF {count++; units = units "         " (view == "detailed" ? $0 : $1) "\n"}
        END {printf "%sFailed units: %d%s\n", (count ? warn : "     "), count, (count ? "" : " (none)");
             printf "%s", units}' || incomplete=1
else
    unknown 'Failed units'
fi

capture free -h
if [ "$status" -eq 0 ]; then
    if [ "$status_view" = detailed ]; then
        printf '\n     == Memory\n'
        printf '%s\n' "$output" | awk '{print "     " $0}'
    else
        printf '%s\n' "$output" | awk -v error="$status_error" '
            $1 == "Mem:" && NF >= 7 {memory = $7 " available / " $2}
            $1 == "Swap:" && NF >= 4 {swap = $3 " used / " $2}
            END {if (memory == "" || swap == "") {print error "Memory: unknown (unexpected free output)"; exit 1}
                 print "     Memory: " memory "; swap: " swap}' || incomplete=1
    fi
else
    unknown Memory
fi

filesystems() {
    capture df "$1"
    if [ "$status" -ne 0 ]; then
        unknown "$2"
        return
    fi
    # Keep root regardless of type, including overlay or tmpfs roots. Keep remote
    # data mounts too; slow/unavailable mounts produce an explicit unknown result.
    printf '%s\n' "$output" | awk -v view="$status_view" -v label="$2" -v warn="$status_warn" -v error="$status_error" '
        NR == 1 {if (view == "detailed") print "\n     == " label "\n     " $0; next}
        NF >= 7 {
            mount = $7; for (i = 8; i <= NF; i++) mount = mount " " $i;
            if (mount != "/" && $2 ~ /^(tmpfs|devtmpfs|squashfs|efivarfs)$/) next;
            count++; warning = $6 != "-" && $6+0 >= 80; warnings += warning;
            if (view == "detailed") print (warning ? warn : "     ") $0;
            else if ((mount == "/" && label == "Disk space") || (warning && shown < 3)) {
                printf "%s%s: %s %s used, %s available\n", (warning ? warn : "     "), label, mount, $6, $5;
                shown++; shown_warnings += warning;
            }
        }
        END {
            if (!count) {print error label ": unknown (no filesystem data)"; exit 1}
            printf "%s%s: %d filesystems checked; %d at >=80%%%s\n", (warnings ? warn : "     "), label, count, warnings,
                   (view == "compact" && warnings > shown_warnings ? " (see F7 system for all)" : "");
        }' || incomplete=1
}
filesystems -hPT 'Disk space'
filesystems -iPT Inodes

if [ -f /run/reboot-required ]; then
    line WARN 'Reboot: requested (/run/reboot-required)'
    if [ "$status_view" = detailed ] && [ -f /run/reboot-required.pkgs ]; then
        value 'Reboot packages' cat /run/reboot-required.pkgs
    fi
else
    line '' 'Reboot: no request recorded'
fi
capture timedatectl show -p NTPSynchronized --value
case "$status:$output" in
    0:yes) line '' 'NTP synchronized: yes' ;;
    0:no) line WARN 'NTP synchronized: no' ;;
    *) unknown 'NTP synchronized' ;;
esac
if [ -e /proc/mdstat ]; then
    capture cat /proc/mdstat
    if [ "$status" -eq 0 ]; then
        printf '%s\n' "$output" | awk -v view="$status_view" -v warn="$status_warn" '
            $1 ~ /^md/ && $2 == ":" {arrays++}
            /\[[U_]*_[U_]*\]/ {degraded=1}
            /recovery|resync|reshape|check =|repair =/ {busy=1}
            {if (view == "detailed") text = text $0 "\n"}
            END {
                if (!arrays && !degraded && !busy) exit;
                printf "%sSoftware RAID: %s%s\n", (degraded ? warn : "     "), (degraded ? "degraded" : "no degraded member pattern found"),
                       (busy ? "; maintenance in progress" : "");
                if (view == "detailed" && arrays) printf "%s", text;
            }' || incomplete=1
    else
        unknown 'Software RAID'
    fi
fi

if [ "$status_view" = detailed ]; then
    printf '\n     == Kernel (version difference alone does not imply a required reboot)\n'
    value Running uname -r
    capture sh -c 'find /boot -maxdepth 1 -name "vmlinuz-*" -print'
    if [ "$status" -eq 0 ] && [ -n "$output" ]; then
        kernels=$output
        capture sort -V <<EOF
$kernels
EOF
        if [ "$status" -eq 0 ]; then
            printf '%s\n' "$output" | awk 'END {sub(".*/vmlinuz-", ""); print "     Highest version found in /boot: " $0 " (boot selection not checked)"}'
        else
            unknown 'Installed kernels'
        fi
    elif [ "$status" -eq 0 ]; then
        output='no kernel images found in /boot'
        unknown 'Installed kernels'
    else
        unknown 'Installed kernels'
    fi

    journal() {
        printf '\n     == %s (this boot, last hour; visible entries only)\n' "$1"
        shift
        capture journalctl --boot --since '-1 hour' --no-pager "$@"
        if [ "$status" -eq 0 ] || { [ "$status" -eq 1 ] && [ "$output" = '-- No entries --' ]; }; then
            printf '%s\n' "${output:-No matching visible entries; journal access may be limited.}"
        else
            unknown Journal
        fi
    }
    journal 'Recent errors, up to 15 entries' --priority=err --lines=15
    journal 'Kernel OOM messages, up to 5 entries' --dmesg --lines=5 --grep='out of memory|oom-kill|killed process' --case-sensitive=no
fi
exit "$incomplete"
