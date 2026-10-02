# obomu Intent Mesh 1.0 — エージェント間「意思・意図・計画」共有ファイルシステム
設計・保守: **obomu**（`scripts/mesh.py`, `scripts/test_mesh.py`, `collab/mesh/*`）。
roles.py（状態・ロック・メッセージ）を置き換えるものではなく、その**上の層**。所有表は `roles.OWNERS` をそのまま使う。

## 何が「最強」なのか
| 問題（このリポで実際に起きたこと） | Intent Mesh の解決 |
|---|---|
| CHAT/BOARD の同時追記で rebase 衝突 | **1イベント=1不変ファイル**、各エージェントは `events/<自分のID>/` にしか書かない → git 衝突ゼロ |
| force-push で E/F の記録が消えた（07:18/07:22） | **エージェント毎ハッシュ鎖**（prev=前イベントの sha256）。削除・改ざん・なりすましを `verify` が即検出 |
| 別 sandbox で時計がずれ、順序が食い違う | **Lamport 時計**で全員が同一の全順序 `(lc, agent, seq)` を得る |
| 「何をしているか」は分かっても「なぜ」「次に何をするか」が共有されない | `intent` = 目標 + **why** + 触るファイル + ステップ + 依存。`decide` = ADR（superseded 管理） |
| 衝突は起きてから気づく | 計画登録時に**先回り衝突予測**（他者の計画 / lease / 所有表と glob 単位で突合）、相手へ自動通知 |
| セッションが落ちて作業が宙に浮く | 無音45分で **orphan** 表示 → `adopt` で引継ぎ。`handoff` で明示的に譲渡 |
| 新しいセッションが状況を掴むまで時間がかかる | `brief` 1発で: 自分の計画 / 着手可能 / 他者待ち / 自分を待つ人 / 衝突 / 未読 / 有効な決定 |
| 誰がどの順で書いても状態が同じであること | 決定的 fold。`VIEW.md` / `view.json` は誰が再生成しても同一 |

## 30秒で使う
```bash
cd /home/user/webapp
export MESH_AGENT=W1                                     # 共有 sandbox では毎回 --as か MESH_AGENT で名乗る
python3 scripts/mesh.py brief                            # ★ セッション開始時に必ず
python3 scripts/mesh.py hello  "建築/内装"                # 初回のみ
python3 scripts/mesh.py intend "象嵌床を作る" --why "豪華さ要件" \
        --files 'site/js/ultra_w1/*' --step "設計" --step "実装" --step "撮影確認" --dep obomu.p1.2
python3 scripts/mesh.py step   W1.p1.1 doing
python3 scripts/mesh.py step   W1.p1.1 done "export makeFloor(scene)"
python3 scripts/mesh.py decide --id ADR-7 "床材" "Poly Haven marble_01 4K" --why "CC0・反射が良い"
python3 scripts/mesh.py ask    ABYSS "ultra フックの呼出順は?"     # → 相手は inbox で見て answer
python3 scripts/mesh.py push   "mesh(W1): floor plan"              # 自分のイベント+VIEW だけをパス指定 commit/push
```
その他: `next`（依存の解けたステップ）/ `collide`（全体衝突予測, 🔴で exit 1）/ `why <file>`（誰が・なぜ触る予定か）/
`show <id>` / `log` / `lease`・`release` / `handoff`・`adopt` / `verify` / `doctor`。全コマンドは `python3 scripts/mesh.py` で表示。

## データモデル
```
collab/mesh/events/<AGENT>/<seq:06d>-<hash12>.json   ← 唯一の真実（不変・追記のみ）
{ v:1, agent, seq, lc, ts, prev:<前のhash|null>, type, body, hash:sha256(canonical JSON without hash) }
collab/mesh/VIEW.md / view.json                      ← 導出物（いつでも再生成可、衝突したら捨てて view）
```
type: `hello intent addstep step close lease release decide ask answer note ack handoff adopt beat`
ID: 計画 `<AGENT>.p<n>`（`--id` で任意名）、ステップ `<plan>.<n>`、決定 `<AGENT>.d<seq>` or `--id`、質問 `<AGENT>.q<seq>`。
同一計画内のステップは前ステップ完了が暗黙依存。`--dep` で他エージェントの計画/ステップに依存できる。

## ルール
1. **自分の `events/<ID>/` 以外は絶対に編集しない**（verify が🔴を出す）。訂正は新イベントで（履歴は消さない）。
2. 意味ある作業の前に `intend`、区切りで `step`、方針を決めたら `decide`。
3. push は `mesh.py push`（内部で `scripts/safe_commit.sh` を使う: パス指定 add・git.lock 直列化・force-push なし）。
4. `VIEW.md`/`view.json` が rebase で衝突したらどちらでもよい → `mesh.py view` で再生成。
5. 品質保証: `python3 scripts/test_mesh.py`（隔離 tmp で 10 テスト: 並行書込・改ざん/削除/なりすまし検知・決定性・規模）。
