"""A local LLM and an agent the app has never heard of, each as a signed add-on and nothing else:
both appear and work everywhere the built-in ones do (map, connect, models, folders, security,
disk space), with no change in the core. This is the promise of the provider engines and adapters:
a new provider or agent is one add-on."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import addon_api  # noqa: E402
import addons  # noqa: E402
import harnesses  # noqa: E402
import providers  # noqa: E402

LLM_META = {"api": 1, "privacy": "numbers", "needs": f"asterism >= {addons.ASTERISM_VERSION}", "id": "llm-example",
            "name": "Example LLM", "version": "1.0.0", "kind": "provider", "capabilities": ["provider"],
            "provides": ["examplellm"], "reads": ["its model folder"], "summary": "A made-up local LLM"}
LLM_SOURCE = '''
import os
from pathlib import Path

import llm_engine
from providers import Provider


def _detect(processes):
    import inventory
    names = sorted(p.stem for p in Path(os.path.expanduser("~/models")).glob("*.gguf"))
    return inventory.Runtime("examplellm", "Example LLM", installed=True, running=False, service="example-llm",
                             address="127.0.0.1:9123", models_dir="~/models", models=names)


class Engine(llm_engine.Engine):
    programs = ("example-server",)
    start_command = "example-server --models <folder>"
    ports = (9123,)
    gguf_folder = True
    reorganize = True
    download = "file"
    removable = "file"
    context_settable = True
    context_effect = "restart"

    def models_page_note(self, rt):
        return "Example LLM reads every GGUF file in its folder."


PROVIDER = Provider("examplellm", "Example LLM", "local", detect=_detect, engine=Engine(),
                    connect_key="example-local", connect_label="Example LLM (local)",
                    data=("~/.example-llm",))


def register(api):
    api.add_provider(PROVIDER)
'''

AGENT_META = {"api": 1, "privacy": "numbers", "needs": f"asterism >= {addons.ASTERISM_VERSION}",
              "id": "agent-exampleagent", "name": "Example Agent", "version": "1.0.0", "kind": "agent",
              "capabilities": ["agent"], "harnesses": ["exampleagent"], "provides": ["exampleagent"],
              "reads": ["its own settings"], "summary": "A made-up coding agent"}
AGENT_TOML = '''
command = "exampleagent"
name = "Example Agent"
icon = "U+F06C4"
data = ["~/.exampleagent"]
home = "~/.exampleagent"
activity = ["~/.exampleagent/sessions"]
web_search = true

[details]
hook = true

[local_llm]
files = ["~/.exampleagent/config.json"]
hooks = true

[mcp]
path = "~/.exampleagent/config.json"
format = "json"
key = "mcpServers"

[research]
argv = ["exampleagent", "ask", "--web-only", "{prompt}"]

[security]
file = "~/.exampleagent/config.json"
format = "json"
asks = "permissions.ask"

[[security.settings]]
key = "permissions.ask"
title = "Before commands"
explain = "Whether it asks before it runs a command."
default = "always"
recommended = "always"
choices = [
  { value = "always", label = "Ask", explain = "Asks every time.", risk = 0 },
  { value = "never", label = "Never ask", explain = "Runs them at once.", risk = 3 },
]
'''
AGENT_HOOKS = '''
import json


def _json(text):
    try:
        data = json.loads(text) if text.strip() else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def details(details):
    import agent_details as ad
    config = ad.read_json(ad._expand("~/.exampleagent/config.json"))
    details.model = str(config.get("model") or "")
    for name, entry in (config.get("providers") or {}).items():
        details.providers.append(ad.provider_for_url(name, entry.get("url"), len(entry.get("models", [])),
                                                     active=name == config.get("provider")))


def local_llm_connected(texts, provider):
    return provider in _json(texts[0]).get("providers", {})


def local_llm_active(texts, provider):
    return _json(texts[0]).get("provider") == provider


def local_llm_transform(texts, provider, label, url, models, context, model, use_now, remove):
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
    return [json.dumps(data, indent=2) + "\\n"]
'''


@unittest.skipUnless(shutil.which("ssh-keygen"), "needs OpenSSH's ssh-keygen")
class NewAddonEndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        key = tmp / "key"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "t", "-f", str(key)], check=True)
        cls.signers = f'{addons.PRINCIPAL} namespaces="{addons.NAMESPACE}" ' + \
            " ".join(key.with_suffix(".pub").read_text().split()[:2])
        cls.out = tmp / "addons"
        llm = cls.out / "llm-example"
        llm.mkdir(parents=True)
        (llm / "addon.json").write_text(json.dumps(LLM_META))
        (llm / "addon.py").write_text(LLM_SOURCE)
        agent = cls.out / "agent-exampleagent"
        agent.mkdir()
        (agent / "addon.json").write_text(json.dumps(AGENT_META))
        (agent / "agent.toml").write_text(AGENT_TOML)
        (agent / "hooks.py").write_text(AGENT_HOOKS)
        for folder in (llm, agent):
            names = sorted(str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file())
            (folder / "MANIFEST.sha256").write_text("".join(
                f"{hashlib.sha256((folder / n).read_bytes()).hexdigest()}  {n}\n" for n in names))
            subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", str(key), "-n", addons.NAMESPACE,
                            str(folder / "MANIFEST.sha256")], check=True, capture_output=True)
            (folder / "MANIFEST.sha256.sig").rename(folder / "SIGNATURE")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        home = Path(self.home.name)
        (home / "models").mkdir()
        (home / "models/tiny-coder-Q4_K_M.gguf").write_bytes(b"GGUF" + b"\0" * 60)
        (home / ".exampleagent/sessions").mkdir(parents=True)
        (home / ".exampleagent/config.json").write_text(json.dumps({
            "permissions": {"ask": "never"},
            "mcpServers": {"files": {"command": "npx", "args": ["-y", "some-mcp-server"]}}}))
        import agent_details
        import agent_security
        import connect
        import disk_usage
        import inventory
        import mcp_ctl
        import skills_ctl
        patches = [mock.patch.dict(os.environ, {"HOME": str(home)})]
        patches += [mock.patch.object(m, "HOME", home) for m in (agent_details, agent_security, connect, disk_usage,
                                                                inventory, mcp_ctl, skills_ctl)
                    if hasattr(m, "HOME")]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        found = addons.load_all({"llm-example", "agent-exampleagent"}, dirs=(self.out,), signers=self.signers,
                                hooks=addon_api.Hooks())
        self.addCleanup(addons.load_all, set(), dirs=(), hooks=addon_api.Hooks())
        self.assertEqual({a.id: a.state for a in found},
                         {"llm-example": "loaded", "agent-exampleagent": "loaded"})

    def agent(self):
        import agents
        h = harnesses.get("exampleagent")
        return agents.Agent(h.command, h.name, h.icon, installed=True, version="1.0")

    def test_the_local_llm_is_known_by_its_engine_alone(self):
        import agent_details
        import llm_engine
        import model_folders
        import model_move
        import runtime_ctl
        provider = providers.get("examplellm")
        self.assertIsNotNone(provider)
        engine = llm_engine.of("examplellm")
        self.assertEqual(type(engine).__name__, "Engine")
        self.assertIsNot(type(engine), llm_engine.Engine)
        self.assertEqual(llm_engine.layout("examplellm"), "flat")
        self.assertTrue(model_folders.reads_gguf("examplellm"))
        self.assertTrue(model_move.movable("examplellm"))
        self.assertEqual(agent_details.local_ports()[9123], "Example LLM")
        rt = provider.detect([])
        self.assertEqual(rt.models, ["tiny-coder-Q4_K_M"])
        self.assertTrue(runtime_ctl.can_control(rt))
        self.assertEqual(engine.models_page_note(rt), "Example LLM reads every GGUF file in its folder.")

    def test_the_agent_is_known_by_its_adapter_alone(self):
        import agent_details
        import agent_profiles
        import agent_security
        import mcp_ctl
        h = harnesses.get("exampleagent")
        self.assertEqual((h.home, h.web_search, h.research[0]), ("~/.exampleagent", True, "exampleagent"))
        self.assertEqual(agent_details.details_for("exampleagent").config_dir, "~/.exampleagent")
        self.assertEqual(list(mcp_ctl.raw_entries("exampleagent")), ["files"])
        report = agent_security.report_for("exampleagent")
        self.assertEqual(report.risks[0].title, "Runs commands without asking")
        self.assertEqual(report.risks[0].fix_key, "permissions.ask")
        with mock.patch.object(agent_profiles.shutil, "which", lambda c: f"/bin/{c}"):
            self.assertIn("exampleagent", agent_profiles.researchers({"exampleagent"}))
            self.assertEqual(agent_profiles.research_command("exampleagent", "Q", Path("/s"))[1:],
                             ["ask", "--web-only", "Q"])

    def test_connect_then_the_map_draws_the_line(self):
        import agent_details
        import connect
        import graph
        import inventory
        rt = providers.get("examplellm").detect([])
        plan = connect.plan("exampleagent", rt, "tiny-coder-Q4_K_M", use_now=True)
        self.assertEqual(len(plan.changes), 1)
        connect.apply(plan, backup_root=Path(self.home.name) / "backups")
        self.assertTrue(connect.is_connected("exampleagent", "examplellm"))
        details = agent_details.details_for("exampleagent")
        self.assertEqual([(p.name, p.local, p.runtime) for p in details.providers],
                         [("example-local", True, "Example LLM")])
        agent = self.agent()
        inv = inventory.collect([agent])
        rt = next(r for r in inv.runtimes if r.key == "examplellm")
        self.assertEqual(rt.agents, ["exampleagent"])
        self.assertIn("exampleagent", next(s for s in inv.mcp if s.name == "files").agents)
        built = graph.build([agent], {"exampleagent": details}, inv)
        ids = {n.id for n in built.nodes}
        self.assertTrue({"agent:exampleagent", "runtime:examplellm"} <= ids)
        self.assertTrue(any(e.source == "agent:exampleagent" and e.target == "runtime:examplellm"
                            for e in built.edges))

    def test_disk_space_counts_its_folders(self):
        import disk_usage
        items = disk_usage.agent_items([self.agent()])
        self.assertEqual([(p.kind, p.path.name) for p in items[0].places if p.kind == "data"],
                         [("data", ".exampleagent")])


if __name__ == "__main__":
    unittest.main()
