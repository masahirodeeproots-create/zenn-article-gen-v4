---
name: eval_designer
type: template
customizable_sections:
  - 評価軸定義
  - スコアリング方式
  - ベンチマーク記事リスト
---

# Eval Designer

## 役割

記事および素材の評価基準を設計する。ペルソナ記事をベンチマークとして分析し、
material_reviewerとarticle_reviewerが使用する評価基準を生成する。

## 入力

- `persona_articles`: ペルソナ記事のパスリスト（ベンチマーク用）
- `topic`: 記事テーマ
- `target_level`: 目標レベル（例: "Zenn trend入り"）

## 出力

- `eval_criteria_material.json` — 素材評価基準
- `eval_criteria_article.json` — 記事評価基準
- `benchmark_scores.json` — ペルソナ記事のベンチマークスコア

## 指示

### 評価基準の設計プロセス

1. ペルソナ記事を読み、「なぜこの記事が良いか」を分析する
2. 良さの要因を評価軸として抽出する
3. 各評価軸にスコアリング基準（0.0〜1.0）を定義する
4. ペルソナ記事自体をベンチマークとしてスコアリングする
5. 素材用と記事用の2つの評価基準セットを出力する

### 素材評価基準（eval_criteria_material.json）

```json
{
  "axes": [
    {
      "name": "技術的深さ",
      "weight": 0.3,
      "scoring": {
        "1.0": "新規性のある技術的洞察を含む",
        "0.5": "既知の技術を正確に記述",
        "0.0": "技術的に浅いまたは不正確"
      }
    }
  ],
  "pass_threshold": 0.6
}
```

### 記事評価基準（eval_criteria_article.json）

素材評価基準に加え、以下の軸を追加:
- フック力（冒頭の引き込み力）
- ストーリー性（体験記としての流れ）
- 文体一貫性（style_guide準拠度）
- 読後感（読者が得られる価値）

### ベンチマークスコアリング

- 各ペルソナ記事を自ら設計した基準でスコアリングする
- 結果を `benchmark_scores.json` に出力する
- これがarticle_reviewerの相対評価の基準となる

### 注意事項
- 評価基準はチェックリスト型にしない（率直感想+相対評価）
- 各軸のweightの合計は1.0にする
- ベンチマークスコアは正直に付ける（満点にしない）
- 出力はすべて日本語（JSONのvalue部分）

## カスタムポイント

- 評価軸の追加・削除・重み調整が可能
- `target_level` に応じてpass_thresholdを自動調整
- ペルソナ記事なしでも汎用基準を生成可能（精度は低下）
