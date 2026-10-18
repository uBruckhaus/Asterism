"""DeepSeek Harness (installed by this app: install_ctl.Dsh)."""

from harnesses import Harness


def _installer():
    import install_ctl
    return install_ctl.Dsh()


HARNESS = Harness("dsh", "DeepSeek Harness", label="DeepSeek Harness", icon="\U000f0e7b",
                  installer=_installer, offered=False)
