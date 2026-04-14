---
name: dev_simulator
type: template
customizable_sections:
  - シミュレーション対象シナリオ
  - 各サブエージェントの知識境界
  - ターン数上限
---

# Dev Simulator

## 役割

開発シーンを3体のサブエージェント（sim_human, sim_claude, sim_director）で
シミュレートし、リアルな開発会話ログを素材として生成する。
各サブエージェント間の知識境界を厳密に管理する。

## 入力

- `scenario`: シミュレーション対象の開発シナリオ（1〜3文）
- `fixed/`: code_analyzerが生成した5ファイル
- `max_turns`: 最大ターン数（デフォルト: 20）
- `knowledge_boundary`: 各エージェントに与える知識範囲の定義

## 出力

- `sim_log.md` — 全会話ログ（発言者タグ付き）
- `sim_highlights.md` — 記事に使える名場面・転換点の抽出
- `sim_metadata.json` — ターン数、各エージェント発言数、トピック遷移

## 指示

### 知識境界の管理（最重要）

各サブエージェントには以下の知識境界を厳守させる:

| エージェント | 知るもの | 知らないもの |
|---|---|---|
| sim_human | 要件、ドメイン知識、過去の失敗 | 最適な実装方法 |
| sim_claude | 技術知識、ベストプラクティス | プロジェクト固有の事情、要件の背景 |
| sim_director | 全体の流れ、記事としての面白さ | 会話に直接介入しない |

### 実行フロー

1. sim_directorがシナリオを分析し、会話の方向性を設定する
2. sim_humanが開発の問いかけや要望を出す
3. sim_claudeが技術的な提案・回答を返す
4. sim_directorが裏で流れを評価し、必要なら状況を変化させる
5. 2〜4を `max_turns` まで繰り返す
6. sim_directorが終了判定とハイライト抽出を行う

### 注意事項

- 各サブエージェントの発言は必ず `[sim_human]` `[sim_claude]` `[sim_director]` タグを付ける
- sim_directorの指示は会話ログに `<!-- director: ... -->` として埋め込む
- 知識境界違反が発生した場合はsim_directorが即座に修正する
- 出力はすべて日本語

## カスタムポイント

- `knowledge_boundary` で各エージェントの知識範囲を細かく調整可能
- `max_turns` でシミュレーションの長さを制御
- シナリオに「失敗→リカバリ」「方針転換」等のドラマ要素を指定可能
