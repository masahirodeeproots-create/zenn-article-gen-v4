# v4.0 PDCA改善計画書

## 背景と問題

v4.0設計のPDCAループに4つの構造的問題がある。

| # | 問題 | 影響 |
|---|---|---|
| P1 | 重要FBがstyle_guide.mdに抽出されず消える | 記事固有の指摘（「3章が弱い」等）が次イテレーションの改善判断材料として構造化されない |
| P2 | 毎回同じFBが繰り返される | Updaterの対応範囲外の問題が指摘され続け、PDCAが空転する。スコアベースの停滞検出では「スコアは微妙に動くがFBの中身は同じ」を検出できない |
| P3 | FBがどのくらい改善に繋がったか測れない | スコア推移しか見ていないため、「何が解消され、何が残存し、何が新規発生したか」が不明 |
| P4 | style_guide.mdがグローバル共有で文体要素が語尾・視点に偏る | 記事タイプ別の切り替え不可。リズム・構造・距離感・情報密度・感情設計などの多様な文体要素が管理できない |

---

## 改善施策

### 施策A: FB構造化ログ（fb_log.json）の新設

**解決する問題**: P1, P2, P3の基盤

各イテレーションのReviewer FBを構造化して記録する。style_guide.mdへの抽出とは別系統で、全指摘を残す。

**責任分担の原則**: FB項目のID付与・カテゴリ分類・解消判定は**Reviewerエージェントの責務**。Reviewerが構造化JSON形式で出力し、コード側（record_fb_log）はそのJSONをパースして記録するだけの**確定ロジック**に限定する。

```json
{
  "phase": "article_pdca",
  "iterations": [
    {
      "iteration": 1,
      "issues": [
        {
          "id": "fb_1_1",
          "category": "structure",
          "detail": "冒頭のフックが弱い。読者が読み進める動機が不足",
          "severity": "major",
          "resolved": false
        },
        {
          "id": "fb_1_2",
          "category": "rhythm",
          "detail": "中盤に同じ文長の文が5文連続している",
          "severity": "minor",
          "resolved": false
        }
      ]
    },
    {
      "iteration": 2,
      "issues": [
        {
          "id": "fb_1_1",
          "category": "structure",
          "detail": "冒頭のフックが弱い（前回から改善なし）",
          "severity": "major",
          "resolved": false
        },
        {
          "id": "fb_1_2",
          "category": "rhythm",
          "detail": "(解消)",
          "severity": "minor",
          "resolved": true,
          "resolved_at": 2
        },
        {
          "id": "fb_2_1",
          "category": "density",
          "detail": "コードブロック後の解説が不足",
          "severity": "minor",
          "resolved": false
        }
      ]
    }
  ]
}
```

**プロンプト注入時の上限**: Reviewer/Updaterのプロンプトにfb_logを渡す際は**直近3イテレーション分のみ**に制限する（C-09コンテキスト汚染防止の原則に準拠）。

### 施策B: FB差分メトリクスの導入

**解決する問題**: P2, P3

fb_log.jsonを元にイテレーション間の差分を計算し、PDCAループ制御に組み込む。

```
compute_fb_diff(fb_log, iter_a, iter_b) → {
  resolved: [...],       # iter_aにあってiter_bで解消 → 改善された
  persisted: [...],      # 両方にある → 残存（PDCAが効いていない）
  new: [...],            # iter_bで初出 → 新規発生
  resolution_rate: float # resolved / (resolved + persisted)
}
```

**PDCAループ制御への組み込み**:

| 指標 | 判定 | アクション |
|---|---|---|
| `resolution_rate` が高い | PDCA効いてる | 続行 |
| `persisted` にmajorが3回連続残存 | FBレベルの停滞 | 即エスカレーション（スコア停滞を待たない） |
| `new` が増え続ける | 直すたびに別の問題 | ADJUST_EVAL検討 |

既存のスコアベース停滞検出と**併用**する（置き換えではない）。

**配置**: FB差分メトリクスは記事テキストの客観計測（§14）とは性質が異なるため、§14には混ぜず**§10 PDCAループ制御内に独立して配置**する。

### 施策C: Updater対応可否レポートの導入

**解決する問題**: P2

Updater（Material Updater / Article Updater）がFBに対して改善を行った際、各指摘への対応状況をYAML形式で明示的にレポートする。

```yaml
response_report:
  - issue_id: fb_1_1
    action: attempted
    detail: "冒頭を書き直したが、素材に具体的なエピソードがなく限界がある"
  - issue_id: fb_1_2
    action: resolved
    detail: "文長にばらつきを持たせた"
  - issue_id: fb_2_1
    action: cannot_resolve
    reason: "material_shortage"
    detail: "コードの背景説明が素材に含まれていない"
```

**対応不可（cannot_resolve）の reason による自動アクション**:

| reason | アクション |
|---|---|
| `material_shortage` | MATERIAL_ISSUE → 素材PDCAに差し戻し |
| `eval_mismatch` | ADJUST_EVAL → Eval Designerに差し戻し |
| `strategy_level` | エスカレーション → Strategist |

既存のMATERIAL_ISSUE即時差し戻し（FR-2.4.5）を拡張する形で実装。

**エスカレーション回数との関係**: cannot_resolve起因の自動アクションは**エスカレーション回数にカウントしない**。ただし以下の例外がある。

- `cannot_resolve/strategy_level` → Strategistへのエスカレーションを発火する。これは**エスカレーション回数にカウントする**。
- エスカレーションが既に消費済みの場合、`strategy_level` の自動アクションは発火せず、警告ログを出力してPDCAを続行する。

**MATERIAL_ISSUE回数制限の統一**: Reviewer起因（既存FR-2.4.5）とUpdater起因（施策C）のMATERIAL_ISSUEは**同一カウンターを共有**する。合計1回の制限。2回目以降のMATERIAL_ISSUEトリガーは無視し、代わりにエスカレーション（Strategist）に回す。

### 施策D: style_guide.mdの性質タグ化

**解決する問題**: P4

ジャンルタグではなく**文体要素の性質カテゴリ**でタグ管理する。

**カテゴリ定義**:

| カテゴリ | 対象 | 例 |
|---|---|---|
| `rhythm` | 文の長さ・リズム・テンポ | 「3文以上同じ文長が続かない」 |
| `structure` | 記事全体の構成パターン | 「冒頭2段構成：何の話か→フック」 |
| `distance` | 読者との距離感・語りかけ方 | 「問いかけは1セクション1回まで」 |
| `density` | 情報密度・コードと解説のバランス | 「コードブロック後に必ず1-2文の解説」 |
| `emotion` | テンションの設計・ユーモア | 「失敗談の後にユーモアで緩和」 |
| `voice` | 語尾・人称・敬体 | 「です・ます調で統一」 |

**style_guide.mdの新フォーマット**:

```markdown
## IMPORTANT Rules

- [rhythm] 3文以上同じ文長が続かないようにする。短→長→短の波を意識
- [structure] 冒頭2段構成：「何の話か」→「フック」
- [distance] 読者への問いかけは1セクション1回まで
- [density] コードブロックの後に必ず1-2文の解説を入れる
- [emotion] 失敗談のあとにユーモアを1つ入れると緩和される
- [voice] です・ます調で統一

## Learned Rules

- [rhythm] セクション冒頭は短文で入る（15字以内）
- [voice] 一人称で書くとき「私は」を連発しない。省略で十分
- [structure] 技術的な説明は「結論→理由→具体例」の順序

## Failure Patterns

- [rhythm] 同じ文長の文が4文以上続くと読者が離脱する
- [density] コード比率20%超で「コード貼っただけ」感が出る
```

**IMPORTANTルールの識別方法**: `## IMPORTANT Rules` セクション配下のルールをIMPORTANTとして扱う（セクションヘッダ基準）。カテゴリタグの有無に関わらず、このセクション内のルールがcount_important_rulesの対象となる。

**filter_style_rules(categories)の挙動**:
- 指定カテゴリに一致するルールだけを抽出して返す
- **該当カテゴリが0件の場合**: フィルタなし（全ルール適用）にフォールバックする

**マイグレーション**: v3.0からの移行時、既存のタグなしルールは `[uncategorized]` として扱う。Style Guide Updaterが次回更新時に適切なカテゴリタグに置き換える。

**Strategistの活用方法**: strategy.mdで「今回重視するカテゴリ（priority_style_categories）」を指定 → `filter_style_rules(categories)` で該当カテゴリのルールだけをWriter/Reviewerに渡す。

---

## ドキュメント修正計画

### REQUIREMENTS_v4.md

| 修正箇所 | 施策 | 変更内容 |
|---|---|---|
| §1.2 核心の思想転換テーブル | A,B | 「評価」行に「FB構造化ログによるイテレーション間差分追跡」を追加 |
| **§3.1 FR-1.1 Strategist** | **D** | **FR-1.1.1改訂: 出力パラメータにpriority_style_categories（今回重視する性質カテゴリ）を追加** |
| **§3.1 FR-1.3 Eval Designer** | **D** | **FR-1.3入力仕様に「style_guide.mdは性質カテゴリタグ付きフォーマット」である旨を追記** |
| §3.2 FR-2.2 素材PDCA | A,C | FR-2.2.5新設: Material UpdaterがFBへの対応可否レポートを出力する |
| | A | FR-2.2.6新設: 各イテレーションのReviewer FBをfb_log.jsonに構造化記録する |
| | **B** | **FR-2.2.7新設: 素材PDCAにもFB差分メトリクス（resolution_rate等）による停滞検出を適用する** |
| | **C** | **FR-2.2.4改訂: エスカレーション選択肢と施策Cの自動アクションの関係を明記（自動アクションが先に判定→エスカレーションは別途）** |
| **§3.2 FR-2.3 記事フェーズ** | **D** | **FR-2.3.1改訂: Writerはstrategy.mdのpriority_style_categoriesでフィルタされたstyle_guide.mdを参照する** |
| §3.2 FR-2.4 記事PDCA | A,B,C | FR-2.4.7新設: Article UpdaterがFBへの対応可否レポートを出力する |
| | A | FR-2.4.8新設: 各イテレーションのReviewer FBをfb_log.jsonに構造化記録する |
| | B | FR-2.4.9新設: FB差分メトリクス（resolution_rate, persisted_count, new_count）でPDCA効果を測定する |
| | B | FR-2.4.10新設: major指摘が3回連続残存した場合、スコアベース停滞検出を待たずにエスカレーションする |
| | C | FR-2.4.5改訂: MATERIAL_ISSUE判定をUpdater対応可否レポートのcannot_resolve/material_shortageでも発火するよう拡張。**Reviewer起因とUpdater起因で同一カウンターを共有（合計1回）** |
| | **C** | **FR-2.4.4改訂: エスカレーション1回限りの定義に「cannot_resolve/strategy_levelはエスカレーション回数にカウントする。MATERIAL_ISSUEとADJUST_EVALの自動アクションはカウントしない」を明記** |
| §3.3 FR-3.2 Style Memory | D | FR-3.2.1改訂: style_guide.mdのルールに性質カテゴリタグ（rhythm, structure, distance, density, emotion, voice）を付与する |
| | D | FR-3.2.5新設: filter_style_rules(categories)で指定カテゴリのルールだけを抽出する機能を提供する。**該当0件時は全ルールにフォールバック** |
| | D | FR-3.2.6新設: Style Guide Updaterがルール追記時にカテゴリタグを自動付与する |
| **§3.3 FR-3.3 Agent Memory** | **A** | **FR-3.3.2改訂: 記録内容にfb_summary（最終resolution_rate、残存major指摘一覧）を追加** |
| §3.3 FR-3.6 実行履歴 | A | FR-3.6.1改訂: runs/{run_id}/の保存対象にfb_log.jsonを追加 |
| §4.3 品質基準 | B | NFR-08改訂: 「resolution_rateが実行回数を重ねるごとに改善傾向を示すこと」を追加 |
| §5.2 アウトプット | A | fb_log.json（素材PDCA + 記事PDCAの全イテレーションFB構造化ログ）を追加 |
| | C | updater_response.yaml（Updater対応可否レポート）を追加 |
| §5.3 蓄積データ | D | style_memory/style_guide.mdの説明に「性質カテゴリタグ付き」を追記 |
| §8 用語集 | A,B,C,D | fb_log、resolution_rate、対応可否レポート、性質カテゴリの定義を追加 |

### TECH_SPEC_v4_part1.md

| 修正箇所 | 施策 | 変更内容 |
|---|---|---|
| §1 フォルダ構成 | A | 実行時生成ファイルにfb_log.jsonを追加 |
| §2 Strategist | B | §2.2.2 エスカレーションモード入力にfb_diff（FB差分メトリクス）を追加 |
| | B | §2.2.3 振り返りモード入力にfb_log.jsonを追加。振り返り項目に「FB残存率の分析」を追加 |
| | **A** | **§2.2.4 フィードバックモード入力にruns/{run_id}/fb_log.jsonを追加（ユーザーFBの文脈理解に使用）** |
| | **D** | **§2.3.1 strategy.md出力フォーマットにpriority_style_categories（性質カテゴリのリスト）を追加** |
| §4 Eval Designer | B | §4.5 agent_memoryからの学習に「過去のfb_log.jsonでresolution_rateが低かった軸は重み調整を検討する」を追加 |
| | **D** | **§4.2 入力スキーマに「style_guide.mdは性質カテゴリタグ付きフォーマット」である旨を追記** |
| §5 agent_templates | A,C,D | §5.2 テンプレート一覧にMaterial Reviewer / Article Reviewerの出力フォーマットとして**JSON形式の**fb_log用構造化出力を追記。Material Updater / Article Updaterのテンプレートに**YAML形式の**対応可否レポート出力を追記。Style Guide Updaterのテンプレートにカテゴリタグ付与指示を追記 |

### TECH_SPEC_v4_part2.md

| 修正箇所 | 施策 | 変更内容 |
|---|---|---|
| §8.2 cmd_run | A | メインフローにfb_log初期化・保存ステップを追加 |
| **§8.3 cmd_feedback** | **A** | **runs/{run_id}/fb_log.jsonを読み込み、Strategistのフィードバックモード入力に渡す** |
| §8.4 RunState | A,B | RunStateにfb_log（dict）とfb_diff_history（list）フィールドを追加。**fb_logはRunState生成時に空dictで初期化** |
| §10 PDCAループ制御 | A,B,C | **大幅改訂** |
| §10.1 execute_pdca_loop | B | FB差分メトリクスによる停滞検出を既存のスコアベース停滞検出と併用するロジックを追加 |
| §10.3 check_stagnation | B | 新規: check_fb_stagnation(fb_log, window=3) — major指摘の残存率で停滞判定 |
| §10.5 run_iteration | A,C | 1イテレーションの処理フローを拡張（**素材PDCA・記事PDCAそれぞれのステップ順序を明記**）: (1) Reviewer → 構造化JSON出力 → record_fb_logでfb_log.jsonに記録 (2) スコア抽出 (3) Updater → 改善 + YAML形式の対応可否レポート出力 (4) parse_updater_responseで対応可否レポートを抽出 (5) cannot_resolveを判定 → handle_cannot_resolveで自動アクション |
| §10.7（新設） | A | **record_fb_log()**: Reviewer出力のJSON部分をパースしfb_logに追記する**確定ロジック**。ID付与・カテゴリ分類・解消判定はReviewerエージェントが行う前提 |
| §10.8（新設） | B | **compute_fb_diff()**: 2つのイテレーション間のFB差分を計算する**確定ロジック**（IDの文字列マッチとresolved判定の集計のみ） |
| §10.9（新設） | C | **parse_updater_response()**: Updater出力のYAML部分をパースする**確定ロジック**。action/reasonの分類はUpdaterエージェントが行う前提 |
| §10.10（新設） | C | **handle_cannot_resolve()**: cannot_resolveのreasonに基づく自動アクション分岐。**MATERIAL_ISSUEは既存の1回制限カウンターを共有。strategy_levelはエスカレーション回数にカウント。エスカレーション消費済みの場合は警告ログを出力してPDCA続行** |
| §11 エスカレーション | B,C | §11.1にFB差分起因のエスカレーショントリガーを追加。§11.3 handle_escalationの入力にfb_diffを追加。**§11.1に「cannot_resolve/strategy_levelはエスカレーション回数にカウントする。material_shortage/eval_mismatchの自動アクションはカウントしない」を明記** |
| ~~§14 自動メトリクスエンジン~~ | ~~B~~ | ~~§14.2にFB差分メトリクスを追加~~ **削除**: FB差分メトリクス（resolution_rate等）は§14（記事テキスト客観計測）ではなく§10内に配置する。§14はあくまで記事テキストのメトリクスに限定 |
| §15 プロンプト組み立て | A,B,C | §15.1 build_agent_prompt: Reviewer向けプロンプトに**直近3イテレーション分の**fb_logを付与。Updater向けプロンプトに「対応可否レポートを**YAML形式で**出力せよ」指示を付与 |
| | **D** | **§15.1 build_agent_prompt: Writer/Reviewer向けのstyle_guide.md読み込み時に、strategy.mdのpriority_style_categoriesを参照し、filter_style_rules()を適用してフィルタ済みルールを注入する** |
| | B | §15.2 build_escalation_prompt: fb_diff情報を含めるよう拡張 |
| §18 責任分担表 | A,B,C | **FB項目のID付与・カテゴリ分類・解消判定=Reviewerエージェント、FB構造化JSONのパース=コード（確定ロジック）**。対応可否の判断・reason分類=Updaterエージェント、**YAML出力のパース=コード（確定ロジック）**、cannot_resolve後のアクション分岐=コード（reasonの文字列マッチ）。**§18.3「境界のグレーゾーン」にこの分担を追記** |
| **§19 エラーハンドリング** | **A,B,C** | **§19.1にFBLogParseError（Reviewer構造化出力のパース失敗）とUpdaterResponseParseError（Updater対応可否レポートのパース失敗）を追加。§19.2に処理方針を追加: FBLogParseError→警告ログ出力、当該iterのfb_logエントリをスキップしてPDCA続行。UpdaterResponseParseError→警告ログ出力、全FBを「attempted」とみなしPDCA続行** |
| §20 実行履歴の保存 | A | §20.1 save_runの保存対象にfb_log.jsonを追加 |
| 付録B | A,B,C,D | 新規関数**6つ**（record_fb_log, compute_fb_diff, parse_updater_response, handle_cannot_resolve, **check_fb_stagnation, filter_style_rules**）を追加 |

### TECH_SPEC_v4_part3.md

| 修正箇所 | 施策 | 変更内容 |
|---|---|---|
| §22 Style Memory | D | **大幅改訂** |
| §22.1 概要 | D | 性質カテゴリタグの設計思想を追記。「語尾・視点だけでなく、リズム・構造・距離感・情報密度・感情設計を含む多角的な文体要素を管理する」 |
| §22.3 style_guide.mdの構造 | D | 新フォーマット定義。各ルールに[category]タグを必須化。カテゴリ一覧（rhythm, structure, distance, density, emotion, voice）を定義。**タグなしルールは[uncategorized]として扱う（v3.0マイグレーション対応）** |
| §22.4 IMPORTANTルール管理 | D | 退役判定は変更なし。カテゴリタグの引き継ぎルールを追記。**IMPORTANTルールの識別方法を明確化: `## IMPORTANT Rules` セクション配下を対象とする（カテゴリタグの有無に関わらない）** |
| §22.6（新設） | D | **filter_style_rules(categories)**: 指定カテゴリに一致するルールだけを抽出して返す。**該当0件の場合はフィルタなし（全ルール適用）にフォールバック** |
| §22.7（新設） | D | **カテゴリの拡張ルール**: 新カテゴリが必要な場合のガイドライン（コード変更不要でカテゴリ文字列を追加するだけ）。**マイグレーション手順: 既存のタグなしルールは[uncategorized]として扱い、Style Guide Updaterが次回更新時に適切なタグに置き換える** |
| §23 Agent Memory | A,B | §23.2 run_{timestamp}.yamlスキーマにfb_summary（最終resolution_rate、残存major指摘一覧）を追加 |
| §25 実行履歴 | A | §25.1にfb_log.jsonを追加。§25.2 scores.jsonと並行してfb_log.jsonの役割を説明 |
| | B | §25.3 summary.jsonにfb_resolution_rate（素材/記事各PDCA）を追加 |
| §31 テスト戦略 | A,B,C,D | §31.3にテストケース追加: record_fb_logの構造化抽出（**正常パース + FBLogParseError時のスキップ動作**）、compute_fb_diffの差分計算、parse_updater_responseのパース（**正常パース + UpdaterResponseParseError時のフォールバック動作**）、filter_style_rulesのフィルタリング（**該当0件時のフォールバック動作含む**）、check_fb_stagnationの停滞判定 |
| 付録D 上限管理一覧 | D | style_guide.mdの説明に「性質カテゴリタグ付き」を追記 |
| | **A** | **fb_log.jsonの注記を追加: 「1フェーズあたりのイテレーション数で自然に上限がかかる（素材: 最大5回、記事: 最大10回）。プロンプト注入時は直近3イテレーション分のみに制限」** |

### BUILD_GUIDE.md

| 修正箇所 | 施策 | 変更内容 |
|---|---|---|
| Phase 2（蓄積基盤） | D | スコープにstyle_guide.mdの性質タグフォーマット定義とfilter_style_rules()を追加。**マイグレーション対応（[uncategorized]タグのフォールバック処理）を含む** |
| ~~Phase 4（プロンプト・メトリクス）~~ | ~~A,B~~ | ~~スコープにrecord_fb_log()、compute_fb_diff()を追加~~ **削除**: record_fb_log()とcompute_fb_diff()は§10管轄のため**Phase 7で実装**する |
| Phase 4（プロンプト・メトリクス） | D | **スコープに「build_agent_promptでfilter_style_rules()を呼び出し、strategy.mdのpriority_style_categoriesでフィルタ済みルールをWriter/Reviewerに注入する」を追加** |
| Phase 5（MetaAgent層） | B,D | Strategistのエスカレーションモード入力にfb_diff追加を明記。**Strategistの出力にpriority_style_categoriesを追加。** Eval Designerの学習入力にfb_resolution_rate追加を明記。**Eval Designerの入力にタグ付きstyle_guide.mdフォーマットを明記** |
| Phase 7（PDCA） | A,B,C | **大幅改訂**。スコープに**record_fb_log()、compute_fb_diff()、check_fb_stagnation()、parse_updater_response()、handle_cannot_resolve()** を追加。FB差分メトリクスによる停滞検出、Updater対応可否レポートのパース・自動アクション分岐を追加。**MATERIAL_ISSUEカウンター共有ロジック、エスカレーション回数管理の拡張を含む**。完了チェックに「record_fb_logの構造化抽出テスト」「FB差分停滞検出のユニットテスト」「cannot_resolveアクション分岐のテスト」「**MATERIAL_ISSUE二重発火防止のテスト**」「**エスカレーション回数カウントのテスト**」を追加 |
| Phase 9（統合・CLI） | A | cmd_run内のfb_log初期化（**RunState生成時にfb_log={}**）・保存（**save_runでruns/{run_id}/fb_log.jsonに出力**）を統合フローに明記。**cmd_feedbackでruns/{run_id}/fb_log.jsonを読み込みStrategistに渡すフローを追加** |
| **Phase 10（堅牢化）** | **A,C** | **FBLogParseError、UpdaterResponseParseErrorの例外クラス追加。各エラー時のフォールバック処理を実装** |
| Phase 11（テスト） | A,B,C,D | 新規テストケース**6種**を追加（record_fb_log, compute_fb_diff, parse_updater_response, handle_cannot_resolve, check_fb_stagnation, filter_style_rules）。**各関数のエラーケース（パース失敗、該当0件等）のテストを含む** |
| ~~フェーズ依存関係図~~ | ~~—~~ | ~~Phase 4にfb_log基盤が入るため、Phase 7への依存が強化されることを注記~~ **削除**: fb_log関連関数はPhase 7に移動したため、既存の依存関係に変更なし |

---

## 実装の依存関係と推奨順序

```
施策D（style_guide.mdタグ化）← 独立して着手可能
  ↓ Phase 2で実装（フォーマット定義 + filter_style_rules + マイグレーション対応）
  ↓ Phase 4で統合（build_agent_promptでのフィルタ呼び出し）
  ↓ Phase 5で統合（Strategistのpriority_style_categories出力）

施策A（fb_log.json）← B, Cの基盤
施策B（FB差分メトリクス）← 施策Aに依存
施策C（Updater対応可否レポート）← 施策Aに依存
  ↓ Phase 7で一括実装（A, B, C全て）
  ↓ Phase 9で統合（cmd_run/cmd_feedbackへの組み込み）
  ↓ Phase 10で堅牢化（エラーハンドリング追加）
```

## 影響範囲まとめ

| ドキュメント | 新規セクション | 改訂セクション | 影響度 |
|---|---|---|---|
| REQUIREMENTS_v4.md | 0 | **13箇所** | **大** |
| TECH_SPEC_v4_part1.md | 0 | **7箇所** | 中 |
| TECH_SPEC_v4_part2.md | 4セクション新設 | **10箇所改訂** | **大** |
| TECH_SPEC_v4_part3.md | 2セクション新設 | **7箇所改訂** | 中 |
| BUILD_GUIDE.md | 0 | **7フェーズ改訂** | **大** |

---

## レビュー指摘への対応一覧

本計画書は以下の21件のレビュー指摘を反映済み。

| # | 指摘 | 対応 |
|---|---|---|
| 1 | cannot_resolveとエスカレーション1回限りの衝突 | 施策Cに回数カウントルール明記。FR-2.4.4改訂を追加 |
| 2 | MATERIAL_ISSUE差し戻しの二重発火 | 施策Cに同一カウンター共有を明記。FR-2.4.5改訂を拡張 |
| 3 | record_fb_log等の配置矛盾（Phase 4 vs Phase 7） | BUILD_GUIDEのPhase 4から削除、Phase 7に統一 |
| 4 | FB差分メトリクスを§14に混ぜる設計矛盾 | §14から削除、§10内に配置 |
| 5 | FR-1.1にpriority_style_categories未追加 | REQUIREMENTS修正計画にFR-1.1.1改訂を追加 |
| 6 | FR-1.3にタグ付きフォーマット未反映 | REQUIREMENTS修正計画にFR-1.3追記、TECH_SPEC §4.2追記を追加 |
| 7 | FR-2.3.1 Writerへのフィルタ済みルール未計画 | REQUIREMENTS修正計画にFR-2.3.1改訂を追加 |
| 8 | FR-3.3.2にfb_summary未追加（REQ側） | REQUIREMENTS修正計画にFR-3.3.2改訂を追加 |
| 9 | 素材PDCAにFB差分メトリクス未適用 | FR-2.2.7新設、FR-2.2.4改訂を追加 |
| 10 | cmd_feedbackがfb_log参照不可 | §8.3の修正計画を追加、Phase 9に反映 |
| 11 | Strategistフィードバックモードにfb_log未追加 | §2.2.4の修正計画を追加 |
| 12 | §15.1 build_agent_promptの施策D対応未計画 | §15.1にfilter_style_rules呼び出しの修正計画を追加 |
| 13 | count_important_rulesのパターンマッチ変更 | §22.4にセクションヘッダ基準の識別方法を明記 |
| 14 | 付録B新規関数が4つではなく6つ | 6関数に修正（check_fb_stagnation, filter_style_rules追加） |
| 15 | テンプレートに構造化出力形式の明示不足 | §5.2にJSON/YAML形式を明示 |
| 16 | record_fb_logパース失敗時の例外未定義 | §19にFBLogParseError追加 |
| 17 | parse_updater_responseパース失敗時の例外未定義 | §19にUpdaterResponseParseError追加 |
| 18 | filter_style_rules該当0件時の挙動未定義 | フィルタなしフォールバックを明記 |
| 19 | fb_log.jsonサイズ膨張→プロンプト圧迫 | 直近3イテレーション制限を明記、付録Dに注記追加 |
| 20 | 既存style_guide.mdのマイグレーション手順なし | [uncategorized]タグとStyle Guide Updaterの置き換えルールを追加 |
| 21 | FB項目ID付与・同一性判定の責任分担 | 施策Aに責任分担の原則を追記、§18修正に反映 |
