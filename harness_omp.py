"""Oh My Pi."""

from harnesses import Harness, Mcp, Skills


HARNESS = Harness("omp", "Oh My Pi", label="omp", full_name="Oh My Pi", icon="\ue903", icon_font="omarchy",
                  spec="github:can1357/oh-my-pi",
                  skills=Skills(("~/.omp/agent/skills",), "~/.omp/agent/skills"),
                  mcp=Mcp("~/.omp/agent/mcp.json", shape="omp"))
