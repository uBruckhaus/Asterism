"""Session readers for agents whose session files have token counts: the same numbers as
claude_sessions (claude_sessions.Session: first and last reply, replies, tokens per model as input,
output, cache read and cache write), for the details page's usage, projects and API cost cards and the
map's cost label. Which agent uses which reader comes from its adapter ([sessions] reader).

- codex-files: ~/.codex/sessions/<y>/<m>/<d>/rollout-*.jsonl; the session's working folder from
  session_meta, its model from turn_context, its tokens from the last token_count's total_token_usage
  (input there includes the cached tokens: they are taken out as cache read).
- pi-files: ~/.pi/agent/sessions/<folder>/*.jsonl; each assistant message's usage (input, output,
  cacheRead, cacheWrite) under its model, the session header's cwd.
- dsh-files: ~/.dsh/sessions/<folder>/session-*/session.v4.jsonl.zstd (zstd, Python 3.14's
  compression.zstd); each assistant/message's usage (inputTokens, outputTokens, cacheReadTokens,
  cacheWriteTokens) under its model.

Only numbers, times, model names and working folders are taken, never what was said. This account's
own regular files only, never through a link; files written in the last DAYS days, at most MAX_FILES
per agent and MAX_BYTES each (a zstd file also at most MAX_BYTES once unpacked); lines over MAX_LINE
skipped. What a file gave is kept by (path, size, time) so an unchanged file is not read again.
"""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path

from claude_sessions import Session

HOME = Path.home()
DAYS = 30
MAX_FILES = 2000
MAX_BYTES = 64 * 1024 * 1024
MAX_LINE = 8 * 1024 * 1024
_KEPT: dict = {}              # (reader, path) -> ((size, mtime_ns), Session or None)


def _int(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 10 ** 13 else 0


def _text(value, limit: int = 200) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _files(root: Path, pattern: str, now: float) -> list:
    """This account's own regular files below root matching pattern, written in the last DAYS days,
    newest first, at most MAX_FILES (links are not followed)."""
    found = []
    try:
        candidates = root.glob(pattern)
        for _number, path in zip(range(MAX_FILES * 4), candidates):
            try:
                info = os.lstat(path)
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and now - info.st_mtime <= DAYS * 86400:
                found.append((info.st_mtime, path, info))
    except OSError:
        return []
    found.sort(key=lambda item: -item[0])
    return found[:MAX_FILES]


def _read(path: Path, info) -> bytes:
    """The whole file, opened without following links, if it is still this account's own regular file
    of at most MAX_BYTES."""
    if info.st_size > MAX_BYTES:
        return b""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return b""
    with os.fdopen(fd, "rb") as handle:
        now = os.fstat(handle.fileno())
        if not stat.S_ISREG(now.st_mode) or now.st_uid != os.getuid():
            return b""
        return handle.read(MAX_BYTES + 1)[:MAX_BYTES]


def _unzstd(data: bytes) -> bytes:
    """zstd unpacked, at most MAX_BYTES (more: nothing, not a cut half)."""
    try:
        from compression import zstd
    except ImportError:         # before Python 3.14: no zstd reader
        return b""
    out, rest = [], data
    total = 0
    try:
        while rest:                 # one frame after another: dsh appends a frame per write
            unpacker = zstd.ZstdDecompressor()
            part = unpacker.decompress(rest, max_length=MAX_BYTES + 1 - total)
            total += len(part)
            if total > MAX_BYTES or not unpacker.eof:
                return b""          # too large once unpacked, or a frame cut short
            out.append(part)
            rest = unpacker.unused_data
    except Exception:
        return b""
    return b"".join(out)


def _entries(data: bytes):
    for line in data.split(b"\n"):
        if not line or len(line) > MAX_LINE:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            yield entry


def _epoch(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value / 1000 if value > 1e11 else float(value)           # milliseconds or seconds
    if isinstance(value, str) and len(value) <= 40:
        from datetime import datetime
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _seen(session: Session, when: float | None):
    if when is None:
        return
    session.first = when if not session.first else min(session.first, when)
    session.last = max(session.last, when)


def _add(session: Session, model: str, counts):
    numbers = session.tokens.setdefault(model or "unknown", [0, 0, 0, 0])
    for i, n in enumerate(counts):
        numbers[i] += n


# --- the three forms ------------------------------------------------------------------------------

def _codex(data: bytes) -> Session | None:
    session, model, totals = Session(), "", None
    for entry in _entries(data):
        payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
        kind = entry.get("type")
        _seen(session, _epoch(entry.get("timestamp")))
        if kind == "session_meta":
            session.cwd = _text(payload.get("cwd"), 4096)
        elif kind == "turn_context":
            model = _text(payload.get("model")) or model
        elif kind == "event_msg" and payload.get("type") == "token_count" and isinstance(payload.get("info"), dict):
            usage = payload["info"].get("total_token_usage")
            if isinstance(usage, dict):
                totals = usage
                session.replies += 1
    if totals is None:
        return None
    cached = _int(totals.get("cached_input_tokens"))
    _add(session, model, [max(0, _int(totals.get("input_tokens")) - cached), _int(totals.get("output_tokens")),
                          cached, _int(totals.get("cache_write_input_tokens"))])
    return session


def _pi(data: bytes) -> Session | None:
    session = Session()
    for entry in _entries(data):
        when = _epoch(entry.get("timestamp"))
        if entry.get("type") == "session":
            session.cwd = _text(entry.get("cwd"), 4096)
        message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
        usage = message.get("usage")
        if entry.get("type") != "message" or message.get("role") != "assistant" or not isinstance(usage, dict):
            continue
        _seen(session, when)
        session.replies += 1
        _add(session, _text(message.get("model")), [_int(usage.get("input")), _int(usage.get("output")),
                                                    _int(usage.get("cacheRead")), _int(usage.get("cacheWrite"))])
    return session if session.replies else None


def _dsh(data: bytes) -> Session | None:
    session = Session()
    for entry in _entries(_unzstd(data)):
        body = entry.get("data") if isinstance(entry.get("data"), dict) else {}
        if entry.get("type") == "session":
            session.cwd = _text(body.get("cwd") or body.get("workspace"), 4096)
        usage = body.get("usage")
        if entry.get("type") != "assistant/message" or not isinstance(usage, dict):
            continue
        _seen(session, _epoch(entry.get("time")))
        session.replies += 1
        source = body.get("message", {}).get("source", {}) if isinstance(body.get("message"), dict) else {}
        model = _text(body.get("model")) or (_text(source.get("model")) if isinstance(source, dict) else "")
        _add(session, model, [_int(usage.get("inputTokens")), _int(usage.get("outputTokens")),
                              _int(usage.get("cacheReadTokens")), _int(usage.get("cacheWriteTokens"))])
    return session if session.replies else None


READERS = {                  # the forms adapters name ([sessions] reader): where and how
    "codex-files": (HOME / ".codex/sessions", "*/*/*/rollout-*.jsonl", _codex),
    "pi-files": (HOME / ".pi/agent/sessions", "*/*.jsonl", _pi),
    "dsh-files": (HOME / ".dsh/sessions", "*/session-*/session.v4.jsonl.zstd", _dsh),
}


def collect(form: str, root: Path | None = None, now: float | None = None) -> dict:
    """{session file path: Session} of one form (a READERS key) for the last DAYS days."""
    default_root, pattern, parse = READERS[form]
    now = time.time() if now is None else now
    found = {}
    for _mtime, path, info in _files(root or default_root, pattern, now):
        key, mark = (form, str(path)), (info.st_size, info.st_mtime_ns)
        kept = _KEPT.get(key)
        if kept is not None and kept[0] == mark:
            session = kept[1]
        else:
            try:
                session = parse(_read(path, info))
            except Exception:       # a file in a form this does not know: left out
                session = None
            _KEPT[key] = (mark, session)
        if session is not None:
            found[str(path)] = session
    return found


def codex_files() -> dict:
    return collect("codex-files")


def pi_files() -> dict:
    return collect("pi-files")


def dsh_files() -> dict:
    return collect("dsh-files")
