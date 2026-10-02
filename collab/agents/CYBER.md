# CYBER — サイバー係 2号（デプロイ時のブラウザ側防御）
> SEC（scripts/seccheck.py: 秘密情報・DOM・vendor・GitHub保護）と重複しない領域を担当。

## 所有
scripts/csp_headers.py, tools/csp_server.py, site/_headers, collab/agents/CYBER.md（+ .gitignore の [CYBER] ブロック）

## 使い方
- 検査: `python3 scripts/csp_headers.py`（インラインscriptハッシュ不一致・許可外オリジンで exit 1）
- 再生成: `python3 scripts/csp_headers.py --write`
- 実地確認: `python3 tools/csp_server.py 8095`（run_in_background）→ PlaywrightConsoleCapture で "Refused to" が出ないこと
  （ローカル http 用に upgrade-insecure-requests と HSTS だけ外して送る）

## 2026-10-02 作業ログ
- 独自監査（SEC と並行・結果一致）: 全履歴の秘密情報0、vendor 155ファイル jsDelivr three@0.186.0 と SHA256 一致、ui.js esc()/https限定/noopener OK、snap_server パストラバーサル実証→SEC 版修正を正として自分の重複修正は破棄
- assets 175 jpg のマジックバイト/末尾検査（偽装ファイル・HTML混入なし）、gltf の外部 uri なし
- site/_headers 生成、CSP 下で index.html?autostart / selftest.html のコンソールに CSP 違反0（WebGLドライバ警告のみ）
- .gitignore に秘密ファイル類

## 残課題
- ultra_* 拡張が外部CDN/画像を読む場合は ALLOWED_ORIGINS 追加が必要（patrol/seccheck で検知したい）
- ホスティング先が Workers(Hosted) の場合 `_headers` が効くか要確認 → 効かなければ Worker 側でヘッダ付与
