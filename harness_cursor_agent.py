"""Cursor CLI."""

from harnesses import Harness, Mcp, Skills, ref
from i18n import _


def _access():
    from agent_status import Access
    return Access(_("A Cursor account (cursor.com)"), "cursor-agent login",
                  (".config/cursor/auth.json",), ("CURSOR_API_KEY",))


HARNESS = Harness("cursor-agent", "Cursor CLI", label="Cursor CLI", icon="\ue90d", icon_font="omarchy",
                  security=ref("agent_security", "cursor"), access=_access,
                  login_status=(("cursor-agent", "status"), "not logged in", "logged in"),
                  skills=Skills(("~/.cursor/skills", "~/.agents/skills", "~/.claude/skills", "~/.codex/skills"), "~/.cursor/skills"),
                  mcp=Mcp("~/.cursor/mcp.json"))
