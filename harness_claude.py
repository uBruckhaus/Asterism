"""Claude Code: its sessions from ~/.claude/projects (claude_sessions reads the numbers)."""

import claude_sessions
from harnesses import Harness, Mcp, Sessions, Skills, ref
from i18n import _


def _note() -> str:
    return _("Numbers from Claude Code's session files (no text is read). The API value is what the "
             "tokens would cost at API prices, not what a plan costs.")


def _access():
    from agent_status import Access
    return Access(_("A Claude Pro or Max subscription (claude.ai), or an API key from console.anthropic.com"),
                  "claude auth login", (".claude/.credentials.json",), ("ANTHROPIC_API_KEY",))


HARNESS = Harness("claude", "Claude Code", sessions=Sessions(claude_sessions.collect_by_id, _note),
                  label="Claude", full_name="Claude Code", icon="\U000f06c4",
                  security=ref("agent_security", "claude"), access=_access,
                  skills=Skills(("~/.claude/skills",), "~/.claude/skills"),
                  mcp=Mcp("~/.claude.json", format="claude", shape="claude"),
                  self_update=("claude", "update"), latest=ref("agent_updates", "claude_channel_latest"))
