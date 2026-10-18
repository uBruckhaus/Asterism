"""OpenAI's Codex CLI."""

from harnesses import Harness, Mcp, Skills, ref
from i18n import _


def _access():
    from agent_status import Access
    return Access(_("A ChatGPT plan (Plus, Pro, Business), or an API key from platform.openai.com"),
                  "codex login", (".codex/auth.json",), ("OPENAI_API_KEY",), local_ok=True)


HARNESS = Harness("codex", "Codex", label="Codex", icon="\ue905", icon_font="omarchy",
                  security=ref("agent_security", "codex"), access=_access,
                  skills=Skills(("~/.agents/skills", "~/.codex/skills"), "~/.codex/skills"),
                  mcp=Mcp("~/.codex/config.toml", format="toml", key="mcp_servers", shape="codex"),
                  short_model_flag=True)
