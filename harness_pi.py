"""Pi."""

from harnesses import Harness, Mcp, Skills, ref
from i18n import _


def _access():
    from agent_status import Access
    return Access(_("Sign in inside Pi (/login: Claude, ChatGPT, Copilot …), an API key, or a local LLM from the map"),
                  "pi  →  /login", (".pi/agent/auth.json",), ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"), local_ok=True)


HARNESS = Harness("pi", "Pi", label="Pi", full_name="Pi", icon="\ue901", icon_font="omarchy",
                  security=ref("agent_security", "pi"), usage=ref("agent_status", "pi"), access=_access,
                  local_llm=True,
                  skills=Skills(("~/.pi/agent/skills", "~/.agents/skills"), "~/.pi/agent/skills", settings_list=True),
                  mcp=Mcp("~/.pi/agent/mcp.json"))
