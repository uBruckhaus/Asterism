import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agent_sessions as a  # noqa: E402

NOW = time.time()

try:
    from compression import zstd
except ImportError:          # before Python 3.14
    zstd = None


def lines(*entries) -> str:
    return "".join(json.dumps(e) + "\n" for e in entries)


class ReadersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        a._KEPT.clear()

    def put(self, rel: str, data):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode())
        return path

    def test_codex_totals_with_cached_input_taken_out(self):
        self.put("2026/10/22/rollout-x.jsonl", lines(
            {"timestamp": "2026-10-22T10:00:00Z", "type": "session_meta", "payload": {"cwd": "/home/u/p"}},
            {"timestamp": "2026-10-22T10:00:01Z", "type": "turn_context", "payload": {"model": "gpt-6-luna"}},
            {"timestamp": "2026-10-22T10:00:05Z", "type": "event_msg", "payload": {"type": "token_count", "info": {
                "total_token_usage": {"input_tokens": 100, "cached_input_tokens": 60, "output_tokens": 7,
                                      "cache_write_input_tokens": 3}}}},
            {"timestamp": "2026-10-22T10:00:09Z", "type": "event_msg", "payload": {"type": "token_count", "info": {
                "total_token_usage": {"input_tokens": 1000, "cached_input_tokens": 600, "output_tokens": 70,
                                      "cache_write_input_tokens": 30}}}}))
        (session,) = a.collect("codex-files", self.root, NOW).values()
        self.assertEqual(session.tokens, {"gpt-6-luna": [400, 70, 600, 30]})    # the last totals only
        self.assertEqual((session.cwd, session.replies), ("/home/u/p", 2))
        self.assertLess(session.first, session.last)

    def test_pi_each_reply_under_its_model(self):
        reply = lambda model, n: {"type": "message", "timestamp": "2026-10-22T10:00:00Z", "message": {
            "role": "assistant", "model": model, "usage": {"input": n, "output": 2, "cacheRead": 3, "cacheWrite": 4},
            "content": [{"type": "text", "text": "never read"}]}}
        self.put("--p--/s.jsonl", lines({"type": "session", "cwd": "/w"}, reply("claude-opus-5-5", 10),
                                        reply("claude-opus-5-5", 5), reply("qwen-local", 1),
                                        {"type": "message", "message": {"role": "user", "content": "hi"}}))
        (session,) = a.collect("pi-files", self.root, NOW).values()
        self.assertEqual(session.tokens, {"claude-opus-5-5": [15, 4, 6, 8], "qwen-local": [1, 2, 3, 4]})
        self.assertEqual(session.cwd, "/w")

    @unittest.skipIf(zstd is None, "needs Python 3.14's compression.zstd")
    def test_dsh_frame_after_frame(self):
        first = lines({"type": "session", "time": 1792000000000, "data": {"cwd": "/w"}})
        reply = lines({"type": "assistant/message", "time": 1792000005000, "data": {
            "model": "deepseek-v4-pro", "usage": {"inputTokens": 10, "outputTokens": 2, "cacheReadTokens": 30}}})
        self.put("--w--/session-1/session.v4.jsonl.zstd", zstd.compress(first.encode()) + zstd.compress(reply.encode()))
        (session,) = a.collect("dsh-files", self.root, NOW).values()
        self.assertEqual(session.tokens, {"deepseek-v4-pro": [10, 2, 30, 0]})
        self.assertEqual(session.last, 1792000005.0)

    @unittest.skipIf(zstd is None, "needs Python 3.14's compression.zstd")
    def test_dsh_too_large_once_unpacked(self):
        bomb = zstd.compress(b" " * (2 * 1024 * 1024))
        with mock.patch.object(a, "MAX_BYTES", 1024 * 1024):
            self.assertEqual(a._unzstd(bomb), b"")
        self.assertEqual(a._unzstd(b"not zstd"), b"")

    def test_links_old_and_large_files_left_out(self):
        outside = self.put("../outside.jsonl", lines({"type": "message", "message": {
            "role": "assistant", "model": "m", "usage": {"input": 1}}}))
        (self.root / "--l--").mkdir()
        os.symlink(outside, self.root / "--l--" / "link.jsonl")
        old = self.put("--o--/old.jsonl", lines({"type": "message", "message": {
            "role": "assistant", "model": "m", "usage": {"input": 1}}}))
        os.utime(old, (NOW - (a.DAYS + 1) * 86400,) * 2)
        self.put("--b--/big.jsonl", "x" * 2048)
        with mock.patch.object(a, "MAX_BYTES", 1024):
            self.assertEqual(a.collect("pi-files", self.root, NOW), {})

    def test_unchanged_file_not_read_again(self):
        path = self.put("--p--/s.jsonl", lines({"type": "message", "timestamp": "2026-10-22T10:00:00Z", "message": {
            "role": "assistant", "model": "m", "usage": {"input": 1}}}))
        a.collect("pi-files", self.root, NOW)
        with mock.patch.object(a, "_read", side_effect=AssertionError("read again")):
            a.collect("pi-files", self.root, NOW)
        path.write_text(path.read_text() * 2)
        (session,) = a.collect("pi-files", self.root, NOW).values()
        self.assertEqual(session.tokens["m"][0], 2)


if __name__ == "__main__":
    unittest.main()
