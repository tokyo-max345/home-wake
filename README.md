# home-wake

自宅の常時ONデスクトップが落ちたら、外から自動で起こす見張り。

- `scripts/heartbeat.ps1` … デスクトップが5分ごとに「生きている」を repo variable `DESKTOP_LAST_SEEN` に書く（家のIPが変われば secret `HOME_HOST` も更新）
- `.github/workflows/watch.yml` … 5分ごとに心拍の古さを見て、12分以上途切れていたら Wake-on-LAN の信号を家のルーターへ送り、LINE で知らせる
- 止める: repo variable `WAKE_ENABLED` を `false`（意図してシャットダウンする時）

secrets: `HOME_HOST` / `WAKE_PORT` / `DESKTOP_MAC` / `NOTIFY_LINE_TOKEN` / `NOTIFY_LINE_TO`
前提: ルーターのポート変換（UDP `WAKE_PORT` → デスクトップ:9）と、デスクトップの高速スタートアップ無効。
