#!/bin/sh
# Kept for old notes: the plugin is made from this tree by tools/sync-plugin.py (a release needs a
# committed Asterism). usage: tools/vendor-into-plugin.sh <plugin checkout>
exec python3 "$(dirname "$0")/sync-plugin.py" --release "$@"
