"""GitHub Copilot CLI."""

from harnesses import Harness, Mcp, Skills, ref
from i18n import _


def _access():
    from agent_status import Access
    return Access(_("A GitHub Copilot subscription (github.com/features/copilot)"),
                  "copilot  →  /login", (".copilot/config.json",), ("COPILOT_GITHUB_TOKEN", "GH_TOKEN"))


HARNESS = Harness("copilot", "GitHub Copilot", label="Copilot", full_name="GitHub Copilot", icon="\uf4b8",
                  security=ref("agent_security", "copilot"), access=_access,
                  skills=Skills(("~/.copilot/skills", "~/.agents/skills"), "~/.copilot/skills"),
                  mcp=Mcp("~/.copilot/mcp-config.json", shape="copilot"))
