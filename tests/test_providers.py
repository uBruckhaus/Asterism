import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import connect  # noqa: E402
import graph  # noqa: E402
import install_ctl  # noqa: E402
import provider_watch  # noqa: E402
import providers  # noqa: E402


class RegistryTest(unittest.TestCase):
    def test_keys_unique_and_kinds(self):
        keys = [p.key for p in providers.all_providers()]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(p.kind == "local" for p in providers.local()))
        self.assertTrue(all(p.kind == "online" for p in providers.online()))
        self.assertEqual(providers.get("ollama").name, "Ollama")
        self.assertIsNone(providers.get("nope"))

    def test_every_local_provider_is_complete(self):
        for p in providers.local():
            self.assertTrue(callable(p.detect), p.key)
            self.assertTrue(callable(p.installer), p.key)
            self.assertTrue(p.connect_key.endswith("-local"), p.key)
            self.assertEqual(p.connect_label, f"{p.name} (local)")
            self.assertEqual(p.detect.__module__, f"provider_{p.key}")


class SameTablesAsBeforeTest(unittest.TestCase):
    """The tables built from the registry are exactly the ones the modules had written out."""

    def test_connect(self):
        self.assertEqual(connect.KEYS, {"llamacpp": "llama-local", "ollama": "ollama-local",
                                        "lmstudio": "lmstudio-local", "vllm": "vllm-local", "jan": "jan-local",
                                        "koboldcpp": "koboldcpp-local"})
        self.assertEqual(connect.LABELS, {"llamacpp": "llama.cpp (local)", "ollama": "Ollama (local)",
                                          "lmstudio": "LM Studio (local)", "vllm": "vLLM (local)",
                                          "jan": "Jan (local)", "koboldcpp": "KoboldCpp (local)"})

    def test_graph(self):
        self.assertEqual(graph.CLOUD, {
            "claude": "Anthropic", "codex": "OpenAI", "copilot": "GitHub Copilot", "cursor-agent": "Cursor",
            "gemini": "Google", "grok": "xAI", "muse": "Meta", "openclaw": "OpenClaw"})
        self.assertEqual(graph.PROVIDER_NAMES, {
            "anthropic": "Anthropic", "openai": "OpenAI", "openai-codex": "OpenAI", "google": "Google",
            "gemini": "Google", "github-copilot": "GitHub Copilot", "xai": "xAI", "nous": "Nous Research",
            "openrouter": "OpenRouter", "groq": "Groq", "mistral": "Mistral", "deepseek": "DeepSeek",
            "fireworks": "Fireworks", "together": "Together AI", "opencode": "OpenCode Zen", "zai": "Z.ai"})

    def test_installers(self):
        self.assertEqual({k: type(v).__name__ for k, v in install_ctl.INSTALLERS.items()}, {
            "ollama": "Ollama", "llamacpp": "LlamaCpp", "lmstudio": "LmStudio", "vllm": "Vllm", "jan": "Jan",
            "koboldcpp": "KoboldCpp"})
        for key, inst in install_ctl.INSTALLERS.items():
            self.assertEqual(inst.key, key)


class WatcherCopyTest(unittest.TestCase):
    """provider_watch.py runs isolated (stdlib only) with its own copy of these facts."""

    def test_same_as_registry(self):
        self.assertEqual(provider_watch.RUNTIMES, tuple(p.key for p in providers.local()))
        self.assertEqual(provider_watch.STAYS_UP, {p.key for p in providers.local() if p.stays_up})
        self.assertEqual(provider_watch.UNLOADS, {p.key: p.unload for p in providers.local() if p.unload})


if __name__ == "__main__":
    unittest.main()
