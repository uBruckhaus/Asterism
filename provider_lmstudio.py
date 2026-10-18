"""LM Studio: LM Studio's server (lms) and its models folder."""

from providers import Provider


def _detect(processes):
    import inventory
    return inventory.lmstudio(processes)


def _installer():
    import install_ctl
    return install_ctl.LmStudio()


PROVIDER = Provider("lmstudio", "LM Studio", "local", detect=_detect, installer=_installer,
                    connect_key="lmstudio-local", connect_label="LM Studio (local)")
