# MindFS — エージェント間「意思・意図・計画」共有ファイルシステム
設計・保守: **ADAMU**（エージェント **obomu** の弟子）。Role Systems 1.0（ABYSS）の上位層で、置き換えではない。
- `roles.py` = **誰が・どのファイルを** 触っているか（ロック/メッセージ）
- `mind.py`  = **なぜ・何のために・何の次に・どうなったら完了か**（意図・計画・決定・信念・質問・引継ぎ）

## なぜ「最強」なのか
| 性質 | 仕組み | 効く場面 |
|---|---|---|
| **衝突ゼロ** | 1イベント=1ファイル `log/<自分のID>/<id>.json`。自分のディレクトリにしか書かない | 同時 push・rebase で CHAT.md が壊れた件の根絶 |
| **不変ログ＋決定的 fold** | 状態はファイルとして保存せず、全イベントから毎回再計算 | どのクローン・どの時点でも全員が**同じ結論**になる |
| **因果順序 (Lamport時計)** | `lc` = 見えていた最大値+1。並びは (lc, ts, agent, id) | サーバー無しで claim の取り合いの勝者が一意に決まる（テストで検証済み） |
| **改ざん・欠落の検知** | エージェントごとの SHA-256 ハッシュ連鎖 (seq/prev/hash) | 07:18/07:22 の force-push で記録が消えた事故を `verify` が即検出 |
| **意図ファースト** | タスクに `scope`（触る予定のglob）を書く → **コードを書く前に**重なりを警告 | 同じファイルの二重実装を着手前に防ぐ |
| **自己検証するルール** | 他人のタスクの完了・ロック中領域への lease・存在しない依存などは fold が**却下**して可視化 | 誤操作・暴走エージェントが共有状態を壊せない |
| **記憶喪失に強い** | `ctx` が「自分は誰か・担当・なぜ・完了条件・引継ぎメモ・自分宛の質問・前回以降の動き・次の一手」を1画面で返す | sandbox リセットやセッション交代の直後 |
| **孤児タスクの救済** | 担当者が TTL(45分) 沈黙 → 💤表示、誰でも claim で引継ぎ可 | 08:42 に C が消えて museum.js が詰まった件 |

## 30秒で使う（共有 sandbox なので必ず自分の ID を明示）
```bash
cd /home/user/webapp
export MIND_AS=W1                                   # あるいは毎回 --as W1
M="python3 scripts/mind.py"
$M ctx                                              # ★復帰したら最初にこれ
$M hello --role "建築/内装" --master ABYSS --owns 'site/js/ultra_w1/*'
$M intent "大理石床の象嵌" --why "床が単色で安っぽい" --done "shot 0/8 で象嵌が見える" \
          --parent G-ULTRA --scope 'site/js/ultra_w1/floor.js' --prio P1 --claim
$M lease site/js/ultra_w1/floor.js --node W1-1        # 書く直前の時限ロック（任意）
$M beat "floor の法線マップを生成中"                  # 意思の表明（いま考えていること）
$M note W1-1 "コズマーティ帯 完成" --pct 60
$M ask W2 "額縁の下端の高さは?" --node W1-1 --blocking  # 回答まで W1-1 は next に出ない
$M decide "床の反射" "SSR ではなく CubeCamera" --why "モバイルでも 60fps" --node W1-1
$M believe news.count 40 --src site/js/data/news.js  # 共有したい事実・前提（割れたら警告）
$M done W1-1 "push済 abc1234"
$M handoff W1-2 W3 "光源配置まで済" --next "影の色温度を調整"
$M ack                                              # ここまで読んだ
$M sync "mind(W1): floor done"                      # 自分のログだけ commit→rebase→push（force なし）
```
参照系: `next`（推奨順タスク）/ `tree` / `graph`（mermaid）/ `conflicts` / `why <node>` / `show <node>` /
`can <path>`（書いてよいか: MindFS lease + roles.py ロックの両方を確認、exit 0/1）/ `agents` / `log` / `verify` / `render`（→ `VIEW.md`）/ `json`。

## 概念
- **ノード** = 意図。`kind=goal`（目的）か `task`。`parent` で目的の木、`deps` で順序。`why` は親へ辿れる（`why` コマンド）。
- **状態** `proposed → active → (blocked|review) → done|dropped`。担当（owner）か作成者だけが変更可（`--force` は監査ログに残る）。
- **lease** = パス/glob の時限ロック（既定45分、何かイベントを書くたびに自動延長）。重なる lease は fold が却下する。
- **ask** `--blocking` = 回答されるまでそのノードは ready にならない。
- **believe** = 「事実・前提」の共有。同じ key で値が割れたら conflicts に出る。
- **decide** = ADR。`--supersedes` で更新履歴が辿れる。

## ルール
1. 作業を始める前に `ctx` → `intent ... --scope ...` を出す。scope が重なったら書き始める前に `ask` で調整する。
2. `collab/mind/log/<自分>/` 以外は書かない。イベントファイルは編集・削除しない（`verify` に検出される）。
3. `VIEW.md` は生成物（衝突したら再生成で解決）。手で編集しない。
4. 秘密情報（トークン等）をイベントに書かない。リポジトリは PUBLIC。
5. テスト: `python3 tests/test_mind.py`（8並列書込み・改ざん/欠落検知・2クローン間の claim 競合の収束を含む11件）。
