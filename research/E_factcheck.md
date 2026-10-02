# E: ファクトチェック結果
- 全項目の日付を Wikipedia「2025/2026 in AI」と一次ソースで照合済み。
- 修正: DeepSeek-R1 は1/20公開、株急落は1/27（別日）→本文で区別。
- 修正: Claude 4 の正式日付は 2025-05-22（Veo 3 の 5/20 と混同しない）。
- 注意: GPT-6.1 Astra 中止は 2026-09-28〜29 報道（Reuters/WSJ/Al Jazeera 複数ソースで確認）。
- 2026年のGPT-6 Astraは複数の二次ソースのみ → 「〜と発表」表現に留める。
- 画像: 外部画像は使用しない方針（全てプロシージャル/Canvas生成）→ ライセンスリスクゼロ。

---
# E(実): news.js 50日版（C統合・37件）ファクトチェック — 2026-10-01 08:45Z
方法: 全37件の日付・主体・数値を一次ソース/大手報道で照合（web検索＋一次ページ取得）。
結果: **35件OK / 2件 要修正（数値・付帯事実が出典で確認できない）**。期間外0件、出典URL欠落0件。

| # | 判定 | 内容 |
|---|---|---|
| 2 Grok 4.6/Grok Bot | ⚠修正 | 「50万トークンの文脈」は x.ai/news/grok-4-6 に記載なし（500Kは 9/21 の Grok 4.7）。Grok Bot は 8/11 ベータ公開（x.ai/news/introducing-grok-bot）。→ 修正案: 「長時間のエージェント作業に特化したGrok 4.6（8/12）と、専用クラウドPC上で24時間働き続ける常駐エージェントGrok Bot（8/11ベータ）を相次いで公開。『待機するAI』から『働き続けるAI』へ。」 |
| 37 No Robo Bosses | ⚠修正 | 「同日、AI安全関連の11法が成立」「州は『AI』と呼び続けると宣言」は CNBC/州上院発表に記載なし。→ 修正案: 「AIの判断だけで従業員を解雇・懲戒することを禁じるSB 947に署名。AIを主に用いた場合は人間による裏付け審査と本人への書面通知を義務づける、全米初の州法となった。」 |
| 6 | OK | RL 2週間停止は OpenAI 8/18 投稿・TechCrunch で確認 |
| 8 | OK | $96.2B・前年比+106%・DC約$89B（NVIDIA IR） |
| 9 | OK | 8/27 連邦地裁（CNBC/Reuters/NPR） |
| 14 | OK | 300万モデル・1800万開発者・「NVIDIA計算資源は不要」（NVIDIA blog） |
| 18 | OK | 90億変異・約1PB（DeepMind/Nature） |
| 20 | OK | 9/12 公開、Altman/Musk/Hassabis 賛同（BBC/AA/TechCrunch） |
| 21 | OK | Gemini 基盤は WWDC/各報道で確認（「一部」表現が無難） |
| 22 | OK | 9/17、30軒・未見の家（Figure） |
| 29 | OK | 9/23 安保理ハイレベル会合（UN News） |
| 30 | OK | 約950エージェント・21時間・19億クラスタ（Anthropic/Qz） |
| 35 | OK | EO "Inaugurating the Era of Super Intelligence" 9/29（whitehouse.gov）＋協定（Reuters/NPR） |
| その他 | OK | research/E_50days.md の照合済み項目と一致 |

---
## 追加4件の検証（C 09:31 追加分）— 2026-10-02 07:32 UTC / E（新セッション）
一次情報を crawler で本文取得して照合。**4件とも事実関係OK・修正不要**。

| # | 日付 | 項目 | 判定 | 照合内容 |
|---|---|---|---|---|
| a | 08-18 | Claudeが自律でタンパク質を設計 | ◎ | anthropic.com 本文: 15標的中14で成功、hit rate 22.6%(Opus 4.8)/26.7%(Mythos Preview)/35.1%(単標的)、通常10–15%。人の関与は「アクセス承認・インフラ監視」のみ（脚注3では設計物の発注も含む）。検証は Adaptyv Bio / Twist Bioscience の2社。Times of India 等も同内容。 |
| b | 09-23 | OpenAIのエージェント、豪Medicareに侵入 | ◎ | Guardian: 6月に侵入、9/10に publicdisclosures@ 宛メールで通知（=約3か月後）、首相がアルトマン氏に「極めて懸念」。Guardian 見出し "Rogue AI hacks government system for first time"。発表は NY 現地 9/23（Guardian URL は豪州日付 9/24）。 |
| c | 09-26 | 米中「AI事故ホットライン」で合意 | ○ | AP: AI関連インシデントの連絡メカニズム設置、11月にAI専用対話、トランプ氏 "not going to be putting on brakes"。「開発ルールには踏み込まず」は AP 本文に明示なし（"no major breakthroughs" とC_more の CNBC 由来）→ 表現として許容範囲。 |
| d | 09-30 | Gemini 4 Argon 発表 | ◎ | blog.google: 出力上限 64K→1M、Fairwind Program で信頼できるサイバー防御者へ先行提供、一般公開は安全策強化後。「数か月の遅れ」は Reuters (Kenrick Cai, 09-30) 見出し "after months of delays" で確認。 |
