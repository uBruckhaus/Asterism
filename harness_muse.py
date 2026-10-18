"""Meta's Muse Code."""

from harnesses import Harness


HARNESS = Harness("muse", "Muse Code", label="Muse Code", icon="\U000f06e4",
                  spec="http:muse[url=https://api.meta.ai/muse-launcher.sh,bin=muse]")
