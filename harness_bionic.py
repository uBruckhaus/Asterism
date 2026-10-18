"""LM Studio Bionic (installed by this app: install_ctl.Bionic)."""

from harnesses import Harness


def _installer():
    import install_ctl
    return install_ctl.Bionic()


HARNESS = Harness("bionic", "LM Studio Bionic", label="LM Studio Bionic", icon="\U000f09d1",
                  installer=_installer, short_version=True, offered=False)
