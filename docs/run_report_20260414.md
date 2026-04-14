# Zenn記事自動生成システム v4.0 — 実行レポート

**作成日**: 2026-04-14
**run_id**: 20260414_100127
**所要時間**: 約90分（Layer 1: 15分 / Layer 2: 75分）

---

## 1. システムアーキテクチャ概要

```
┌─────────────────────────────────────────────────────────┐
│                    層1: MetaAgent（固定3体）               │
│  ┌───────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Strategist │→│ Agent Editor  │→│ Eval Designer │      │
│  │ 戦略立案   │  │ エージェント  │  │ 評価基準     │      │
│  │ エスカレー  │  │ 動的生成     │  │ 動的生成     │      │
│  │ ション判断  │  │ workflow.json│  │              │      │
│  └───────────┘  └──────────────┘  └──────────────┘      │
└──────────────────────┬──────────────────────────────────┘
                       ↓ agents/generated/ + workflow.json
┌─────────────────────────────────────────────────────────┐
│               層2: 動的エージェント群                      │
│                                                          │
│  [素材生成]  code_analyzer ─┐                            │
│              trend_searcher ─┼→ 並列実行                 │
│              dev_simulator  ─┘                            │
│                    ↓                                      │
│  [素材PDCA]  material_reviewer ⇄ material_updater        │
│              (max 5 iter, score停滞→エスカレーション)      │
│                    ↓                                      │
│  [記事PDCA]  writer → article_reviewer → style_guide_updater │
│              (max 10 iter, 停滞→ADD_AGENT等)              │
└──────────────────────┬──────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────┐
│               層3: 蓄積基盤                               │
│  knowledge/     — トレンド・読者ペイン（記事間で育つ）      │
│  style_memory/  — 文体ルール + 学習ログ                    │
│  agent_memory/  — 実行構成と有効性の記録                   │
│  human-bench/   — ペルソナ記事18本                         │
│  runs/          — 実行履歴（成果物保存）                   │
└─────────────────────────────────────────────────────────┘
```

**技術スタック**: Python + Claude CLI (`claude -p`) + asyncio並列実行
**エージェント呼び出し**: subprocess経由でClaude Sonnetを使用
**コード行数**: orchestrator.py 1,700行 / knowledge_store.py 174行 / テスト193件

---

## 2. AIの思考フロー（全ステップ詳細）

### Phase 1: 戦略立案（Strategist）
1. ソースファイル4本（builder/planner/reviewer/visualizer の post-instructions.md）を全文読み込み
2. ペルソナ記事18本のindex.yamlを参照し、素材参考4本 + 文体参考4本を選定
3. 記事の性格を決定: `article_type: 体験記`, `tone: カジュアル寄り（です・ます体）`, `tech_depth: 中級`
4. 「勝ち筋」を言語化: 「境界のどちら側に責任を置くかを決めて初めてシステムが動いた」
5. 「死にパターン」6個を具体的に定義（全エージェント均等カタログ、スペック羅列冒頭、等）
6. `priority_style_categories` で冒頭フック・失敗談の正直さ・具体性・メタファーの効果を重視指定

### Phase 2: エージェント構成決定（Agent Editor）
1. strategy.mdを読み、8エージェント構成を決定
2. agent_templates/から各テンプレートを読み、agents/generated/にカスタム指示付きで出力
3. workflow.json生成: 4フェーズ（material_generation[並列] → material_review[PDCA] → article_writing → article_review[PDCA]）
4. **1回目の検証で16エラー**（生成ファイル不在等）→ 修正依頼 → 2回目でパス

### Phase 3: 評価基準設計（Eval Designer）
1. ベンチマーク記事4本（家老切腹, TAKT, PR83%, DESIGN.md）を全文読了
2. 素材評価軸5個（役割境界の具体性[w=0.30], 失敗ナラティブの質[w=0.25], 契約モチーフ素材[w=0.20], 読者共感[w=0.15], 技術的正確性[w=0.10]）を設計
3. 記事評価軸8個（冒頭フック力[w=0.20], 役割境界[w=0.15], 失敗ナラティブ[w=0.15], 契約モチーフ一貫性[w=0.15], 死のパターン回避[w=0.15], 体験密度[w=0.10], 読者共感[w=0.05], 技術正確性[w=0.05]）を設計
4. 各軸に1.0/0.5/0.0の具体的な条件とベンチマーク比較を記述

### Phase 4: 素材生成（3エージェント並列）
- **code_analyzer**: ソース4ファイルを分析し、fixed/に5ファイル生成（architecture, key_decisions等）
- **trend_searcher**: Zenn/Qiita/はてな等から「マルチエージェント 役割分担 設計」で検索。knowledge/trends.mdに追記
- **dev_simulator**: sim_human→sim_claude→sim_directorの3体制御でシミュレーションログ生成

### Phase 5: 素材PDCA（3イテレーション → 成功終了）
```
Iter 1: Material Reviewer → 7.7/10 → Material Updater（2,622文字の改善レポート）
Iter 2: Material Reviewer → 8.4/10 → Material Updater（1,333文字）
Iter 3: Material Reviewer → 8.7/10 → 2連続8.0超で成功終了 ✅
```

### Phase 6: 記事PDCA（4イテレーション → 停滞→エスカレーション→停止）
```
Iter 1: Writer → Article Reviewer → 6.4/10 → Style Guide Updater
Iter 2: Writer → Article Reviewer → 6.5/10 → Style Guide Updater
Iter 3: Writer → Article Reviewer → 6.8/10 → 停滞検出（幅0.4≤tolerance 0.5）
  → Strategistにエスカレーション → ADD_AGENTを選択
  → Agent Editorが「narrative_puncher」を新規生成・レジストリ登録
Iter 4: Writer → Article Reviewer → 6.4/10 → FB停滞（エスカレーション後の再停滞）→ 停止
```

### Phase 7: 振り返り（Strategist）
- learning_log.mdに5項目の振り返りを記録（勝ち筋実現度40%、次回への学び5点）
- agent_memory/に実行記録をYAML保存
- runs/に全成果物を保存

---

## 3. 外部から収集したデータ

| データ | 収集元 | 内容 |
|---|---|---|
| **技術トレンド** | Zenn, Qiita, はてなブログ, note, Hacker News | 「マルチエージェント 役割分担 設計」関連のZenn記事5本の反応数・内容サマリー、Qiitaの設計パターン解説記事群 |
| **読者の痛み** | DEV Community, Anthropic Blog, Zenn | 6つのペイン（artifact-traceability, phase-gate-design-uncertainty, context-propagation-degradation, loop-termination-criteria, agent-role-granularity-decision, kol-personalization-gap） |

**注意**: trend_searcherは `claude -p` 内でWeb検索を試みますが、実際にどこまで外部APIを叩けたかはLLMの実行環境に依存します。knowledge/trends.mdに記録された内容からは、Zenn/Qiita/はてなの記事タイトル・いいね数・ブックマーク数が具体的に引用されており、一定の外部データ収集が行われたと推定されます。

---

## 4. トークン消費量

**現在のシステムではトークン消費量を計測する仕組みが未実装です。**

推定値（エージェント呼び出し回数 × 平均入出力トークン数）:

| フェーズ | 呼び出し回数 | 推定入力トークン | 推定出力トークン |
|---|---|---|---|
| Layer 1 MetaAgent | 5回（Strategist + Agent Editor×2 + Eval Designer） | ~50K | ~5K |
| material_generation | 3回（並列） | ~30K | ~3K |
| material_review PDCA | 6回（Reviewer+Updater × 3iter） | ~60K | ~8K |
| article_writing | 1回 | ~15K | ~3K |
| article_review PDCA | 12回（Writer+Reviewer+SGU × 4iter） | ~120K | ~12K |
| エスカレーション | 2回（Strategist + Agent Editor） | ~20K | ~2K |
| 振り返り | 1回 | ~15K | ~2K |
| **合計** | **30回** | **~310K** | **~35K** |

**推定総トークン: 約345Kトークン（約$1〜3程度 ※モデル・プランによる）**

### 改善案
`subprocess.run`の出力にトークン数情報が含まれない現状を改善するため、`claude -p`に`--output-format json`を使ってレスポンスからトークン数を抽出し、summary.jsonに記録する機能の追加が必要。

---

## 5. さらなる改善案

### A. 精度を上げるには

| 改善 | 内容 | 期待効果 |
|---|---|---|
| **Writerへの前回FB注入** | 記事PDCAの各イテレーションで、前回のreview.mdの指摘をWriterプロンプトの冒頭に埋め込む | 記事PDCAのスコア改善率向上（現状: major指摘の解消率0%→目標50%以上） |
| **素材→記事引継ぎ文書** | 素材PDCA完了時にwriter_handoff.mdを自動生成（使ってよい/いけない素材の分類、推定出力の注意事項）| 戦略→記事の骨格維持率向上（現状40%→目標80%） |
| **style_guideのPre-context注入** | Writerプロンプト冒頭に「です・ます体必須」を直接埋め込む | です・ます比率35%→80%以上 |
| **動的エージェントの実行パス** | ADD_AGENTで生成されたエージェントを実際にrun_iteration内で呼び出す | エスカレーション後のスコア改善 |

### B. トークン消費を抑えるには

| 改善 | 内容 | 削減見込み |
|---|---|---|
| **素材のサマリー化** | Writerに全素材原文ではなくサマリーを渡す | Writer呼び出し1回あたり30-50%削減 |
| **早期終了条件の緩和** | 素材PDCAの成功閾値を8.0→7.5に下げる | 素材PDCA 1-2iter削減 |
| **スコア抽出失敗時のスキップ** | スコア0.0のイテレーションを停滞判定から除外 | 無駄なイテレーション削減 |
| **トークン計測の導入** | 各エージェント呼び出しのトークン数を記録し、上限を設定 | 暴走防止 |

### C. 記事を作るごとに精度が向上する仕様にするには

| 改善 | 内容 | 蓄積効果 |
|---|---|---|
| **agent_memoryの充実** | score_by_axis、eval_criteria_accuracy、custom_agents_effectivenessを正しく記録 | Eval Designerが過去の軸精度を参照して重みを調整 |
| **人間FBの蓄積** | feedbackコマンドで記事へのFBを記録し、AI評価vs人間評価のギャップを蓄積 | 次回のEval Designerが人間感覚に近い重みを設定 |
| **style_guideの段階的精錬** | Style Guide Updaterが毎回ルールを追加・退役する仕組みを活用 | 文体の一貫性が回を重ねるごとに向上 |
| **learning_logの参照** | Strategistが過去の振り返りを読んで戦略を調整 | 同じ失敗を繰り返さない |
| **ベンチマーク記事の拡充** | 成功した記事を human-bench/に追加 | 評価基準の精度向上 |

---

## 6. 意図したロジックに対する抜け漏れ

| # | 意図したロジック | 実際の動作 | 影響 |
|---|---|---|---|
| **1** | Writerは前回レビューのFBを読んで修正する | ~~**前回レビューがWriterプロンプトに注入されていない**~~ → **修正済み（2026-04-14）**: 素材PDCA（Material Updater）・記事PDCA（Writer）の両方で前回review.md + FB差分サマリーを注入 | ~~major指摘の解消率0%~~ → 次回実行で効果検証 |
| **2** | FB構造化JSONでPDCA差分を追跡する | **Article ReviewerのJSON出力でパースエラー**（iter 1） | FB差分停滞検出が部分的に機能しない |
| **3** | ADD_AGENTで生成されたnarrative_puncherが記事改善に寄与する | **レジストリに登録されたが実行されなかった** | エスカレーションの効果がゼロ |
| **4** | style_guide.mdのカテゴリタグでフィルタリングされたルールがWriterに渡る | **priority_style_categoriesがYAML正規フォーマットで出力されず、パース失敗で全ルール渡し** | フィルタリング機能が未活用 |
| **5** | agent_memoryにscore_by_axis等の詳細が記録される | **overall_scoreのみ記録。軸別スコアは未蓄積** | 次回のEval Designerが軸精度を参照できない |
| **6** | Eval Designerの評価基準がArticle Reviewerの`## Overall: X/10`フォーマットで出力されるよう制御する | **Eval Designerが独自のJSON形式（0-1スケール）を指示** | 今回はBug 1修正で吸収したが、根本的にはEval DesignerとReviewerの出力フォーマット統一が必要 |

---

## 7. 致命的な欠陥

### ~~欠陥1: 記事PDCAでWriterにFBが渡らない（最重要）~~ → **修正済み（2026-04-14）**

**症状**: 4イテレーション回してもmajor指摘が1件も解消されない
**根因**: `run_iteration()`がWriterに前回のreview.mdを渡していない。Writerは毎回ゼロから書いている
**修正内容**: `run_iteration()`の素材PDCA（Material Updater）・記事PDCA（Writer）の両方で、前回review.md全文 + `compute_fb_diff()`によるFB差分サマリー（resolved/persisted/new/resolution_rate）をプロンプトに注入するよう修正。これによりUpdater/Writerが「前回何を指摘されて、何が解消済みで、何が未解消か」を知った上で改善に取り組める

### 欠陥2: エージェント出力がファイルに保存されないことがある

**症状**: `claude -p`の出力をsubprocessで受け取り、ファイルに保存する前提だが、エージェントが自分でファイルに書き込むか、orchestratorが受け取った出力をファイルに書くかが不明確
**根因**: エージェントは`--add-dir`でプロジェクトルートにアクセスできるが、ファイルを書くかどうかはLLMの判断に依存する。orchestratorは`if not path.exists(): path.write_text(output)`でフォールバックしているが、出力がファイルの中身として適切でない場合がある
**影響**: 素材ファイル（fixed/*.md等）の品質がエージェントの振る舞いに強く依存
**修正コスト**: 中（エージェントに「必ずファイルに書き込め」を徹底するか、orchestratorが出力を解析してファイルに書く）

### 欠陥3: トークン消費量の計測・制御がゼロ

**症状**: 暴走時に青天井でトークンを消費する可能性がある
**影響**: コスト管理ができない
**修正コスト**: 低（`claude -p --output-format json`でトークン数を取得し記録するだけ）

---

## 8. 今回蓄積されたナレッジ

### A. knowledge/ （記事間で育つ知識DB）

| ファイル | 蓄積内容 |
|---|---|
| **knowledge/trends.md** | Zenn/Qiita/はてなの「マルチエージェント 役割分担」関連記事5-10本のタイトル・反応数・サマリー |
| **knowledge/reader_pains.md** | 6つの読者ペイン（artifact-traceability, phase-gate-design-uncertainty, context-propagation-degradation, loop-termination-criteria, agent-role-granularity-decision, kol-personalization-gap） |

### B. style_memory/ （文体ルール蓄積）

| ファイル | 蓄積内容 |
|---|---|
| **style_memory/style_guide.md** | v3.0から移行した11個のIMPORTANTルール + Style Guide Updaterによる追加ルール |
| **style_memory/learning_log.md** | run_20260414_100127の振り返り5項目（勝ち筋実現度40%、次回への学び5点） |

### C. agent_memory/ （実行構成記録）

| ファイル | 蓄積内容 |
|---|---|
| **agent_memory/run_20260414_100127.yaml** | article_type=体験記、8エージェント構成、素材3iter/記事4iter、エスカレーション(ADD_AGENT)、fb_summary |

### D. runs/ （実行履歴）

| ファイル | 蓄積内容 |
|---|---|
| **runs/20260414_100127/** | strategy.md, eval_criteria.md, workflow.json, agents_generated/, final_article.md, scores.json, summary.json, fb_log.json |

---

## 9. 次回のナレッジ利用ロジックと改善点

### 現在整っているロジック

| ナレッジ | 利用箇所 | ロジック |
|---|---|---|
| **agent_memory** | Strategist / Agent Editor / Eval Designer | `filter_agent_memory(article_type, limit=5)` で同タイプの過去記録を優先取得。human_feedbackありを優先 |
| **learning_log** | Strategist | `get_recent_learning_log(10)` で直近10件の振り返りを取得 |
| **style_guide** | Writer / Reviewer | `filter_style_rules(categories)` でstrategyに合ったルールを注入 |
| **knowledge/trends.md** | Strategist / trend_searcher | `filter_by_topic(topic, max_lines=200)` でトピック関連エントリを抽出 |
| **human-bench/index.yaml** | Strategist | material_quality/style_qualityでフィルタして参考記事を選定 |

### 整っていないロジック（要修正）

| # | 問題 | 必要な修正 |
|---|---|---|
| **1** | **agent_memoryのscore_by_axisが空** | `write_agent_memory()`にRunStateから軸別スコアを収集する処理を追加 |
| **2** | **agent_memoryのeval_criteria_accuracyが空** | Strategist振り返りの出力をパースして該当フィールドに記録する処理を追加 |
| **3** | **agent_memoryのcustom_agents_effectivenessが空** | エスカレーションで追加されたエージェントの効果を記録する処理を追加 |
| **4** | **feedbackコマンド未使用** | 人間FBを蓄積する運用フローが確立されていない |
| **5** | **knowledge/のフィルタリングが粗い** | 現在はキーワードの単純部分一致。BM25やTF-IDFベースの関連度スコアリングが必要 |

### データ膨大化への対策

| 対策 | 現状 | 改善案 |
|---|---|---|
| **knowledge/の肥大化** | 6ヶ月超のアーカイブ機能あり（`archive_old_entries()`） + 200行上限フィルタ | ✅ 現状で十分だが、記事数が100を超えるとキーワード検索の精度が低下。**Embeddingベースのセマンティック検索**への移行を検討 |
| **style_guide.mdの肥大化** | 200行上限 + Consolidator圧縮 + IMPORTANTルール15個上限 | ✅ 良い設計。ただし退役判定の「直近3iterで違反なし」はStyle Guide Updaterに依存しており、精度が不安定 |
| **agent_memory/の肥大化** | article_typeフィルタ + 直近5件制限 | ⚠️ 100実行を超えるとYAMLファイルのglob走査が遅くなる。**SQLiteまたはJSONL形式**への移行を推奨 |
| **runs/の肥大化** | 追記のみ（削除なし） | ⚠️ 各実行に10-20ファイル保存。100実行で1,000-2,000ファイル。**古いrunの圧縮アーカイブ**（tar.gz化）を検討 |

### 検索精度と拡張性の改善

| レベル | 改善 | コスト | 効果 |
|---|---|---|---|
| **短期（今すぐ）** | agent_memoryのフィールド充実 + feedbackの運用開始 | 低 | 次回からEval Designerの重み精度が向上 |
| **中期（10実行後）** | knowledge/のセマンティック検索（Embedding + コサイン類似度）導入 | 中 | トレンド検索の関連度向上。キーワードに依存しない検索 |
| **中期（10実行後）** | agent_memoryのSQLite化 + インデックス追加 | 中 | article_type × human_feedback × created_atの複合クエリが高速化 |
| **長期（50実行後）** | ペルソナ記事のベクトルDB化 + RAG検索 | 高 | 18本→50本以上に拡充しても、記事の「強み」で検索可能 |
| **長期（50実行後）** | style_guideのルール自動分類・重要度推定 | 高 | 退役判定の精度向上。違反頻度ベースの自動優先度付け |

---

## 10. 総合評価

### 成功した点
- **全フローが一気通貫で動いた**: MetaAgent→素材PDCA→記事PDCA→振り返り→保存
- **素材PDCAは高品質**: 7.7→8.4→8.7と着実に改善し成功終了
- **動的エージェント構成**: Agent Editorが状況に応じたworkflow.jsonを生成
- **エスカレーション機構**: 停滞検出→Strategist判断→ADD_AGENTまでの全フロー
- **蓄積基盤**: learning_log, agent_memory, knowledge, runsに正しく保存

### 最優先で修正すべき3点
1. ~~**WriterへのFB注入**（記事PDCAの改善ループが機能していない根本原因）~~ → **修正済み（2026-04-14）**: 素材PDCA・記事PDCAの両方で、前回review.md + FB差分サマリー（resolved/persisted/new/resolution_rate）をUpdater/Writerプロンプトに注入するよう修正
2. **エージェント出力のファイル保存の確実化**（出力品質の安定性）
3. **トークン計測の導入**（コスト管理）
