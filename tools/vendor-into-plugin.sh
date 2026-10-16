#!/bin/sh
# Copy this Asterism release into the AI Agents Map plugin (its Python files and tests), so the
# plugin installs with nothing else and the marketplace reviews all of its code.
# usage: tools/vendor-into-plugin.sh <plugin checkout>   (then review, test and commit there)
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
plugin=${1:?usage: vendor-into-plugin.sh <plugin checkout>}
[ -f "$plugin/manifest.json" ] && [ -f "$plugin/BarWidget.qml" ] || { echo "not the plugin: $plugin" >&2; exit 1; }
[ -z "$(git -C "$root" status --porcelain)" ] || { echo "commit Asterism first" >&2; exit 1; }
cp "$root"/*.py "$plugin/"
rm -rf "$plugin/tests" && cp -r "$root/tests" "$plugin/tests"
echo "Asterism $(git -C "$root" describe --always --tags) → $plugin"
git -C "$plugin" status --short
