# QA（結合/回帰テスト・データ整合）— 2026-10-02 セッション
所有: `scripts/qa_*.py`, `collab/qa/*`, 本ファイル。他人の所有ファイルは触らない（不具合は所有者へ roles.py say で依頼）。

## 経緯
- 07:21 W4 を取得したが E が同時取得＆同一修正(7b80055)済みと判明 → W4 を E に譲り QA に改名。重複 CSS(roomleave) は撤去。

## scripts/qa_e2e.py（来館者目線の UI 不変条件 E2E）
`python3 scripts/qa_e2e.py [stop...] [--report] [--shots]` / `FT_URL=...?ultra=0` で比較。
- データ: NEWS件数=展示数、日付が 08-12..10-01・昇順、source URL、wing∈WINGS、空欄/重複タイトル
- 各 stop を **snap**（出発と到着が同一フレーム=最悪ケース）→ CSS アニメ収束待ち → 判定:
  キャプション表示/画面内/タイトル・日付が NEWS と一致/見切れ、章タイトル×カード重なり、prev/next disabled、HUD要素の重なり、フィナーレ、camera NaN、pageerror/console.error
- /tmp/browser.lock で他のブラウザ利用と直列化。全42 stop で約10分以上（SwiftShader）→ run_in_background 推奨。

## 知見
- `?autostart` は入館後 stop1 へ自動歩行する。直後に snap すると競合し「戻るボタンが有効」「カード非表示」の偽陽性 → 歩行終了を待ってから巡回。
- SwiftShader は ~1-3fps のため CSS トランジションも遅延。固定 sleep ではなく `document.getAnimations()` の収束を待つこと。
- E の重なり修正を最悪ケースで実測: stop 8/14/21 で重なり 0。
