#!/bin/sh
# Copy this Asterism release into the AI Agents Map plugin (its Python files and tests), so the
# plugin installs with nothing else and the marketplace reviews all of its code.
# usage: tools/vendor-into-plugin.sh <plugin checkout>   (then review, test and commit there)
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
plugin=${1:?usage: vendor-into-plugin.sh <plugin checkout>}
[ -f "$plugin/manifest.json" ] && [ -f "$plugin/BarWidget.qml" ] || { echo "not the plugin: $plugin" >&2; exit 1; }
[ -z "$(git -C "$root" status --porcelain)" ] || { echo "commit Asterism first" >&2; exit 1; }
# Asterism-only modules (and their tests) stay out of the plugin: session titles and the Claude
# summary are not part of what the marketplace reviewed (ai_popup works without them).
ASTERISM_ONLY="session_topics.py"
for file in "$root"/*.py; do
    case " $ASTERISM_ONLY " in *" $(basename "$file") "*) continue ;; esac
    cp "$file" "$plugin/"
done
for name in $ASTERISM_ONLY; do rm -f "$plugin/$name" "$plugin/tests/test_$name"; done
rm -rf "$plugin/tests" && cp -r "$root/tests" "$plugin/tests"
# The translations (one data file per language) and the pictures the pages show (assets/).
rm -rf "$plugin/translations" && cp -r "$root/translations" "$plugin/translations"
mkdir -p "$plugin/assets" && cp "$root/data/llm-monitor-preview.png" "$plugin/assets/"
for name in $ASTERISM_ONLY; do rm -f "$plugin/tests/test_$name"; done
echo "Asterism $(git -C "$root" describe --always --tags) → $plugin"
git -C "$plugin" status --short
