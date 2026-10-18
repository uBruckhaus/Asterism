"""Ollama: the ollama service and its model store."""

from providers import Provider


def _detect(processes):
    import inventory
    return inventory.ollama(processes)


def _installer():
    import install_ctl
    return install_ctl.Ollama()


PROVIDER = Provider("ollama", "Ollama", "local", detect=_detect, installer=_installer,
                    connect_key="ollama-local", connect_label="Ollama (local)")
