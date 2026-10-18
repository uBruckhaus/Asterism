import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import claude_sessions as cs  # noqa: E402
import session_topics as st  # noqa: E402


class TopicsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "projects"
        (self.root / "p").mkdir(parents=True)
        self.file = self.root / "p" / "s.jsonl"
        self.cache = Path(self.tmp.name) / "titles.json"

    def write(self, *entries):
        self.file.write_text("".join(json.dumps(e) + "\n" for e in entries))

    def test_titles_only_from_title_lines_and_plain(self):
        self.write({"type": "user", "sessionId": "s1", "message": {"content": '{"type":"ai-title","aiTitle":"fake"}'}},
                   {"type": "ai-title", "sessionId": "s1", "aiTitle": "Fix the <b>map</b>\n\x1b[31m"},
                   {"type": "ai-title", "sessionId": "../x", "aiTitle": "bad id"})
        titles = st.collect_titles(self.root, self.cache)
        self.assertEqual(list(titles), ["s1"])            # not the fake one inside a user message, not "../x"
        self.assertTrue(titles["s1"].startswith("Fix the <b>map</b>"))   # shown as plain text, never markup
        self.assertFalse(any(not c.isprintable() for c in titles["s1"]))
        self.assertEqual(self.cache.stat().st_mode & 0o777, 0o600)

    def test_long_titles_are_cut(self):
        self.assertEqual(len(st.clean_title("x" * 1000)), st.MAX_TITLE)

    def test_summary_text_has_titles_and_numbers_only(self):
        now = time.time()
        sessions = {"s1": cs.Session(cwd="/home/u/p", last=now, active=600, replies=3, tokens={"m": [1, 2, 3, 4]})}
        text = st.summary_text(sessions, {"s1": "Fix the map"}, now - 86400)
        self.assertIn("Fix the map", text)
        self.assertIn("10 min", text)
        self.assertLessEqual(len(st.summary_text({f"s{i}": sessions["s1"] for i in range(5000)}, {}, 0)),
                             st.MAX_SUMMARY_INPUT)

    def test_run_summary_is_locked_down(self):
        with mock.patch.object(st.shutil, "which", return_value="/usr/bin/claude"), \
                mock.patch.object(st.ai_core, "read_bounded_output", return_value=(b"Mostly \x1b[1mmaps\x00.", True)) as run:
            ok, answer = st.run_summary("titles")
        argv = run.call_args[0][0]
        for flag in ("-p", "--permission-mode", "plan", "--strict-mcp-config", "--no-session-persistence"):
            self.assertIn(flag, argv)
        self.assertEqual(run.call_args[1]["stdin"], b"titles")
        self.assertTrue(ok)
        self.assertNotIn("\x1b", answer)
        self.assertNotIn("\x00", answer)



class DatabaseTitlesTest(unittest.TestCase):
    """OpenCode's and Hermes's own titles: top-level sessions only, as plain text."""

    def setUp(self):
        import sqlite3
        import test_harnesses as th
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.opencode, self.hermes = Path(tmp.name) / "opencode.db", Path(tmp.name) / "state.db"
        th.opencode_db(self.opencode)
        th.hermes_db(self.hermes)
        db = sqlite3.connect(self.opencode)
        db.execute("UPDATE session_v2 SET title = ? WHERE id = 'c'", ("bad\x1b[31m title",))
        db.commit()
        db.close()

    def test_titles(self):
        self.assertEqual(st.opencode_titles(self.opencode), {"a": "Fix the parser", "c": "bad [31m title"})
        self.assertEqual(st.hermes_titles(self.hermes), {"h1": "Deploy"})
        self.assertEqual(st.opencode_titles(self.opencode.with_name("none.db")), {})

    def test_summary_names_the_harness(self):
        import harness_hermes
        sessions = harness_hermes.collect(self.hermes)
        text = st.summary_text(sessions, st.hermes_titles(self.hermes), 0, "Hermes")
        self.assertIn("my Hermes sessions", text)
        self.assertIn("Deploy", text)


if __name__ == "__main__":
    unittest.main()
