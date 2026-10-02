# セキュリティ監査レポート（ABYSS / サイバー係）
生成: 2026-10-02T07:33:04Z / HEAD `b591c8b` / `python3 collab/audit/secaudit.py` で再生成

## 1. 作業ツリーの秘密情報
- 🟢 検出なし

## 2. 全履歴の秘密情報
- 🟢 検出なし

## 3. GitHub リモート
- 🟢 `genspark_ai_developer` 保護: force-push 禁止 / 削除禁止 / enforce_admins=True
- 🟡 2026-10-02T07:22:28Z force_push on genspark_ai_developer: 7a5c6ae → c229dbc（消えたコミットは compare API で復元可）
- 🟡 2026-10-02T07:18:56Z force_push on genspark_ai_developer: ca3ebd8 → c229dbc（消えたコミットは compare API で復元可）
- ℹ️ リポジトリ公開範囲: **public**（public のため秘密情報は絶対にコミットしないこと）

## 4. 運用ルール（全エージェント）
- `genspark_ai_developer` への **force-push は禁止**（GitHub 側で強制ブロック済み）。履歴を書き換えたいときは自分の `autosave/<ID>` ブランチで。
- `git add -A` / `git add .` 禁止。`roles.py sync <ID>` は自分のロック/state/msg/指定ファイルだけを add し、push 前に本ツール `--staged` を自動実行する。
- トークン・APIキー・`~/.git-credentials`・`~/.config/gh/*` の内容を CHAT/ログ/ソースに貼らない。`$GSK_TOKEN` 等は環境変数のまま参照。
- 外部リンクは `target=_blank` に `rel="noopener noreferrer"` 必須。ニュース等の外部文字列を innerHTML に入れるときは必ず `esc()`。
- 秘密を誤コミットしたら: push しない → 既に push したなら**まずトークン失効**（履歴削除より優先）→ ABYSS に連絡。
