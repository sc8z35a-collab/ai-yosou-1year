# Agent F — 環境整備（総合）＋コーディング
## 起動プロンプト（このエージェントのセッションに貼る）
> あなたは FLAT TRAIL 制作チームのエージェントF（環境整備（総合）＋コーディング）です。リポジトリ https://github.com/sc8z35a-collab/Flat-trail-26.10.1 の
> ブランチ genspark_ai_developer を /home/user/webapp に clone し、collab/README.md → TIPS.md →
> TROUBLESHOOTING.md → INTERFACES.md → agents/F.md の順に読んで作業してください。
> 開発者から、現状使える全ツール・ハーネス・便利機能の共有と、制作のためのあらゆる手段の自由行使を明示的に許可されています。
> 5〜10分ごとにcommit&push（scripts/autosave.sh 併用）。連絡は collab/CHAT.md に追記。

## 担当
環境構築・全体整備・緊急アラート・全体整理・環境監視（メモリ/CPU/プロセス/push失敗）・巡回（定期的にpull→構文チェック→コンソールエラー検査）・高度な知的監視（設計逸脱・性能劣化・ライセンス違反の検知）。audio.js（WebAudio合成アンビエント）・perf.js（動的画質）。

## 成果物
scripts/autosave.sh, scripts/monitor.sh, scripts/patrol.sh, collab/ALERTS.md, site/js/audio.js, site/js/perf.js

## 作業ログ（追記）
- [08:30] F枠を実エージェントが取得。autosave.sh v2（pull --rebase + 追記型ファイルは両残し/他はリモート優先）、audio.js 全面改修（石造ホールIR、ピアノ/FMベル、靴音、finale、ミュート永続化、iOSアンロック）、perf.js（GPU判定、PROFILES、DPR上限1.5、ピンポン防止、?debug HUD、?q= 固定）。
- [08:30] scripts/patrol.py（静的知的監視）、scripts/monitor.sh（環境監視）、site/selftest.html + js/selftest.js（ランタイム巡回）、favicon。
- [08:48] audio: per-room mood (news.js 参照), phone EQ, footstep heel。Offlineレンダ検証 (/tmp/arender.py 手法を TROUBLESHOOTING に記載)。
- [09:08] museum_f.js（museum.js フォールバック）+ site/f_preview.html。
- [09:21] 新C が museum_f.js を正式採用（museum.js は re-export）。patrol 修正。残タスク: (1) E: 章タイトルとカードの重なり (2) museum_f: アトリウムの大窓の白飛び調整、展示室ごとに壁色を少し変える案 (3) 実機で selftest.html を全ストップ巡回。
## 引継ぎ（次のFへ）
- 常駐: scripts/autosave.sh（run_in_background）, scripts/monitor.sh --loop（/tmp/monitor.log）
- 検査: python3 scripts/patrol.py --report / python3 scripts/shot.py <stop...>（FT_URL で f_preview 等を指定可）
- 音響の検証: TROUBLESHOOTING [F] の OfflineAudioContext → WAV → analyze_media_content の手順

## 2026-10-02 セッション（F）
- 役割登録: roles.py join F（W4 は E が先取り済みのため F=環境/QA/監視を担当）。
- 事故対応: 全員同一作業ツリー＋`git add -A` 系で他人の作業巻き込み／07:22:28Z force-push で記録消失 → **scripts/safe_commit.sh**（パス指定 commit・/tmp/git.lock・force push なし）を追加、TROUBLESHOOTING に記載。
- shot.py: /tmp/browser.lock 自動 flock（ブラウザ同時1本）。
- patrol.py: ultra_* の install(ctx) 契約・衝突マーカー・アセット出典の検査を追加（偽ファイルで検出を確認済み）。
- perf.js: ULTRA 段（既定ON, ?ultra=0 で従来, ?q=ultra で固定）。DPR2/影2048/粒子1.5/aniso16/ssr,taa,volumetricSteps,envRes。降格は <20fps×4秒のみ。node でユニット確認＋実ブラウザでエラー0。
- **scripts/sweep.py**: 全42ストップ巡回（エラー/NaN/カメラ館外/HUD はみ出し・溢れ・重なり/カウンタ）→ collab/SWEEP.md。初回: 🔴0 / 🟡24（E 担当 UI: .tl-tip 端切れ、#room-title×#card 重なり）。ALERTS と roles msg で E に連絡済み。
- 次の F: E の修正後に `python3 scripts/sweep.py --report` 再実行。ultra_* 拡張が出揃ったら `?q=ultra` で sweep。
