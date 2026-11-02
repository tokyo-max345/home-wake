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

    def test_alternate_pace_waits_four_days(self):
        # 在庫切れ後の隔日配信（直近2本が48時間おき）なら、金→月の72時間空きでは鳴らさない
        self.assertEqual(watch.judge_note(NOW - 72 * H, NOW, NOW - 120 * H)[0], "ok")
        self.assertEqual(watch.judge_note(NOW - 97 * H, NOW, NOW - 145 * H)[0], "stall")

    def test_daily_pace_keeps_30h(self):
        # 毎日配信（直近2本が24時間おき）は従来どおり30時間で鳴らす
        self.assertEqual(watch.judge_note(NOW - 31 * H, NOW, NOW - 55 * H)[0], "stall")


class CheckNoteTuple(unittest.TestCase):
    def test_tuple_fetch_uses_previous(self):
        s = {}
        orig = watch.line
        watch.line = lambda t: None
        d, cwd = tempfile.mkdtemp(), os.getcwd()
        os.chdir(d)
        try:
            watch.check_note(s, NOW, fetch=lambda u: (NOW - 72 * H, NOW - 120 * H))
            self.assertNotIn("note", s)
            self.assertNotIn("note_err", s)  # 旧実装はタプルで例外→取得失敗扱いになっていた
        finally:
            watch.line = orig
            os.chdir(cwd)


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
        # 見張る note は NOTE_TARGETS の数だけ。どれも40時間止まり＝アカウントごとに1回ずつ（二重通知なし）
        self.assertEqual(len([m for m in self.sent if "note" in m and "🔴" in m]), len(watch.NOTE_TARGETS))
        self.assertEqual(s.get("note_nightbiz"), "stall")


class NightbizTarget(unittest.TestCase):
    """ナイトビジネスラボ（nightbiz_lab）を2つ目の見張り先として足した（11-03）。旧実装は futsukayoi_com しか見ていなかった。"""
    T = next(t for t in watch.NOTE_TARGETS if t["user"] == "nightbiz_lab")

    def setUp(self):
        self.dir, self.cwd = tempfile.mkdtemp(), os.getcwd()
        os.chdir(self.dir)
        self.sent, self.orig_line, self.orig_env = [], watch.line, dict(os.environ)
        watch.line = lambda t: self.sent.append(t)
        os.environ.pop("NOTE_WATCH", None)

    def tearDown(self):
        watch.line = self.orig_line
        os.environ.clear()
        os.environ.update(self.orig_env)
        os.chdir(self.cwd)

    def test_36h_threshold(self):
        # 1本目（手動 04:35）→次の定時（翌日13〜14時）の約33時間では鳴らさない・1回取りこぼしたら鳴る
        self.assertEqual(watch.judge_note(NOW - 33 * H, NOW, None, self.T)[0], "ok")
        self.assertEqual(watch.judge_note(NOW - 37 * H, NOW, NOW - 61 * H, self.T)[0], "stall")
        # 二日酔いラボの30時間は変えない
        self.assertEqual(watch.judge_note(NOW - 31 * H, NOW)[0], "stall")

    def test_separate_state_and_message(self):
        s = {}
        asked = []
        def fetch(u):
            asked.append(u)
            return NOW - 40 * H
        watch.check_note(s, NOW, self.T, fetch=fetch)
        self.assertEqual(asked, ["nightbiz_lab"])
        self.assertEqual(s.get("note_nightbiz"), "stall")
        self.assertNotIn("note", s)               # 二日酔いラボの状態に混ざらない
        self.assertIn("ナイトビジネスラボ", self.sent[0])
        self.assertIn("nightbiz-note-*.log", self.sent[0])
        # 取得失敗の回数も別に数える
        def boom(u):
            raise OSError("x")
        watch.check_note(s, NOW, self.T, fetch=boom)
        self.assertEqual((s.get("note_nightbiz_err"), s.get("note_err")), (1, None))

    def test_two_alerts_same_run_both_kept_in_flag(self):
        # 同じ回に2アカウントとも止まったら、失敗メールに載る旗に2件とも残る（旧実装は後の1件で上書き＝Codex 11-03 指摘）
        s = {}
        for t in watch.NOTE_TARGETS:
            watch.check_note(s, NOW, t, fetch=lambda u: NOW - 100 * H)
        with open(watch.ALERT_FLAG, encoding="utf-8") as f:
            lines = [l for l in f.read().splitlines() if l]
        self.assertEqual(len(lines), len(watch.NOTE_TARGETS))
        self.assertTrue(any("二日酔いラボ" in l for l in lines) and any("ナイトビジネスラボ" in l for l in lines))

    def test_keys_survive_pc_restart(self):
        # main は "note" で始まるキーだけを PC 停止・復帰をまたいで引き継ぐ
        self.assertTrue(all(t["key"].startswith("note") for t in watch.NOTE_TARGETS))


if __name__ == "__main__":
    unittest.main(verbosity=1)
