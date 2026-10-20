#!/usr/bin/env python3
"""One source for both editions: the AI Agents Map plugin's shared files are made from this
Asterism tree and never edited in the plugin.

    tools/sync-plugin.py <plugin checkout>             copy what is shared, remove what is stale
    tools/sync-plugin.py --check <plugin checkout>     list the differences; exit 1 if there are any
    tools/sync-plugin.py --release <plugin checkout>   as the first, from a committed Asterism only
    tools/sync-plugin.py --install-hook <plugin>       the plugin refuses commits that differ from here

Shared (Asterism → plugin): every *.py here except the add-on modules, adapters/, tests/ (without the add-on
tests), icons/, translations/, LICENSE, and data/user-manual*.pdf → assets/. The add-on modules stay
out: their absence is what limits the plugin to numbers (edition.maximum(); ai_popup works without
them), and the marketplace reviewed the plugin without them.

AI Playground (the plugin whose manifest id is ubruckhaus.ai-playground) is made from the same
tree: the core modules it uses (PLAYGROUND_CORE), playground/*.py (its own, chess too) at its top,
playground/tests in tests/, adapters/, icons/, translations/ and LICENSE.

The plugin's own files (BarWidget.qml, I18n.js, manifest.json, preview.png, README.md, .gitignore,
the bar toggle with its local-only part, its other assets) are never touched. Anything else in a
shared place that this tree no longer has (a module removed here) is stale and goes.
"""

from __future__ import annotations

import argparse
import filecmp
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASTERISM_ONLY = {"addons.py", "addon_api.py", "addon_store.py", "addons_page.py"}
ASTERISM_ONLY_TESTS = {"test_packaging.py"}       # Asterism's packages (packaging/): the plugin has none
ADDON_IMPORT = re.compile(r"^(import|from) (addons|addon_api|addon_store|addons_page)\b", re.M)
SHARED_DIRS = ("tests", "icons", "translations", "adapters")   # mirrored whole (minus what is left out)
SKIP = {"__pycache__", ".git", ".pytest_cache"}
PLAYGROUND_ID = "ubruckhaus.ai-playground"
# What AI Playground imports (a run that opened every tab, 2026-10-20), and desktop_generic for
# other desktops. Its tests import each of them, so a missing one fails there.
PLAYGROUND_CORE = ("adapter_data", "agent_details", "agent_status", "ai_core", "claude_sessions", "corners", "dsh_ctl",
                   "desktop", "desktop_generic", "desktop_omarchy", "gpu_usage", "harnesses", "i18n", "icons",
                   "loopback", "more_plugins", "netfetch", "palette", "runtime_ctl", "settings_schema", "signin",
                   "text_guard", "theme_css")


def edition(plugin: Path) -> str:
    """"playground" for AI Playground, else "map" (AI Agents Map)."""
    try:
        import json
        return "playground" if json.loads((plugin / "manifest.json").read_text()).get("id") == PLAYGROUND_ID \
            else "map"
    except (OSError, ValueError):
        return "map"


def wanted_playground() -> dict[str, Path]:
    files = {f"{name}.py": ROOT / f"{name}.py" for name in PLAYGROUND_CORE}
    files.update({source.name: source for source in sorted((ROOT / "playground").glob("*.py"))})
    files.update({f"tests/{source.name}": source for source in sorted((ROOT / "playground/tests").glob("*.py"))})
    for folder in ("icons", "translations", "adapters"):
        for source in sorted((ROOT / folder).rglob("*")):
            rel = source.relative_to(ROOT)
            if source.is_file() and not SKIP & set(rel.parts) and source.suffix != ".pyc":
                files[str(rel)] = source
    files["LICENSE"] = ROOT / "LICENSE"
    return files


def wanted(kind: str = "map") -> dict[str, Path]:
    """{path in the plugin: source file here} for everything shared."""
    if kind == "playground":
        return wanted_playground()
    files = {}
    for source in sorted(ROOT.glob("*.py")):
        if source.name not in ASTERISM_ONLY:
            files[source.name] = source
    for folder in SHARED_DIRS:
        for source in sorted((ROOT / folder).rglob("*")):
            rel = source.relative_to(ROOT)
            if not source.is_file() or SKIP & set(rel.parts) or source.suffix == ".pyc":
                continue
            if folder == "tests" and source.suffix == ".py" and (
                    source.name.removeprefix("test_") in ASTERISM_ONLY or source.name in ASTERISM_ONLY_TESTS
                    or ADDON_IMPORT.search(source.read_text(errors="replace"))):
                continue                       # tests of (or loading) the add-on modules
            files[str(rel)] = source
    files["LICENSE"] = ROOT / "LICENSE"
    for source in sorted((ROOT / "data").glob("user-manual*.pdf")):
        files[f"assets/{source.name}"] = source
    return files


def present(plugin: Path) -> set[str]:
    """The plugin's files in the places this tree owns (its own files and assets left out)."""
    found = set()
    for path in plugin.iterdir():
        if path.is_file() and path.suffix == ".py":
            found.add(path.name)
    for folder in SHARED_DIRS:
        for path in (plugin / folder).rglob("*") if (plugin / folder).is_dir() else ():
            rel = path.relative_to(plugin)
            if path.is_file() and not SKIP & set(rel.parts) and path.suffix != ".pyc":
                found.add(str(rel))
    found.update(f"assets/{p.name}" for p in (plugin / "assets").glob("user-manual*.pdf"))
    return found


def differences(plugin: Path) -> tuple[list, list, list]:
    """(missing in the plugin, different there, stale there)."""
    files, have = wanted(edition(plugin)), present(plugin)
    missing = [rel for rel in files if not (plugin / rel).is_file()]
    changed = [rel for rel in files if (plugin / rel).is_file()
               and not filecmp.cmp(files[rel], plugin / rel, shallow=False)]
    stale = sorted(have - set(files))
    return missing, changed, stale


def is_plugin(plugin: Path) -> bool:
    return (plugin / "manifest.json").is_file() and (plugin / "BarWidget.qml").is_file()


def describe() -> str:
    run = subprocess.run(["git", "-C", str(ROOT), "describe", "--always", "--tags", "--dirty"],
                         capture_output=True, text=True)
    return run.stdout.strip() or "?"


def sync(plugin: Path) -> int:
    missing, changed, stale = differences(plugin)
    files = wanted(edition(plugin))
    for rel in missing + changed:
        target = plugin / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(files[rel], target)
    for rel in stale:
        (plugin / rel).unlink()
    for folder in SHARED_DIRS:                 # folders a removed file left empty
        for path in sorted((plugin / folder).rglob("*"), reverse=True) if (plugin / folder).is_dir() else ():
            if path.is_dir() and not SKIP & set(path.parts) and not any(path.iterdir()):
                path.rmdir()
    print(f"Asterism {describe()} → {plugin}: {len(missing)} added, {len(changed)} updated, "
          f"{len(stale)} removed")
    for label, items in (("added", missing), ("updated", changed), ("removed", stale)):
        for rel in items:
            print(f"  {label:8} {rel}")
    return 0


def check(plugin: Path) -> int:
    missing, changed, stale = differences(plugin)
    if not (missing or changed or stale):
        print(f"The plugin's shared files match Asterism {describe()}.")
        return 0
    print(f"The plugin differs from Asterism {describe()} (edit in {ROOT}, then run "
          f"tools/sync-plugin.py {plugin}):", file=sys.stderr)
    for label, items in (("missing", missing), ("differs", changed), ("stale", stale)):
        for rel in items:
            print(f"  {label:8} {rel}", file=sys.stderr)
    return 1


HOOK = """#!/bin/sh
# Shared files come from Asterism (tools/sync-plugin.py); a commit with them changed here is refused.
# Skip once with: git commit --no-verify
exec python3 {script} --check "$(git rev-parse --show-toplevel)"
"""


def install_hook(plugin: Path) -> int:
    hook = plugin / ".git/hooks/pre-commit"
    if hook.exists() and "sync-plugin.py" not in hook.read_text(errors="replace"):
        print(f"{hook} exists and is not ours; left as it is", file=sys.stderr)
        return 1
    hook.write_text(HOOK.format(script=Path(__file__).resolve()))
    hook.chmod(0o755)
    print(f"Installed {hook}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("plugin", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="only list the differences")
    mode.add_argument("--release", action="store_true", help="only from a committed Asterism")
    mode.add_argument("--install-hook", action="store_true", help="pre-commit check in the plugin")
    args = parser.parse_args()
    plugin = args.plugin.expanduser().resolve()
    if not is_plugin(plugin):
        print(f"not the plugin: {plugin}", file=sys.stderr)
        return 2
    if args.check:
        return check(plugin)
    if args.install_hook:
        return install_hook(plugin)
    if args.release and subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"],
                                       capture_output=True, text=True).stdout.strip():
        print("commit Asterism first", file=sys.stderr)
        return 1
    return sync(plugin)


if __name__ == "__main__":
    sys.exit(main())
