# home-wake progress

## セッションログ（2026-09-24 nightos/progress.md から移設・新しい順）

### 2026-09-23 [デスクトップが落ちたら外から自動で起こす見張り home-wake] 進行中 ／ 検証commit:5e455c8(home-wake) ／ 実測:疑似DOWN→LINE 200(run 35805085939)→心拍復帰→復帰LINE 200(run 35805131980)
- 公開repo `tokyo-max345/home-wake`（Actions無料のためpublic・値はsecrets）。デスクトップが5分毎に心拍（repo variable）→Actions 5分毎に判定→途切れたらWoL送信+LINE。家のIP変化は心拍側が secret を更新
- デスクトップの高速スタートアップを無効化（シャットダウン後もWoLを受けるため）
- ✅ルーター WSR-5400AX6 設定（Claudeがssh経由HTTPで実施）: ポート変換 UDP 44539→192.168.11.7:9 ＋ DHCP手動割当。実測: 外部回線から送った信号がデスクトップNICに着弾（pktmon）
- 残: シャットダウン→外部WoLで実際に起きるかの試験（電源OFF中のARP忘れが最大の関門・失敗時は電源ボタンが要る）
- 詳細=[[reference_home_wake_desktop_watchdog]]
- 保存(09-24): 新leaf [[feedback_fast_startup_shutdown_logged_as_sleep]]（高速スタートアップのシャットダウンを「スリープ」と誤報告した件）＋index_scripting に2行（同leaf／tar日本語名化け）。MEMORY.md は上限すれすれ（25,581/25,600B）＝次の追記前に退避が要る
- 次にやること: まこつの了承を得てシャットダウン→外部WoLの実起動テスト（最大20分で自動復帰＋LINE「復帰」が合格条件）
- [トークン概算: 入力約120k/出力約30k — SSH越しの実測・ルーターHTMLの読解・Actions実走]

