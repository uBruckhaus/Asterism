#!/bin/sh
# Type checking for the core (the modules without GTK), with pyright as pyrightconfig.json sets it
# (its "exclude" names the GTK modules: they come later).
#
#     tools/typecheck.sh                  check; exit 1 on any error
#     tools/typecheck.sh --install-hook   also run it before every commit that changes a .py file
#
# pyright comes through uv at a pinned version: downloaded once into uv's cache, then offline, and
# the same answer on every run. --pythonpath: the system Python, whose site-packages hold cairo,
# yaml and gi (the one first on PATH may be another, e.g. mise's).
set -eu
cd "$(dirname "$0")/.."
PYRIGHT="pyright==1.1.414"

if [ "${1:-}" = "--install-hook" ]; then
    hook=.git/hooks/pre-commit
    if [ -e "$hook" ] && ! grep -q "tools/typecheck.sh" "$hook"; then
        echo "typecheck: $hook exists already; add a line that runs tools/typecheck.sh to it" >&2
        exit 1
    fi
    cat > "$hook" <<'EOF'
#!/bin/sh
# Installed by tools/typecheck.sh --install-hook: the core must type-check before a commit.
if git diff --cached --name-only --diff-filter=ACMR | grep -q '\.py$'; then
    exec tools/typecheck.sh
fi
EOF
    chmod +x "$hook"
    echo "typecheck: pre-commit hook installed"
    exit 0
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "typecheck: needs uv (pacman -S uv)" >&2
    exit 1
fi
exec uv tool run "$PYRIGHT" --pythonpath /usr/bin/python3
