import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import addon_store  # noqa: E402
import addons  # noqa: E402
import addons_page as page  # noqa: E402


def entry(aid, version="1.0.0", kind="feature", **kw):
    return addon_store.Entry(aid, aid.title(), version, kind=kind, summary=f"{aid} summary", url="u", size=1,
                             sha256="0" * 64, **kw)


class ItemsTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(addon_store, "present", side_effect=lambda e: e.id == "kilo")
        patcher.start()
        self.addCleanup(patcher.stop)

    def items(self, installed, entries):
        return {i.id: i for i in page.build_items(installed, entries)}

    def test_sections_and_states(self):
        on = addons.Addon(Path("/x/insights"), id="insights", name="Insights", version="1.0.0", state="loaded",
                          privacy=3)
        off = addons.Addon(Path("/x/demo"), id="demo", name="Demo", version="2.0.0", state="verified")
        bad = addons.Addon(Path("/x/broken"), id="broken", state="refused", reason="insights.py was changed")
        items = self.items([on, off, bad], [entry("insights", "1.1.0"), entry("kilo", kind="agent"), entry("other")])
        self.assertEqual(items["insights"].state, "on")
        self.assertTrue(items["insights"].update)
        self.assertEqual(items["insights"].summary, "insights summary")
        self.assertEqual(items["demo"].state, "off")
        self.assertFalse(items["demo"].update)
        self.assertEqual((items["broken"].state, items["broken"].reason), ("failed", "insights.py was changed"))
        self.assertEqual(items["kilo"].state, "suggested")
        self.assertEqual(items["other"].state, "available")
        self.assertEqual(items["claude"].state, "builtin")
        self.assertEqual(items["ollama"].kind, "provider")
        self.assertEqual(items["anthropic"].state, "builtin")

    def test_filters_and_search(self):
        items = page.build_items([], [entry("kilo", kind="agent")])
        kilo = next(i for i in items if i.id == "kilo")
        claude = next(i for i in items if i.id == "claude")
        self.assertTrue(page.visible(kilo, "agent", ""))
        self.assertFalse(page.visible(kilo, "provider", ""))
        self.assertFalse(page.visible(claude, "installed", ""))
        self.assertTrue(page.visible(claude, "all", "claude"))
        self.assertFalse(page.visible(claude, "all", "ollama"))
        self.assertTrue(page.visible(kilo, "all", "kilo summary"))


if __name__ == "__main__":
    unittest.main()
