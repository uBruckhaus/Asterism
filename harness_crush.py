"""Charm's Crush."""

from harnesses import Harness, Mcp, Skills
from i18n import _


def _access():
    from agent_status import Access
    return Access(_("An API key for a provider, or a local LLM from the map"), "crush",
                  (".local/share/crush/crush.json",), ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"), local_ok=True)


HARNESS = Harness("crush", "Crush", label="Crush", icon="\U000f02d1", access=_access,
                  skills=Skills(("~/.config/crush/skills", "~/.config/agents/skills", "~/.agents/skills", "~/.claude/skills"), "~/.config/crush/skills"),
                  mcp=Mcp("~/.config/crush/crush.json", key="mcp", shape="crush"), short_model_flag=True)
