"""DeepSeek Harness (installed by this app: install_ctl.Dsh)."""

from harnesses import Harness, Mcp, Skills
from i18n import _


def _installer():
    import install_ctl
    return install_ctl.Dsh()


def _access():
    from agent_status import Access
    return Access(_("An API key from platform.deepseek.com, or a local LLM from the map"),
                  "dsh web", (".dsh/.credentials.yaml",), ("DEEPSEEK_API_KEY",), local_ok=True)


HARNESS = Harness("dsh", "DeepSeek Harness", label="DeepSeek Harness", icon="\U000f0e7b",
                  installer=_installer, offered=False, access=_access, local_llm=True,
                  skills=Skills(("~/.dsh/skills", "~/.agents/skills"), "~/.dsh/skills"),
                  mcp=Mcp("~/.dsh/profiles/web/cordis.patch.yml", format="dsh", key="", shape="dsh"))
