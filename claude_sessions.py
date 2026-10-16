"""Claude Code's work per project, as numbers only: tokens, working time, sessions, lines
changed and cost, from its session files (~/.claude/projects/<project>/<session>.jsonl).

Only two kinds of line are parsed, and only their numbers are kept:
- a model reply ("type":"assistant"): model name, token counts, time, the project folder (cwd);
- a session's cost summary ("type":"cost-state"): lines added/removed, cost, API and tool time.
No message text, title or prompt is read into the results or shown.

Reading is bounded and incremental: own regular files only (no symlinks), at most MAX_LINE bytes
per line (longer lines are skipped), MAX_FILES files, MAX_BYTES per run; each file is read on from
where the last run stopped (same inode, grown). The results are cached owner-only in CACHE.
"""

import json
import os
import re
import stat
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"
CACHE = Path.home() / ".cache/ai-agents-map/claude-sessions.json"
MAX_LINE = 8 * 1024 * 1024
MAX_FILES = 5000
MAX_DIRS = 500
MAX_BYTES = 2 * 1024 ** 3          # per run; the rest is read next time
MAX_CACHE = 16 * 1024 * 1024
GAP = 5 * 60                       # replies further apart than this are separate stretches of work
CACHE_VERSION = 1
_MODEL = re.compile(r"[A-Za-z0-9._:/-]{1,100}")
_ASSISTANT = b'"type":"assistant"'
_COST = b'"type":"cost-state"'


@dataclass
class Session:
    cwd: str = ""
    first: float = 0.0             # first and last reply (epoch seconds)
    last: float = 0.0
    active: float = 0.0            # seconds: gaps between replies up to GAP
    replies: int = 0
    tokens: dict = field(default_factory=dict)      # model -> [input, output, cache read, cache write]
    hours: dict = field(default_factory=dict)       # "weekday*24+hour" -> replies
    lines_added: int = 0
    lines_removed: int = 0
    cost: float = 0.0
    api_ms: int = 0


def _epoch(stamp) -> float | None:
    if not isinstance(stamp, str) or len(stamp) > 40:
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _number(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 10 ** 13 else 0


def add_reply(session: Session, entry: dict):
    """One model reply: its model, tokens, time and project folder (nothing else)."""
    message = entry.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("usage"), dict):
        return
    usage = message["usage"]
    model = message.get("model")
    model = model if isinstance(model, str) and _MODEL.fullmatch(model) else "unknown"
    counts = session.tokens.setdefault(model, [0, 0, 0, 0])
    for i, key in enumerate(("input_tokens", "output_tokens", "cache_read_input_tokens",
                             "cache_creation_input_tokens")):
        counts[i] += _number(usage.get(key))
    cwd = entry.get("cwd")
    if not session.cwd and isinstance(cwd, str) and cwd.startswith("/") and len(cwd) <= 1024 \
            and not any(ord(c) < 32 for c in cwd):
        session.cwd = cwd
    when = _epoch(entry.get("timestamp"))
    session.replies += 1
    if when is None:
        return
    if session.last and 0 < when - session.last <= GAP:
        session.active += when - session.last
    session.first = min(session.first, when) if session.first else when
    session.last = max(session.last, when)
    local = time.localtime(when)
    slot = str(local.tm_wday * 24 + local.tm_hour)
    session.hours[slot] = session.hours.get(slot, 0) + 1


def add_cost(session: Session, entry: dict):
    """A session's cost summary: lines changed, cost and API time (the latest one counts)."""
    session.lines_added = _number(entry.get("totalLinesAdded"))
    session.lines_removed = _number(entry.get("totalLinesRemoved"))
    cost = entry.get("totalCostUSD")
    session.cost = float(cost) if isinstance(cost, (int, float)) and 0 <= cost < 10 ** 7 else 0.0
    session.api_ms = _number(entry.get("totalAPIDuration"))


def _session_from(data) -> Session | None:
    if not isinstance(data, dict):
        return None
    try:
        s = Session(**{k: data[k] for k in Session.__dataclass_fields__ if k in data})
    except TypeError:
        return None
    if not isinstance(s.tokens, dict) or not isinstance(s.hours, dict) or not isinstance(s.cwd, str):
        return None
    return s


def read_file(path: Path, state: dict, budget: int) -> int:
    """Read path on from state["offset"] into state["sessions"]; returns the bytes read."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return 0
    with os.fdopen(fd, "rb") as handle:
        st = os.fstat(handle.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
            return 0
        if state.get("inode") != st.st_ino or st.st_size < state.get("offset", 0):
            state.clear()                       # a new or rewritten file: from the start
        state["inode"] = st.st_ino
        sessions = state.setdefault("sessions", {})
        offset = state.get("offset", 0)
        handle.seek(offset)
        read = 0
        while read < budget:
            line = handle.readline(MAX_LINE + 1)
            if not line:
                break
            if not line.endswith(b"\n"):
                if len(line) <= MAX_LINE:
                    break                       # a line still being written: read it next time
                # Longer than MAX_LINE: skip to its end and keep nothing of it.
                skipped, done = len(line), False
                while True:
                    more = handle.readline(MAX_LINE + 1)
                    if not more:
                        break                   # still being written: the next run starts at it again
                    skipped += len(more)
                    if more.endswith(b"\n"):
                        done = True
                        break
                if not done:
                    break
                read += skipped
                offset += skipped
                continue
            read += len(line)
            offset += len(line)
            if _ASSISTANT not in line and _COST not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict) or entry.get("type") not in ("assistant", "cost-state"):
                continue
            sid = entry.get("sessionId")
            sid = sid if isinstance(sid, str) and re.fullmatch(r"[A-Za-z0-9-]{1,64}", sid) else "?"
            data = sessions.get(sid)
            session = data if isinstance(data, Session) else (_session_from(data) or Session())
            sessions[sid] = session
            if entry["type"] == "assistant":
                add_reply(session, entry)
            else:
                add_cost(session, entry)
        state["offset"] = offset
        return read


def _load_cache(cache: Path) -> dict:
    try:
        fd = os.open(cache, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as handle:
            if os.fstat(handle.fileno()).st_uid != os.getuid():
                return {}
            data = json.loads(handle.read(MAX_CACHE + 1)[:MAX_CACHE] or b"{}")
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION or not isinstance(data.get("files"), dict):
        return {}
    return data["files"]


def _save_cache(files: dict, cache: Path):
    import ai_core
    plain = {path: {"inode": s.get("inode"), "offset": s.get("offset", 0),
                    "sessions": {sid: asdict(x) if isinstance(x, Session) else x
                                 for sid, x in s.get("sessions", {}).items()}}
             for path, s in files.items()}
    try:
        ai_core.atomic_write(cache, json.dumps({"version": CACHE_VERSION, "files": plain}))
    except OSError:
        pass


def collect(root: Path = ROOT, cache: Path = CACHE) -> list[Session]:
    """Every session's numbers (incremental, bounded; blocking: run it on a thread)."""
    files = _load_cache(cache)
    seen, budget = {}, MAX_BYTES
    try:
        dirs = sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink())[:MAX_DIRS]
    except OSError:
        dirs = []
    paths = []
    for folder in dirs:
        try:
            paths += sorted(folder.glob("*.jsonl"))
        except OSError:
            continue
        if len(paths) >= MAX_FILES:
            break
    for path in paths[:MAX_FILES]:
        key = str(path)
        state = files.get(key) if isinstance(files.get(key), dict) else {}
        if budget > 0:
            budget -= read_file(path, state, budget)
        seen[key] = state
    _save_cache(seen, cache)
    sessions = []
    for state in seen.values():
        for data in state.get("sessions", {}).values():
            session = data if isinstance(data, Session) else _session_from(data)
            if session is not None and session.replies:
                sessions.append(session)
    return sessions


# --- what the details page shows ------------------------------------------------------------------

@dataclass
class Project:
    cwd: str
    sessions: int = 0
    active: float = 0.0
    tokens: int = 0                # input + output + cache write (cache reads are counted apart)
    cache_read: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    cost: float = 0.0
    last: float = 0.0


def projects(sessions: list[Session], since: float = 0.0) -> list[Project]:
    """Per project folder, the sessions last active since `since`, busiest first."""
    found: dict[str, Project] = {}
    for s in sessions:
        if s.last < since:
            continue
        p = found.setdefault(s.cwd or "?", Project(s.cwd or "?"))
        p.sessions += 1
        p.active += s.active
        for counts in s.tokens.values():
            p.tokens += counts[0] + counts[1] + counts[3]
            p.cache_read += counts[2]
        p.lines_added += s.lines_added
        p.lines_removed += s.lines_removed
        p.cost += s.cost
        p.last = max(p.last, s.last)
    return sorted(found.values(), key=lambda p: (-p.active, -p.tokens))


def busiest(sessions: list[Session], since: float = 0.0) -> tuple[int, int] | None:
    """(weekday 0=Monday, hour) with the most replies since `since`, or None."""
    totals: dict[int, int] = {}
    for s in sessions:
        if s.last < since:
            continue
        for slot, n in s.hours.items():
            if str(slot).isdigit() and isinstance(n, int):
                totals[int(slot)] = totals.get(int(slot), 0) + n
    if not totals:
        return None
    slot = max(totals, key=totals.get)
    return slot // 24, slot % 24
