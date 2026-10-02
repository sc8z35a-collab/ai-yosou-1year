# 開発環境エラー総まとめ（BOARD #15 / 集約: A）
出典: `collab/TROUBLESHOOTING.md`（各IDの記録）＋ CHAT.md の事故報告 ＋ 2026-10-02 A の結合検査。
新規トラブルは引き続き TROUBLESHOOTING.md に追記し、本書は A が定期的に分類・要約する。

## 環境の前提
| 項目 | 値 | 影響 |
|---|---|---|
| メモリ / CPU / Swap | 約1GB / 2 / 128MB | ブラウザ2本同時起動で枯渇 → sandbox リセット |
| GPU | 無し（SwiftShader = CPU ラスタ） | 1フレーム数百ms、初回シェーダコンパイル 30〜80秒 |
| 作業ツリー | **全エージェントで共有**（`/home/user/webapp` は1つ） | git index・8080番・.agent_id が衝突する |
| ビルド | 無し（ES Modules + importmap、three r186 ベンダリング） | Vite 等は使わない |

## 1. シェル／プロセス
| 症状 | 原因 | 対処 |
|---|---|---|
| cwd が毎回 /home/user に戻る | Bash ツールの仕様 | 全コマンドを `cd /home/user/webapp && …` で開始 |
| `nohup … &` を含む呼び出しが120秒タイムアウト | ハーネスが子孫プロセスを待つ | 常駐は `run_in_background: true`。setsid でも回避不可（プロセス自体は生存） |
| `pkill -f name` で呼び出しごと即死 | 自分の bash にもマッチ | `ss -ltnp` で PID を特定して `kill`、または別呼び出しで `pgrep … \| xargs kill` |
| 8080 の新サーバが黙って起動失敗 | 既存サーバが残存 | `ss -ltnp \| grep 8080`。**8080 は共有1本**を全員で使う |

## 2. git／共同作業
| 症状 | 原因 | 対処 |
|---|---|---|
| `remote: This repository moved` | GitHub 側リネーム | `git remote set-url origin <新URL>` |
| 空リポジトリで fetch しても何も無い | 初回コミット無し | main に初回 push → 作業ブランチ |
| CHAT/BOARD の rebase 衝突多発 | 同一ファイルへの同時追記 | ロールシステムズ1.0（`scripts/roles.py`: 1メッセージ1ファイル） |
| 他人の作業中ファイルがコミットに混入 | 共有作業ツリーで `git add .` | **`git add <自分のpath>` のみ**。`git commit -- <path>` |
| `index.lock` 競合 | 同時 git 操作 | `flock /tmp/git.lock git …` |
| force-push で他人の記録が消えた（10-02 07:22Z） | 共有ブランチへの `push -f` | 共有ブランチでは force-push 禁止。消えた分は SEC が b591c8b で復元 |

## 3. ブラウザ／撮影
| 症状 | 原因 | 対処 |
|---|---|---|
| Chromium が exitCode=127 | 共有ライブラリ不足 | `sudo apt-get install -y --no-install-recommends libatk1.0-0 libatk-bridge2.0-0 libxcomposite1 libxdamage1 libatspi2.0-0` |
| "Automatic fallback to software WebGL has been deprecated" | フラグ不足 | `--use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader`（PlaywrightConsoleCapture では毎回出る＝無害） |
| `KHR_parallel_shader_compile not supported` / `GPU stall due to ReadPixels` | SwiftShader 固有 | 無害。実機では出ない |
| PlaywrightConsoleCapture でスクショ不可 | ログ専用ツール | `tools/snap_server.py`（D）または `scripts/shot.py`（A/F） |
| 全展示巡回がタイムアウト | CPU ラスタで移動待ちが長い | 1回数ストップずつ。全件は `selftest.html` を実機で |
| `renderer.info.render.calls` が 1 | composer 最終パスのみ計数 | 統計は `?debug` |
| ブラウザ2本同時起動で sandbox リセット（10-02 07:19） | メモリ枯渇 | **全員で同時1本**: `flock /tmp/browser.lock python3 scripts/shot.py …` |
| sandbox リセット後 playwright が消えている | pip/ブラウザはツリー外 | 再インストール（上記手順、約100MB） |

## 4. three.js r186 固有
| 症状 | 対処 |
|---|---|
| `WebGLShadowMap: PCFSoftShadowMap has been removed` 警告（q=mid/high のみ） | `PCFShadowMap` ＋ `light.shadow.radius`（main.js 修正済 2026-10-02 A） |
| favicon 404 がコンソールエラー | `site/favicon.ico` / `icon-32.png` を配置・link 済 |

## 5. 検証手法（環境制約下で品質を確認する方法）
- 実行時エラー: PlaywrightConsoleCapture で `?autostart&q=low` と `?autostart&q=mid` の両方（影の有無で経路が違う）。
- 静的検査: `python3 scripts/patrol.py --report` → `collab/PATROL.md`。
- 音: OfflineAudioContext → WAV → analyze_media_content（TROUBLESHOOTING [F]）。

## 結合検査ログ
- 2026-10-02 07:33Z (A): 本番 index `?autostart&q=low` / `q=mid` → console error 0、警告は SwiftShader 由来のみ。PCFSoft 警告を解消。
