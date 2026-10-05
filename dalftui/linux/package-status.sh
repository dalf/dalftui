#!/bin/sh
# Read-only Debian/Ubuntu status. Do not refresh metadata or install packages.
export LC_ALL=C
printf '%s\n' 'Debian/Ubuntu package status' 'Cached metadata only; no online refresh performed.'
if ! command -v apt-get >/dev/null 2>&1; then
    printf '%s\n' 'apt-get is unavailable; package status is unknown.'
    exit 127
fi
stamp=/var/lib/apt/periodic/update-success-stamp
if [ -f "$stamp" ]; then
    printf 'Last recorded successful APT refresh: '
    date -r "$stamp" '+%Y-%m-%d %H:%M:%S %Z'
else
    printf '%s\n' 'Last successful APT refresh: unknown (no success stamp).'
fi
printf '%s\n' 'A success stamp does not guarantee that every repository is current.'
printf '%s\n' 'Simulation from cached lists (including packages kept back):'
apt-get --simulate -o Debug::NoLocking=1 upgrade
status=$?
if [ "$status" -ne 0 ]; then
    printf '%s\n' 'APT could not determine available upgrades.'
fi
if [ -f /var/run/reboot-required ]; then
    printf '%s\n' 'A reboot is requested (/var/run/reboot-required exists).'
fi
printf '%s\n' 'To check online yourself: sudo apt-get update, then rerun the check.'
exit "$status"
