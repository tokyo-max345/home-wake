"""営業ロボ監視（judge_outreach / check_outreach）のテスト。python3 tests/test_watch_outreach.py で実行。

旧実装なら赤: watch.py はデスクトップの心拍しか見ず、Windows が生きていて WSL/ロボが死んでいる・
送信が止まっている状態を外から検知できなかった。
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import watch  # noqa: E402

JST = timezone(timedelta(hours=9))


def ts(y, mo, d, h, mi=0):
    return int(datetime(y, mo, d, h, mi, tzinfo=JST).timestamp())


class JudgeOutreach(unittest.TestCase):
    def test_ok(self):
        now = ts(2026, 10, 16, 11)  # 木曜
        s, _ = watch.judge_outreach(f"{now - 300}|{now - 600}|0|12|400", now)
        self.assertEqual(s, "ok")

    def test_down_when_seen_is_old(self):
        now = ts(2026, 10, 16, 11)
        s, why = watch.judge_outreach(f"{now - 3 * 3600}|{now - 4 * 3600}|0|5|400", now)
        self.assertEqual(s, "down")
        self.assertIn("応答しません", why)

    def test_stall_flag_from_robot(self):
        now = ts(2026, 10, 16, 11)
        s, why = watch.judge_outreach(f"{now - 60}|{now - 5 * 86400}|1|0|400", now)
        self.assertEqual(s, "stall")
        self.assertIn("送信待ち 400件", why)

    def test_weekday_afternoon_zero_sends(self):
        now = ts(2026, 10, 16, 15, 5)  # 木曜 15:05
        s, _ = watch.judge_outreach(f"{now - 60}|{now - 86400}|0|0|400", now)
        self.assertEqual(s, "stall")

    def test_weekend_or_morning_or_empty_stock_is_ok(self):
        sat = ts(2026, 10, 17, 16)
        self.assertEqual(watch.judge_outreach(f"{sat - 60}|{sat - 86400}|0|0|400", sat)[0], "ok")
        morning = ts(2026, 10, 16, 9)
        self.assertEqual(watch.judge_outreach(f"{morning - 60}|{morning - 86400}|0|0|400", morning)[0], "ok")
        empty = ts(2026, 10, 16, 16)
        self.assertEqual(watch.judge_outreach(f"{empty - 60}|{empty - 86400}|0|0|0", empty)[0], "ok")

    def test_unknown_on_missing_or_broken(self):
        now = ts(2026, 10, 16, 11)
        self.assertEqual(watch.judge_outreach("", now)[0], "unknown")
        self.assertEqual(watch.judge_outreach("1|2|3", now)[0], "unknown")


class CheckOutreachTransitions(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.dir)
        self.sent = []
        watch.line = lambda text: self.sent.append(text)

    def tearDown(self):
        os.chdir(self.cwd)

    def run_with(self, seen, now, state):
        os.environ["OUTREACH_SEEN"] = seen
        watch.check_outreach(state, now)
        return state

    def test_alert_once_then_recover(self):
        now = ts(2026, 10, 16, 11)
        st = {"status": "up", "since": 0}
        self.run_with(f"{now - 3 * 3600}|0|0|0|1", now, st)
        self.assertEqual(st["outreach"], "down")
        self.assertTrue(os.path.exists(watch.ALERT_FLAG), "新しい異常でジョブを赤くする旗")
        self.assertEqual(len(self.sent), 1)
        os.remove(watch.ALERT_FLAG)
        # 続いている間は再通知しない・旗も立てない
        self.run_with(f"{now - 4 * 3600}|0|0|0|1", now + 3600, st)
        self.assertEqual(len(self.sent), 1)
        self.assertFalse(os.path.exists(watch.ALERT_FLAG))
        # 復帰で1回
        self.run_with(f"{now + 7200}|{now + 7000}|0|3|1", now + 7300, st)
        self.assertEqual(st["outreach"], "ok")
        self.assertEqual(len(self.sent), 2)
        self.assertIn("復帰", self.sent[1])
        json.dumps(st)  # state.json に保存できる

    def test_missing_or_broken_seen_is_alerted_not_ignored(self):
        now = ts(2026, 10, 16, 11)
        st = {"status": "up", "since": 0}
        self.run_with("", now, st)
        self.assertEqual(st["outreach"], "down")
        self.assertTrue(os.path.exists(watch.ALERT_FLAG))
        self.assertIn("監視データが読めません", self.sent[0])

    def test_line_failure_still_raises_flag_and_saves_state(self):
        def boom(_):
            raise RuntimeError("LINE 429")
        watch.line = boom
        now = ts(2026, 10, 16, 11)
        st = {"status": "up", "since": 0}
        self.run_with(f"{now - 3 * 3600}|0|0|0|1", now, st)
        self.assertEqual(st["outreach"], "down")
        self.assertTrue(os.path.exists(watch.ALERT_FLAG))


if __name__ == "__main__":
    unittest.main(verbosity=1)
