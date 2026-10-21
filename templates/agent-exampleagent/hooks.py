"""Example Agent's hooks (agent.toml): what its facts cannot say. Each function has a fixed name
(adapter_data.HOOKS) and is used where agent.toml says "hook" (or hooks = true). An agent whose
settings a reader of the app knows needs no hooks.py at all."""

import json


def _json(text):
    try:
        data = json.loads(text) if text.strip() else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def details(details):
    """Its model and providers (agent_details.Details), from its own settings."""
    import agent_details as ad
    config = ad.read_json(ad._expand("~/.exampleagent/config.json"))
    details.model = str(config.get("model") or "")
    for name, entry in (config.get("providers") or {}).items():
        details.providers.append(ad.provider_for_url(name, entry.get("url"), len(entry.get("models", [])),
                                                     active=name == config.get("provider")))


# Connecting it to a local LLM on the map: texts are the files of [local_llm] files, in order.

def local_llm_connected(texts, provider):
    return provider in _json(texts[0]).get("providers", {})


def local_llm_active(texts, provider):
    return _json(texts[0]).get("provider") == provider


def local_llm_transform(texts, provider, label, url, models, context, model, use_now, remove):
    """The files' new texts (the app shows them first, keeps a backup and offers Undo)."""
    data = _json(texts[0])
    found = data.setdefault("providers", {})
    if remove:
        found.pop(provider, None)
        if data.get("provider") == provider:
            data.pop("provider", None)
            data.pop("model", None)
    else:
        found[provider] = {"name": label, "url": url, "models": list(models)}
        if use_now and model:
            data["provider"], data["model"] = provider, model
    return [json.dumps(data, indent=2) + "\n"]
