"""note（二日酔いラボ）監視（judge_note / check_note / main の状態引き継ぎ）のテスト。python3 tests/test_watch_note.py で実行。

旧実装なら赤: watch.py は note を見ておらず、サブPCの日次配信が止まっても誰も気づかなかった（08-09〜10-31 の約12週間 0本）。
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import watch  # noqa: E402

H = 3600
NOW = 1_800_000_000


class JudgeNote(unittest.TestCase):
    def test_ok_when_recent(self):
        self.assertEqual(watch.judge_note(NOW - 5 * H, NOW)[0], "ok")

    def test_stall_when_old(self):
        self.assertEqual(watch.judge_note(NOW - 31 * H, NOW)[0], "stall")

    def test_stall_when_no_posts(self):
        self.assertEqual(watch.judge_note(None, NOW)[0], "stall")


class CheckNote(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.dir)
        self.sent = []
        self.orig_line = watch.line
        self.orig_env = dict(os.environ)
        watch.line = lambda t: self.sent.append(t)
        os.environ.pop("NOTE_WATCH", None)

    def tearDown(self):
        watch.line = self.orig_line
        os.environ.clear()
        os.environ.update(self.orig_env)   # test_disabled の NOTE_WATCH=false を後のテストに漏らさない
        os.chdir(self.cwd)

    def run_check(self, state, fetch):
        if os.path.exists(watch.ALERT_FLAG):
            os.remove(watch.ALERT_FLAG)
        watch.check_note(state, NOW, fetch=fetch)
        return os.path.exists(watch.ALERT_FLAG)

    def test_alert_once_then_recover(self):
        s = {}
        self.assertTrue(self.run_check(s, lambda u: NOW - 40 * H))
        self.assertEqual(s["note"], "stall")
        self.assertFalse(self.run_check(s, lambda u: NOW - 41 * H))  # 継続中は再通知しない
        self.assertEqual(len(self.sent), 1)
        self.assertFalse(self.run_check(s, lambda u: NOW - 1 * H))
        self.assertEqual(s["note"], "ok")
        self.assertIn("再開", self.sent[-1])

    def test_fetch_errors_alert_after_six(self):
        def boom(u):
            raise OSError("timeout")
        s = {}
        for _ in range(watch.NOTE_ERR_ALERT - 1):
            self.assertFalse(self.run_check(s, boom))
        self.assertNotIn("note", s)
        self.assertTrue(self.run_check(s, boom))
        self.assertEqual(s["note"], "stall")
        self.run_check(s, lambda u: NOW - 1 * H)
        self.assertNotIn("note_err", s)

    def test_disabled(self):
        os.environ["NOTE_WATCH"] = "false"
        s = {}
        self.assertFalse(self.run_check(s, lambda u: None))
        self.assertEqual(s, {})

class MainKeepsNoteState(unittest.TestCase):
    """PC停止→復帰で state を作り直しても note の状態が残り、同じ停止を二重通知しない。"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.dir)
        self.sent = []
        self.saved = (watch.line, watch.send_magic, watch.check_note.__defaults__, dict(os.environ))
        watch.line = lambda t: self.sent.append(t)
        watch.send_magic = lambda *a: None
        watch.check_note.__defaults__ = (lambda u: int(__import__("time").time()) - 40 * H,)
        os.environ.update({"HOME_HOST": "x", "WAKE_PORT": "9", "DESKTOP_MAC": "00:11:22:33:44:55"})
        os.environ.pop("NOTE_WATCH", None)
        os.environ.pop("WAKE_ENABLED", None)

    def tearDown(self):
        watch.line, watch.send_magic, watch.check_note.__defaults__, env = self.saved
        os.environ.clear()
        os.environ.update(env)
        os.chdir(self.cwd)

    def run_main(self, age):
        now = int(__import__("time").time())
        os.environ["DESKTOP_LAST_SEEN"] = str(now - age)
        os.environ["OUTREACH_SEEN"] = f"{now}|{now}|0|1|0"
        watch.main()
        with open(watch.STATE, encoding="utf-8") as f:
            return json.load(f)

    def test_down_and_up_keep_note(self):
        self.assertEqual(self.run_main(60).get("note"), "stall")
        s = self.run_main(H)
        self.assertEqual((s["status"], s.get("note")), ("down", "stall"))
        s = self.run_main(60)
        self.assertEqual((s["status"], s.get("note")), ("up", "stall"))
        self.assertEqual(len([m for m in self.sent if "note" in m and "🔴" in m]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
