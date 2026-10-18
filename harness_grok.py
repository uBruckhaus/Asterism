"""xAI's Grok CLI."""

from harnesses import Harness, Mcp, Skills
from i18n import _


def _access():
    from agent_status import Access
    return Access(_("An API key from console.x.ai"), "grok", (), ("XAI_API_KEY",))


HARNESS = Harness("grok", "Grok", label="Grok", icon="\ue904", icon_font="omarchy",
                  spec="npm:@xai-official/grok", access=_access,
                  skills=Skills(("~/.grok/skills",), "~/.grok/skills"),
                  mcp=Mcp("~/.grok/config.toml", format="toml", key="mcp_servers"))
