"""Google's Gemini CLI."""

from harnesses import Harness, Mcp, Skills, Way
from i18n import _


def _access():
    from agent_status import Access
    return Access(_("A Google account (free tier), or an API key from aistudio.google.com"),
                  "gemini", (".gemini/oauth_creds.json",), ("GEMINI_API_KEY", "GOOGLE_API_KEY"))


HARNESS = Harness("gemini", "Gemini CLI", label="Gemini", full_name="Gemini CLI", icon="\U000f0ae2",
                  access=_access,
                  skills=Skills(("~/.gemini/skills", "~/.agents/skills"), "~/.gemini/skills"),
                  mcp=Mcp("~/.gemini/settings.json", shape="gemini"),
                  install=(Way("mise", spec="gemini"),),
                  data=("~/.gemini",),
                  homepage="https://github.com/google-gemini/gemini-cli")
