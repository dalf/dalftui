#!/bin/sh
# Preserve the installed entrypoint while keeping the policy with Linux support.
checkout=$(CDPATH= cd -P -- "$(dirname -- "$0")" && pwd) || exit
exec sh "$checkout/dalftui/linux/tmux-start.sh" "$@"
