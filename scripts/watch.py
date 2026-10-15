"""自宅デスクトップ(DESKTOP-C2HHAFO)の見張り。GitHub Actions から5分ごとに呼ばれる。

- デスクトップは5分ごとに repo variable DESKTOP_LAST_SEEN（UNIX秒）を更新している（heartbeat.ps1）
- それが DOWN_AFTER 秒より古ければ「落ちている」とみなし、家のルーターのポート変換経由で
  Wake-on-LAN のマジックパケットを送る（起きているPCに届いても何も起きない＝誤検知でも無害）
- 状態が変わった時だけ LINE で知らせ、state.json を commit する（通知の重複防止）

止めたい時は repo variable WAKE_ENABLED を false にする（意図してシャットダウンする時など）。
"""
import json
import os
import socket
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
STATE = "state.json"
DOWN_AFTER = 12 * 60        # 心拍5分＋Actionsの遅れ。これより古ければ落ちている
STILL_DOWN_AFTER = 60 * 60  # 起動信号を送り続けても戻らない時の2通目
KEEPALIVE_DAYS = 30         # 60日無活動で schedule が止まる GitHub の仕様への備え


def env(name, required=True):
    v = os.environ.get(name, "").strip()
    if required and not v:
        sys.exit(f"::error::{name} が未設定")
    return v


def hhmm(ts):
    return datetime.fromtimestamp(ts, JST).strftime("%m/%d %H:%M")


def send_magic(host, port, mac):
    raw = bytes.fromhex(mac.replace("-", "").replace(":", ""))
    if len(raw) != 6:
        sys.exit("::error::DESKTOP_MAC の形式が不正")
    packet = b"\xff" * 6 + raw * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        for _ in range(3):
            s.sendto(packet, (host, port))
            time.sleep(0.3)


def line(text):
    token, to = env("NOTIFY_LINE_TOKEN", False), env("NOTIFY_LINE_TO", False)
    if not token or not to:
        print("::warning::LINE の secret が無いので通知しない")
        return
    body = json.dumps({"to": to, "messages": [{"type": "text", "text": text}]}).encode()
    req = urllib.request.Request("https://api.line.me/v2/bot/message/push", data=body, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            print(f"LINE {r.status} request-id={r.headers.get('x-line-request-id')}")
    except urllib.error.HTTPError as e:  # 黙って捨てない: 本文ごと出して job を赤くする
        print(f"::error::LINE {e.code} {e.read().decode(errors='replace')}")
        raise


OUTREACH_DOWN_AFTER = 2 * 60 * 60  # 営業ロボの応答が途絶えて「止まっている」とみなすまで
ALERT_FLAG = "alert.flag"          # 新しく異常になった回だけ作る → 最後のステップがジョブを赤くする（GitHub の失敗メール）


def judge_outreach(seen, now):
    """営業ロボ（outreach-engine）の状態を返す: ("ok"|"down"|"stall"|"unknown", 説明)。

    seen = repo variable OUTREACH_SEEN "<確認時刻>|<最終送信>|<停止判定0/1>|<今日の送信数>|<送信待ち>"
    デスクトップ（Windows）が生きていても、WSL・Docker・ロボ本体が死んでいる／送信が止まっている状態は
    心拍だけでは見えない（09-18〜24 WSL 破損で5.5日、09-29〜10-14 設定の文字化けで16日、誰も気づかなかった）。
    """
    if not seen:
        return "unknown", "OUTREACH_SEEN がまだ無い"
    parts = seen.split("|")
    if len(parts) != 5 or not all(p.lstrip("-").isdigit() for p in parts):
        return "unknown", f"OUTREACH_SEEN の形式が不正: {seen[:60]}"
    seen_at, last_sent, stalled, sent_today, live = (int(p) for p in parts)
    if now - seen_at > OUTREACH_DOWN_AFTER:
        return "down", f"営業ロボが {hhmm(seen_at)} から応答しません（PCは起動中）"
    if stalled:
        last = hhmm(last_sent) if last_sent else "なし"
        return "stall", f"営業メールの自動送信が止まっています（最後の送信 {last}・送信待ち {live}件）"
    jst = datetime.fromtimestamp(now, JST)
    if jst.weekday() < 5 and jst.hour >= 15 and sent_today == 0 and live > 0:
        return "stall", f"平日15時を過ぎても今日の送信が0通です（送信待ち {live}件）"
    return "ok", ""


def check_outreach(state, now):
    status, why = judge_outreach(env("OUTREACH_SEEN", False), now)
    print(f"営業ロボ: {status} {why}")
    if status == "unknown":
        # 監視データが無い・壊れている＝監視そのものが効いていない。黙って見逃さず異常として扱う
        status, why = "down", f"営業ロボの監視データが読めません（{why}）。送信PCの home-wake-heartbeat を確認"
    prev = state.get("outreach", "ok")
    if status != "ok" and prev == "ok":
        state["outreach"] = status
        state["outreach_since"] = now
        # 先に旗を立てる: LINE が枠切れ(429)でも GitHub の失敗メールで必ず届く
        with open(ALERT_FLAG, "w", encoding="utf-8") as f:
            f.write(why + "\n")
        try:
            line(f"🔴 {why}\n→ 送信PCで docker と crawler のログを確認してください。")
        except Exception as e:  # noqa: BLE001 — 本文は line() が ::error で出している。状態は保存して二重通知しない
            print(f"::warning::LINE 通知失敗（GitHub の失敗メールで代替）: {e}")
    elif status == "ok" and prev != "ok":
        mins = (now - state.get("outreach_since", now)) // 60
        state["outreach"] = "ok"
        state.pop("outreach_since", None)
        line(f"✅ 営業ロボが復帰しました（異常だった時間 約{mins}分）。")
    elif status != "ok" and status != prev:
        state["outreach"] = status  # down⇔stall の切替は記録だけ（通知は最初の1回）


def main():
    now = int(time.time())
    if env("WAKE_ENABLED", False).lower() == "false":
        print("WAKE_ENABLED=false のため何もしない")
        return
    last = env("DESKTOP_LAST_SEEN", False)
    if not last.isdigit():
        sys.exit("::error::DESKTOP_LAST_SEEN が無い（heartbeat.ps1 が一度も動いていない）")
    last = int(last)
    age = now - last

    state = {"status": "up", "since": now}
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            state = json.load(f)
    before = json.dumps(state, sort_keys=True)

    down = age > DOWN_AFTER
    print(f"最終心拍 {hhmm(last)}（{age // 60}分前） → {'DOWN' if down else 'UP'} / 前回 {state['status']}")

    if down:
        send_magic(env("HOME_HOST"), int(env("WAKE_PORT")), env("DESKTOP_MAC"))
        print("起動信号を送信")
        if state["status"] != "down":
            state = {"status": "down", "since": now, "last_seen": last, "still_notified": False}
            line(f"🖥 デスクトップが応答なし（最後の応答 {hhmm(last)}）。起動信号を送りました。5分ごとに送り続けます。")
        elif not state.get("still_notified") and now - state["since"] > STILL_DOWN_AFTER:
            state["still_notified"] = True
            line(f"🖥 デスクトップが {hhmm(state['since'])} から起きません。起動信号では戻らない状態です"
                 "（コンセント・電源ボタン・ルーターを確認）。")
    elif state["status"] == "down":
        mins = (now - state.get("last_seen", state["since"])) // 60
        state = {"status": "up", "since": now}
        line(f"✅ デスクトップが復帰しました（止まっていた時間 約{mins}分）。")

    if not down:
        check_outreach(state, now)

    if json.dumps(state, sort_keys=True) != before:
        state["updated"] = now
    elif now - state.get("updated", 0) > KEEPALIVE_DAYS * 86400:
        state["updated"] = now  # 無変化でも月1回 commit して schedule の自動停止を防ぐ
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
        f.write("\n")


if __name__ == "__main__":
    main()
