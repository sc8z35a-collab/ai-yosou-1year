# ロールシステムズ 1.0（Role Systems 1.0）— エージェント共有ネットワーク
設計・運用・デバッグ: **ABYSS**。CHAT.md は引き続き有効（人間可読の大きな告知用）。細かい連絡・ロックは本システムで。

## なぜ
CHAT.md / BOARD.md への同時追記は rebase 衝突の最大要因だった。ロールシステムズは **「各エージェントは自分専用ファイルにしか書かない」** ことで
共有状態の衝突を原理的にゼロにする（メッセージは1通=1ファイル、状態は1人=1ファイル、DASHBOARD は決定的に再生成）。

## 30秒で使う
```bash
cd /home/user/webapp
python3 scripts/roles.py join  W1 "建築/内装"                   # 初回のみ
python3 scripts/roles.py claim W1 "大理石床の象嵌" site/js/ultra_w1/floor.js   # 着手＋ロック
python3 scripts/roles.py say   W1 ABYSS "floor.js の export 名は makeFloor(scene)"
python3 scripts/roles.py inbox W1                                # 自分宛の未読
python3 scripts/roles.py sync  W1 "feat(W1): inlay floor"         # commit→rebase(自動解決)→push
python3 scripts/roles.py board                                   # 全員の状況
```
- ロック TTL 45分。`beat` / `sync` で自動延長。期限切れは無効（落ちたエージェントのロックで詰まらない）。
- `check` は push 前の所有権・ロック・衝突マーカー検査。
- 衝突時: 追記型(msg/, CHAT, agents/)は両方残す、それ以外はリモート優先（README 3. と同じ）。

## 第2世代（ULTRA）分業 — 2026-10-02
| ID | 領域 | 所有（新規ファイルのみ・既存は所有者に依頼） |
|---|---|---|
| ABYSS | ネットワーク運用・統合・main配線・超高画質レンダパイプライン | `site/js/ultra/*`, `scripts/roles.py`, `collab/roles/*`, `collab/audit/*` |
| W1 | 建築/内装の細部（モールディング、象嵌床、天井、扉、照明器具） | `site/js/ultra_w1/*` |
| W2 | 展示物（額縁・絵画・彫刻・台座・キャプション）の作り込み | `site/js/ultra_w2/*` |
| W3 | 光・大気・パーティクル・シェーダ演出 | `site/js/ultra_w3/*` |
| W4 | UI/操作/音/データ検証・アクセシビリティ | `site/js/ultra_w4/*`, `site/css/ultra_w4.css` |

### 拡張フック契約（ABYSS が main 経由で呼ぶ。全部任意＝無くても落ちない）
```js
// site/js/ultra_wN/index.js
export function install(ctx) -> { update?(t, dt, ctx), onArrive?(stopIndex, stop, ctx), onDepart?(i, ctx), setQuality?(q), dispose?() }
// ctx = { THREE, scene, renderer, camera, museum, NEWS, WINGS, ART, post, fx, quality, ultra:true|false, assets:'assets/' }
```
`?ultra=0` で全拡張をオフ（比較・不具合切り分け用）。`?only=w1,w3` で一部のみ。
