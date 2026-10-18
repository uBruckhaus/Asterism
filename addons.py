"""Add-ons for Asterism (not in the AI Agents Map plugin): found, verified, loaded.

Only add-ons signed by Uwe Bruckhaus load. An add-on is a folder <id>/ with:
    addon.json        id, name, version, api, privacy, harnesses, reads, sends
    addon.py          register(api) (see addon_api.py); nothing may run at import time
    translations/<language>.json   optional, the add-on's own strings
    MANIFEST.sha256   "<sha256>  <path>" for every other file
    SIGNATURE         `ssh-keygen -Y sign -n asterism-addon` of MANIFEST.sha256 with Uwe's key

Before anything of it runs: the folder and every file must be the user's (or root's), regular, not
writable by others, no links, within size limits, only the files above; SIGNATURE must verify
MANIFEST.sha256 against the key below (OpenSSH's ssh-keygen); every file must match its hash and
no file may be missing from or added to the manifest. addon.py is then compiled from the very bytes
that were hashed (never read again from disk), and only when the user switched the add-on on.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import types
from dataclasses import dataclass, field
from pathlib import Path

import addon_api
import ai_core
import harnesses
import providers

# Uwe Bruckhaus's add-on signing key (fingerprint SHA256:e5cC634Ke3Our5LAeSc88qs22NKZEHTncBW5Ig3amWQ).
ALLOWED_SIGNERS = ('addons@asterism namespaces="asterism-addon" '
                   'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEIPZnfPIkyy+IX1J0jfB5g/U8U5jjJTapOogzlKrxlo')
PRINCIPAL = "addons@asterism"
NAMESPACE = "asterism-addon"

USER_DIR = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "asterism/addons"
SYSTEM_DIR = Path("/usr/lib/asterism/addons")

MAX_FILES = 64
MAX_FILE = 1024 * 1024
MAX_TOTAL = 4 * 1024 * 1024
MAX_MANIFEST = 64 * 1024
MAX_SIGNATURE = 8 * 1024
VERIFY_TIMEOUT = 10.0
_ID = re.compile(r"[a-z][a-z0-9-]{1,40}")
_VERSION = re.compile(r"\d{1,4}\.\d{1,4}\.\d{1,4}")
_LANG = re.compile(r"translations/[a-z]{2}\.json")
_LINE = re.compile(r"([0-9a-f]{64})  (\S{1,200})")
_TEXT_LIMIT = 300


@dataclass
class Addon:
    folder: Path
    id: str = ""
    name: str = ""
    version: str = ""
    api: int = 0
    privacy: int = 0
    harnesses: list = field(default_factory=list)
    reads: list = field(default_factory=list)
    sends: list = field(default_factory=list)
    capabilities: list = field(default_factory=list)    # "agent", "provider", "installer"
    state: str = "refused"           # refused | verified | loaded | failed
    reason: str = ""
    files: dict = field(default_factory=dict, repr=False)    # path -> verified bytes


def _refuse(addon: Addon, reason: str) -> Addon:
    addon.state, addon.reason, addon.files = "refused", reason, {}
    return addon


def _trusted(st: os.stat_result, uid: int) -> bool:
    return st.st_uid in (uid, 0) and not st.st_mode & (stat.S_IWGRP | stat.S_IWOTH)


def _read(path: Path, uid: int, limit: int) -> bytes | None:
    """A regular, trusted file's bytes (no links followed), or None."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as handle:
        st = os.fstat(handle.fileno())
        if not stat.S_ISREG(st.st_mode) or not _trusted(st, uid) or st.st_size > limit:
            return None
        data = handle.read(limit + 1)
    return data if len(data) <= limit else None


def _files(folder: Path, uid: int) -> list | str:
    """Every file below `folder` as a relative path, or the reason it is refused."""
    found, stack = [], [(folder, "")]
    while stack:
        current, prefix = stack.pop()
        try:
            st = os.lstat(current)
        except OSError:
            return "cannot be read"
        if not stat.S_ISDIR(st.st_mode) or not _trusted(st, uid):
            return f"folder {prefix or '.'} is a link, not yours or writable by others"
        try:
            with os.scandir(current) as entries:
                items = list(entries)
        except OSError:
            return "cannot be read"
        for item in items:
            rel = prefix + item.name
            if item.is_symlink():
                return f"{rel} is a link"
            if item.is_dir(follow_symlinks=False):
                if prefix:
                    return f"{rel}: folders may only be one level deep"
                stack.append((Path(item.path), rel + "/"))
            else:
                found.append(rel)
            if len(found) > MAX_FILES:
                return "too many files"
    return sorted(found)


def signature_ok(manifest: bytes, signature: bytes, signers: str = ALLOWED_SIGNERS) -> bool:
    """Does `signature` sign `manifest` by a key in `signers`? (ssh-keygen -Y verify)"""
    keygen = shutil.which("ssh-keygen")
    if keygen is None:
        return False
    with tempfile.TemporaryDirectory(prefix="asterism-addon-") as tmp:
        signers_file, signature_file = Path(tmp) / "allowed_signers", Path(tmp) / "SIGNATURE"
        signers_file.write_text(signers + "\n")
        signature_file.write_bytes(signature)
        _out, ok = ai_core.read_bounded_output(
            [keygen, "-Y", "verify", "-f", str(signers_file), "-I", PRINCIPAL, "-n", NAMESPACE,
             "-s", str(signature_file)], max_bytes=4096, timeout=VERIFY_TIMEOUT, stdin=manifest)
    return ok


def _texts(value, limit: int = 12) -> list:
    if not isinstance(value, list):
        return []
    return [" ".join(str(v).split())[:_TEXT_LIMIT] for v in value[:limit] if isinstance(v, str) and v.strip()]


def verify(folder: Path, signers: str = ALLOWED_SIGNERS, uid: int | None = None) -> Addon:
    """Check an add-on folder completely; state "verified" with its files, or "refused" with why."""
    uid = os.getuid() if uid is None else uid
    addon = Addon(folder=folder, id=folder.name)
    if not _ID.fullmatch(folder.name):
        return _refuse(addon, "the folder name is not an add-on id")
    names = _files(folder, uid)
    if isinstance(names, str):
        return _refuse(addon, names)
    allowed = {"addon.json", "addon.py", "MANIFEST.sha256", "SIGNATURE"}
    strange = [n for n in names if n not in allowed and not _LANG.fullmatch(n)]
    if strange:
        return _refuse(addon, f"unexpected file {strange[0]}")
    if "SIGNATURE" not in names or "MANIFEST.sha256" not in names:
        return _refuse(addon, "not signed")
    manifest = _read(folder / "MANIFEST.sha256", uid, MAX_MANIFEST)
    signature = _read(folder / "SIGNATURE", uid, MAX_SIGNATURE)
    if manifest is None or signature is None:
        return _refuse(addon, "the signature files cannot be read safely")
    if not signature_ok(manifest, signature, signers):
        reason = "not signed by Uwe Bruckhaus" if shutil.which("ssh-keygen") else \
            "ssh-keygen (OpenSSH) is missing, so the signature cannot be checked"
        return _refuse(addon, reason)
    listed = {}
    for line in manifest.decode("utf-8", "replace").splitlines():
        m = _LINE.fullmatch(line)
        if m is None or m.group(2) in listed:
            return _refuse(addon, "the manifest is malformed")
        listed[m.group(2)] = m.group(1)
    if set(listed) != set(names) - {"MANIFEST.sha256", "SIGNATURE"}:
        return _refuse(addon, "files differ from the signed list")
    files, total = {}, 0
    for name, digest in listed.items():
        data = _read(folder / name, uid, MAX_FILE)
        if data is None:
            return _refuse(addon, f"{name} cannot be read safely")
        total += len(data)
        if total > MAX_TOTAL:
            return _refuse(addon, "too large")
        if hashlib.sha256(data).hexdigest() != digest:
            return _refuse(addon, f"{name} was changed")
        files[name] = data
    try:
        meta = json.loads(files["addon.json"])
    except (KeyError, ValueError):
        return _refuse(addon, "addon.json is missing or not JSON")
    if not isinstance(meta, dict) or meta.get("id") != folder.name:
        return _refuse(addon, "addon.json does not name this add-on")
    if "addon.py" not in files:
        return _refuse(addon, "addon.py is missing")
    version, api, privacy = meta.get("version"), meta.get("api"), meta.get("privacy")
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        return _refuse(addon, "the version is not x.y.z")
    if api != addon_api.API_VERSION:
        return _refuse(addon, f"made for add-on API {api}, this Asterism has {addon_api.API_VERSION}")
    if privacy not in addon_api.PRIVACY:
        return _refuse(addon, "unknown privacy level")
    addon.name = " ".join(str(meta.get("name") or folder.name).split())[:80]
    addon.version, addon.api, addon.privacy = version, api, addon_api.PRIVACY[privacy]
    capabilities = meta.get("capabilities", [])
    if not isinstance(capabilities, list) or not all(c in addon_api.CAPABILITIES for c in capabilities):
        return _refuse(addon, "unknown capabilities")
    addon.harnesses, addon.reads, addon.sends = (_texts(meta.get("harnesses")), _texts(meta.get("reads")),
                                                 _texts(meta.get("sends")))
    addon.capabilities = sorted(set(capabilities))
    addon.files, addon.state, addon.reason = files, "verified", ""
    return addon


def strings(addon: Addon) -> dict:
    """The add-on's translations: language -> {English: translation} (only plain strings)."""
    found = {}
    for name, data in addon.files.items():
        if _LANG.fullmatch(name):
            try:
                table = json.loads(data)
            except ValueError:
                continue
            if isinstance(table, dict):
                found[name[13:15]] = {k: v for k, v in table.items() if isinstance(k, str) and isinstance(v, str)}
    return found


def load(addon: Addon, hooks: addon_api.Hooks = addon_api.HOOKS) -> Addon:
    """Run a verified add-on's register(api) from its verified bytes."""
    if addon.state != "verified":
        return addon
    module = types.ModuleType(f"asterism_addon_{addon.id.replace('-', '_')}")
    module.__file__ = str(addon.folder / "addon.py")
    api = addon_api.AddonAPI(addon.id, addon.privacy, strings(addon), hooks, addon.capabilities)
    try:
        exec(compile(addon.files["addon.py"], module.__file__, "exec"), module.__dict__)
        register = getattr(module, "register", None)
        if not callable(register):
            raise addon_api.AddonError("addon.py has no register(api)")
        register(api)
    except Exception as error:          # a broken add-on must not stop the app
        addon_api.failed(addon.id, error, hooks)
        addon.state, addon.reason = "failed", hooks.errors[addon.id]
        for registry in (hooks.details, hooks.help, hooks.settings):
            registry[:] = [entry for entry in registry if entry[0] != addon.id]
        for command in list(hooks.titles):
            hooks.titles[command] = [entry for entry in hooks.titles[command] if entry[0] != addon.id]
        harnesses.remove_added(addon.id)
        providers.remove_added(addon.id)
        return addon
    hooks.privacy[addon.id] = addon.privacy
    addon.state = "loaded"
    return addon


def find(dirs=(USER_DIR, SYSTEM_DIR)) -> list:
    """Add-on folders; an id in the user folder wins over the same id installed system-wide."""
    seen, found = set(), []
    for base in dirs:
        try:
            entries = sorted(p for p in Path(base).iterdir() if p.name not in seen)
        except OSError:
            continue
        for path in entries[:100]:
            seen.add(path.name)
            found.append(path)
    return found


def load_all(enabled, dirs=(USER_DIR, SYSTEM_DIR), signers: str = ALLOWED_SIGNERS,
             hooks: addon_api.Hooks = addon_api.HOOKS) -> list:
    """Verify every add-on found (to show its state) and load the ones switched on; then the
    modules rebuild their tables, so the add-ons' agents and providers appear everywhere."""
    hooks.clear()
    harnesses.remove_added()
    providers.remove_added()
    result = []
    for folder in find(dirs):
        addon = verify(folder, signers)
        if addon.state == "verified" and addon.id in enabled:
            load(addon, hooks)
        result.append(addon)
    harnesses.changed()
    providers.changed()
    return result
