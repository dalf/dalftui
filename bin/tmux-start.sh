#!/bin/sh
# Launch the canonical Linux tmux session policy from this checkout.
checkout=$(CDPATH= cd -P -- "$(dirname -- "$0")/.." && pwd) || exit
exec sh "$checkout/dalftui/linux/tmux-start.sh" "$@"
