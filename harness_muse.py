"""Meta's Muse Code."""

from harnesses import Harness, Mcp, Skills


HARNESS = Harness("muse", "Muse Code", label="Muse Code", icon="\U000f06e4",
                  spec="http:muse[url=https://api.meta.ai/muse-launcher.sh,bin=muse]",
                  skills=Skills(("~/.config/muse/skills", "~/.agents/skills", "~/.claude/skills", "~/.codex/skills"), "~/.config/muse/skills"),
                  mcp=Mcp("~/.config/muse/settings.json", key="mcp_servers", shape="muse"))
