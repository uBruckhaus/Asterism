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


    def test_built_ins_know_whether_the_program_is_here(self):
        from types import SimpleNamespace as NS
        items = {i.id: i for i in page.build_items([], [], [NS(command="opencode", installed=False),
                                                            NS(command="claude", installed=True)],
                                                   [NS(key="ollama", installed=True)])}
        self.assertEqual((items["opencode"].installed, items["opencode"].target), (False, "agent"))
        self.assertTrue(items["claude"].installed)
        self.assertEqual((items["ollama"].installed, items["ollama"].target), (True, "runtime"))
        self.assertEqual(items["anthropic"].target, "")            # online: nothing to install



class UpdateAllTest(unittest.TestCase):
    """Update all: every add-on with a newer catalog version, one toast, a failure named."""

    def fake_app(self, items):
        app = mock.MagicMock()
        app.addons_updating = False
        app.addon_update_items = lambda: items
        app.update_all_addons = lambda: page.AddonsPage.update_all_addons(app)
        app.addons_busy = lambda: page.AddonsPage.addons_busy(app)
        app.run_addon_job = lambda work, done: page.AddonsPage.run_addon_job(app, work, done)
        app.sync_update_bar = lambda: page.AddonsPage.sync_update_bar(app)
        app.addons_items = []
        return app

    def run_sync(self, app):
        with mock.patch.object(page.threading, "Thread",
                               side_effect=lambda target, daemon: mock.Mock(start=target)), \
                mock.patch.object(page.GLib, "idle_add", side_effect=lambda fn, *a: fn(*a)):
            app.update_all_addons()

    def test_updates_each_and_reports_failures(self):
        good = mock.Mock(entry=entry("alpha", "1.1.0"))
        good.name = "Alpha"
        bad = mock.Mock(entry=entry("beta", "1.1.0"))
        bad.name = "Beta"
        app = self.fake_app([good, bad])

        def install(e):
            if e.id == "beta":
                raise addon_store.InstallError("bad signature")
        with mock.patch.object(addon_store, "install", side_effect=install) as installed:
            self.run_sync(app)
        self.assertEqual(installed.call_count, 2)
        message = app.addons_changed.call_args[0][0]
        self.assertIn("Alpha", message)
        self.assertIn("Beta (bad signature)", message)
        self.assertFalse(app.addons_updating)
        app.refresh_overview.assert_called_once()

    def test_nothing_to_update_or_already_running_does_nothing(self):
        with mock.patch.object(addon_store, "install") as installed:
            self.run_sync(self.fake_app([]))
            busy = self.fake_app([mock.Mock(entry=entry("alpha", "1.1.0"))])
            busy.addons_updating = True
            self.run_sync(busy)
        installed.assert_not_called()

    def test_unexpected_error_never_leaves_the_flag_set(self):
        item = mock.Mock(entry=entry("alpha", "1.1.0"))
        item.name = "Alpha"
        app = self.fake_app([item])
        import zipfile
        with mock.patch.object(addon_store, "install", side_effect=zipfile.BadZipFile("CRC")):
            self.run_sync(app)
        self.assertFalse(app.addons_updating)
        self.assertIn("Alpha (CRC)", app.addons_changed.call_args[0][0])
        # A single update while Update all runs is refused, not started twice.
        app.addons_updating = True
        with mock.patch.object(addon_store, "install") as installed:
            page.AddonsPage.update_addon(app, item)
        installed.assert_not_called()


class SetupCardUpdateTest(unittest.TestCase):
    """A Setup card's menu offers Update add-on when the catalog has a newer version."""

    def test_update_entry_only_with_an_update(self):
        import setup_page
        app = mock.MagicMock()
        newer = mock.Mock(id="agent-pi", entry=entry("agent-pi", "0.11.1"))
        app.addon_update_items = lambda: [newer]
        addon = mock.Mock(id="agent-pi")
        entries = setup_page.SetupPage.addon_entries(app, addon)
        self.assertEqual(len(entries), 2)
        entries[0]("popover")
        label, _popover, run = app.menu_item.call_args[0][:3]
        self.assertIn("0.11.1", label)
        run()
        app.update_addon.assert_called_once_with(newer)
        app.addon_update_items = lambda: []
        self.assertEqual(len(setup_page.SetupPage.addon_entries(app, addon)), 1)


if __name__ == "__main__":
    unittest.main()
