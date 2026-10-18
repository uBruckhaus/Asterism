"""Asterism only (not in the AI Agents Map plugin): a harness's sessions under their own titles,
and a written summary of the last 30 days by Claude itself (edition.TITLES and edition.SUMMARY).

- Titles: the titles each harness gave its sessions itself, read by TITLES[command]:
  Claude Code's "type":"ai-title" lines in its session files (only those lines are parsed, bounded
  and incremental like claude_sessions, cached owner-only); OpenCode's and Hermes's title column
  (read-only, the id and title columns only). Shown as plain text.
- Summarize: on a click, the titles and numbers (never the conversations) go to the user's own
  `claude -p`, after a preview of exactly that text. Claude runs in plan mode (no changes, no
  commands), without MCP servers, without saving a session, in an empty temporary folder, with the
  text on stdin and a bounded answer.

ai_popup calls fill(app, body, harness, sessions_by_id, since) when this module can be imported.
"""

import json
import os
import re
import shutil
import stat
import tempfile
import threading
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

import ai_core  # noqa: E402
import claude_sessions  # noqa: E402
import harness_hermes  # noqa: E402
import harness_opencode  # noqa: E402
import harnesses  # noqa: E402
import inventory  # noqa: E402
from i18n import _, ngettext  # noqa: E402

CACHE = claude_sessions.CACHE.with_name("claude-titles.json")
MAX_TITLE = 120
MAX_SUMMARY_INPUT = 24 * 1024
MAX_ANSWER = 64 * 1024
TIMEOUT = 180
_TITLE = b'"ai-title"'          # a quick pre-filter; json decides
_SID = re.compile(r"[A-Za-z0-9-]{1,64}")


def clean_title(text) -> str:
    """A title as plain text: no control characters, at most MAX_TITLE characters."""
    if not isinstance(text, str):
        return ""
    text = "".join(c if c.isprintable() else " " for c in text).strip()
    return text[:MAX_TITLE]


def read_titles(path: Path, state: dict, budget: int) -> int:
    """The ai-title lines of a session file from state["offset"] on into state["titles"]."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return 0
    with os.fdopen(fd, "rb") as handle:
        st = os.fstat(handle.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
            return 0
        if state.get("inode") != st.st_ino or st.st_size < state.get("offset", 0):
            state.clear()
        state["inode"] = st.st_ino
        titles = state.setdefault("titles", {})
        offset = state.get("offset", 0)
        handle.seek(offset)
        read = 0
        while read < budget:
            line = handle.readline(claude_sessions.MAX_LINE + 1)
            if not line or not line.endswith(b"\n"):
                if line and len(line) > claude_sessions.MAX_LINE:
                    # Too long: skip it whole, or stop where it is still being written.
                    skipped = len(line)
                    while line and not line.endswith(b"\n"):
                        line = handle.readline(claude_sessions.MAX_LINE + 1)
                        skipped += len(line)
                    if not line:
                        break
                    read += skipped
                    offset += skipped
                    continue
                break
            read += len(line)
            offset += len(line)
            if _TITLE not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and entry.get("type") == "ai-title" and \
                    isinstance(entry.get("sessionId"), str) and _SID.fullmatch(entry["sessionId"]):
                title = clean_title(entry.get("aiTitle"))
                if title:
                    titles[entry["sessionId"]] = title
        state["offset"] = offset
        return read


def collect_titles(root: Path = claude_sessions.ROOT, cache: Path = CACHE) -> dict:
    """{session id: title} (incremental, bounded; blocking)."""
    try:
        fd = os.open(cache, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as handle:
            files = json.loads(handle.read(claude_sessions.MAX_CACHE + 1)[:claude_sessions.MAX_CACHE] or b"{}")
    except (OSError, ValueError):
        files = {}
    files = files if isinstance(files, dict) else {}
    seen, budget = {}, claude_sessions.MAX_BYTES
    try:
        dirs = sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink())[:claude_sessions.MAX_DIRS]
    except OSError:
        dirs = []
    paths = [path for folder in dirs for path in sorted(folder.glob("*.jsonl"))][:claude_sessions.MAX_FILES]
    for path in paths:
        state = files.get(str(path)) if isinstance(files.get(str(path)), dict) else {}
        if not isinstance(state.get("titles", {}), dict):
            state = {}
        if budget > 0:
            budget -= read_titles(path, state, budget)
        seen[str(path)] = state
    try:
        ai_core.atomic_write(cache, json.dumps(seen))
    except OSError:
        pass
    return {sid: clean_title(t) for state in seen.values() for sid, t in state.get("titles", {}).items()
            if isinstance(sid, str) and clean_title(t)}


def _db_titles(db_path: Path, sql: str) -> dict:
    db = harnesses.connect(db_path)
    if db is None:
        return {}
    try:
        rows = db.execute(sql, (harnesses.MAX_SESSIONS,)).fetchall()
    except Exception:
        return {}
    finally:
        db.close()
    return {str(sid): clean_title(title) for sid, title in rows if clean_title(title)}


def opencode_titles(db_path: Path = harness_opencode.DB) -> dict:
    return _db_titles(db_path, "SELECT id, title FROM session_v2 WHERE parent_id IS NULL AND title IS NOT NULL"
                               " ORDER BY time_created DESC LIMIT ?")


def hermes_titles(db_path: Path = harness_hermes.DB) -> dict:
    return _db_titles(db_path, "SELECT id, title FROM sessions WHERE parent_session_id IS NULL"
                               " AND title IS NOT NULL ORDER BY started_at DESC LIMIT ?")


TITLES = {"claude": lambda: collect_titles(), "opencode": lambda: opencode_titles(),
          "hermes": lambda: hermes_titles()}


def summary_text(sessions: dict, titles: dict, since: float, name: str = "Claude Code") -> str:
    """What Summarize sends: per project, its sessions' titles with time and tokens. No conversation."""
    from datetime import datetime
    lines = [f"Below are my {name} sessions of the last 30 days: project folder, then each session's "
             f"title (as {name} named it), date, working time and tokens. Summarize in a few short "
             "paragraphs what I mainly worked on, which topics took the most time and tokens, and anything "
             "worth noticing. Plain text, no headings."]
    by_project: dict[str, list] = {}
    for sid, s in sessions.items():
        if s.last >= since:
            by_project.setdefault(s.cwd or "?", []).append((sid, s))
    for cwd, items in sorted(by_project.items(), key=lambda kv: -sum(s.active for _sid, s in kv[1])):
        lines.append("")
        lines.append(f"Project {inventory.tilde(cwd)}:")
        for sid, s in sorted(items, key=lambda item: -item[1].last):
            tokens = sum(c[0] + c[1] + c[3] for c in s.tokens.values())
            day = datetime.fromtimestamp(s.last).strftime("%Y-%m-%d")
            lines.append(f"- {titles.get(sid, 'untitled')} ({day}, {round(s.active / 60)} min, {tokens} tokens)")
    text = "\n".join(lines)
    return text[:MAX_SUMMARY_INPUT]


def run_summary(text: str) -> tuple[bool, str]:
    """Claude's summary of `text` (blocking): (ok, answer or error)."""
    claude = shutil.which("claude")
    if claude is None:
        return False, _("Claude Code is not installed.")
    with tempfile.TemporaryDirectory(prefix="asterism-summary-") as empty:
        out, ok = ai_core.read_bounded_output(
            [claude, "-p", "--output-format", "text", "--permission-mode", "plan", "--strict-mcp-config",
             "--no-session-persistence"],
            max_bytes=MAX_ANSWER, timeout=TIMEOUT, stdin=text.encode("utf-8"), cwd=empty)
    answer = out.decode("utf-8", "replace").strip()
    answer = "".join(c if c.isprintable() or c in "\n\t" else " " for c in answer)
    return (ok and bool(answer)), (answer or _("No answer from Claude Code."))


# --- the details page ------------------------------------------------------------------------------

def short_number(n: int) -> str:
    for size, unit in ((10 ** 9, "B"), (10 ** 6, "M"), (10 ** 3, "k")):
        if n >= size:
            return f"{n / size:.1f}{unit}".replace(".0", "")
    return str(n)


def fill(app, body, harness, sessions: dict, since: float):
    """Under the projects: each project's sessions by title, and Summarize."""
    reader = TITLES.get(harness.command)
    if reader is None:
        return
    titles_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    body.append(titles_box)

    def work():
        try:
            titles = reader()
        except Exception:
            titles = {}
        GLib.idle_add(done, titles)

    def done(titles):
        if titles_box.get_parent() is None:
            return False                    # the page was left
        show(titles_box, app, sessions, titles, since, harness.name)
        return False

    threading.Thread(target=work, daemon=True).start()


def show(box, app, sessions: dict, titles: dict, since: float, name: str = "Claude Code"):
    recent = {sid: s for sid, s in sessions.items() if s.last >= since}
    if not recent:
        return
    app.settings_heading(box, _("Topics, last 30 days"))
    listbox = app.boxed_list()
    by_project: dict[str, list] = {}
    for sid, s in recent.items():
        by_project.setdefault(s.cwd or "?", []).append((sid, s))
    for cwd, items in sorted(by_project.items(), key=lambda kv: -sum(s.active for _sid, s in kv[1]))[:10]:
        expander = Adw.ExpanderRow(title=inventory.tilde(cwd) if cwd != "?" else _("Unknown folder"),
                                   subtitle=ngettext("1 session", "{0} sessions", len(items)).format(len(items)),
                                   use_markup=False)
        for sid, s in sorted(items, key=lambda item: -item[1].last)[:30]:
            tokens = sum(c[0] + c[1] + c[3] for c in s.tokens.values())
            row = app.plain_row(titles.get(sid) or _("Untitled session"),
                                " · ".join([app.duration_text(s.active),
                                            _("{0} tokens").format(short_number(tokens))]))
            expander.add_row(row)
        listbox.append(expander)
    box.append(listbox)

    if shutil.which("claude") is None:
        return                              # Summarize runs the user's own Claude Code
    result = Gtk.Label(xalign=0, wrap=True, selectable=True, visible=False)
    result.add_css_class("card")
    result.add_css_class("am-summary")
    summarize = Gtk.Button(label=_("Summarize with Claude…"), halign=Gtk.Align.START)
    summarize.set_tooltip_text(_("Sends the titles and numbers above (no conversations) to Claude Code and "
                                 "shows what it writes. Uses some tokens."))
    summarize.connect("clicked", lambda *_a: ask(app, summarize, result, summary_text(recent, titles, since, name)))
    box.append(summarize)
    box.append(result)


def ask(app, button, result, text: str):
    """Show exactly what would be sent; Claude only runs on Send."""
    dialog = Adw.AlertDialog(heading=_("Send this to Claude Code?"),
                             body=_("Only these titles and numbers go to Claude, not your conversations."))
    preview = Gtk.TextView(editable=False, cursor_visible=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
    preview.get_buffer().set_text(text)
    scroller = Gtk.ScrolledWindow(min_content_height=240, max_content_height=420, propagate_natural_height=True)
    scroller.set_child(preview)
    dialog.set_extra_child(scroller)
    dialog.add_response("cancel", _("Cancel"))
    dialog.add_response("send", _("Send"))
    dialog.set_response_appearance("send", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("cancel")

    def answered(_dialog, response):
        if response != "send":
            return
        button.set_sensitive(False)
        result.set_visible(True)
        result.set_label(_("Claude is writing…"))

        def work():
            ok, answer = run_summary(text)
            GLib.idle_add(finished, answer)

        def finished(answer):
            button.set_sensitive(True)
            result.set_label(answer)        # a Gtk.Label: plain text, never markup
            return False
        threading.Thread(target=work, daemon=True).start()
    dialog.connect("response", answered)
    dialog.present(app.window)
