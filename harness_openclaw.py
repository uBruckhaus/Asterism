"""OpenClaw (the openclaw pacman package)."""

from harnesses import Harness, Mcp, Skills


HARNESS = Harness("openclaw", "OpenClaw", label="OpenClaw", icon="\ue90c", icon_font="omarchy",
                  package="openclaw", package_only=True,
                  skills=Skills(("~/.openclaw/skills", "~/.agents/skills"), "~/.openclaw/skills"),
                  mcp=Mcp("~/.openclaw/openclaw.json", format="openclaw", key="mcp.servers", shape="openclaw"))
