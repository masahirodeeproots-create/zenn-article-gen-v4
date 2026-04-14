"""Tests for compute_* functions and build_metrics_context."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from orchestrator import (
    compute_code_ratio,
    compute_desu_masu_ratio,
    compute_section_length_ratio,
    compute_max_consecutive_same_band,
    compute_sentence_length_stddev,
    compute_total_chars,
    compute_metrics,
    build_metrics_context,
)


class TestComputeCodeRatio:
    def test_no_code(self):
        assert compute_code_ratio("Hello\nWorld\n") == 0.0

    def test_all_code(self):
        text = "```\nline1\nline2\nline3\n```"
        ratio = compute_code_ratio(text)
        # 5 lines total, 3 are code lines (line1, line2, line3), fences not counted
        assert ratio == 3 / 5

    def test_mixed(self):
        text = "intro\n```\ncode\n```\noutro"
        ratio = compute_code_ratio(text)
        assert ratio == 1 / 5

    def test_empty_text(self):
        assert compute_code_ratio("") == 0.0

    def test_multiple_blocks(self):
        text = "text\n```\na\n```\ntext\n```\nb\n```"
        ratio = compute_code_ratio(text)
        # 8 lines, code lines = a, b = 2
        assert ratio == 2 / 8


class TestComputeDesuMasuRatio:
    def test_all_desu_masu(self):
        text = "これはテストです。問題ありません。実行しました。"
        ratio = compute_desu_masu_ratio(text)
        assert ratio == 1.0

    def test_no_desu_masu(self):
        text = "これはテストだ。問題ない。実行した。"
        ratio = compute_desu_masu_ratio(text)
        assert ratio == 0.0

    def test_mixed(self):
        text = "これはテストです。問題ないよこれは。実行しました。"
        ratio = compute_desu_masu_ratio(text)
        # 3 sentences, 2 end with desu/masu => 2/3
        # Note: sentences must be > 5 chars to count
        assert 0.0 < ratio < 1.0

    def test_empty_text(self):
        # No sentences > 5 chars, returns 1.0
        assert compute_desu_masu_ratio("") == 1.0

    def test_short_sentences_ignored(self):
        text = "あ。い。う。"
        assert compute_desu_masu_ratio(text) == 1.0


class TestComputeSectionLengthRatio:
    def test_equal_sections(self):
        text = "## Section 1\nline1\nline2\n## Section 2\nline1\nline2"
        ratio = compute_section_length_ratio(text)
        assert ratio == 1.0

    def test_unequal_sections(self):
        text = "## Short\nline\n## Long\nline1\nline2\nline3\nline4"
        ratio = compute_section_length_ratio(text)
        assert ratio > 1.0

    def test_single_section(self):
        text = "## Only\nline1\nline2"
        assert compute_section_length_ratio(text) == 1.0

    def test_no_sections(self):
        assert compute_section_length_ratio("just text") == 1.0


class TestComputeMaxConsecutiveSameBand:
    def test_varied_lengths(self):
        # short, medium, long alternating
        text = "短い文。" + "これは中くらいの長さの文章であり少し長い。" + "この文はとても長くて五十文字を超えるように書かれた非常に詳細な技術的説明を含む文章です。"
        result = compute_max_consecutive_same_band(text)
        assert result >= 1

    def test_all_same_band(self):
        # All short sentences
        text = "短い。次も短い。これも短。また短い。短文だ。"
        result = compute_max_consecutive_same_band(text)
        assert result >= 2

    def test_empty_text(self):
        assert compute_max_consecutive_same_band("") == 0

    def test_single_sentence(self):
        text = "これは一文です。"
        result = compute_max_consecutive_same_band(text)
        assert result == 1


class TestComputeSentenceLengthStddev:
    def test_uniform_length(self):
        text = "ああああああ。ああああああ。ああああああ。"
        stddev = compute_sentence_length_stddev(text)
        assert stddev == 0.0

    def test_varied_length(self):
        # Need sentences > 3 chars after strip. Use period as separator.
        text = "これは短い文章。これはかなり長くて詳細な技術的説明を含む文章になっている。また短い。"
        stddev = compute_sentence_length_stddev(text)
        assert stddev > 0.0

    def test_empty_text(self):
        assert compute_sentence_length_stddev("") == 0.0

    def test_single_sentence(self):
        assert compute_sentence_length_stddev("一文だけです。") == 0.0


class TestComputeTotalChars:
    def test_basic(self):
        assert compute_total_chars("hello") == 5

    def test_empty(self):
        assert compute_total_chars("") == 0

    def test_unicode(self):
        assert compute_total_chars("あいう") == 3


class TestComputeMetrics:
    def test_returns_all_keys(self):
        metrics = compute_metrics("テスト文章です。\n```\ncode\n```\n")
        expected_keys = {
            "code_ratio", "desu_masu_ratio", "section_length_ratio",
            "max_consecutive_same_band", "sentence_length_stddev", "total_chars",
        }
        assert set(metrics.keys()) == expected_keys


class TestBuildMetricsContext:
    def test_no_warnings(self):
        metrics = {"code_ratio": 0.1, "desu_masu_ratio": 0.9, "max_consecutive_same_band": 3}
        assert build_metrics_context(metrics) == ""

    def test_code_ratio_warning(self):
        metrics = {"code_ratio": 0.3, "desu_masu_ratio": 0.9, "max_consecutive_same_band": 3}
        result = build_metrics_context(metrics)
        assert "コード比率" in result

    def test_desu_masu_warning(self):
        metrics = {"code_ratio": 0.1, "desu_masu_ratio": 0.5, "max_consecutive_same_band": 3}
        result = build_metrics_context(metrics)
        assert "です・ます比率" in result

    def test_consecutive_band_warning(self):
        metrics = {"code_ratio": 0.1, "desu_masu_ratio": 0.9, "max_consecutive_same_band": 6}
        result = build_metrics_context(metrics)
        assert "連続同長文帯" in result

    def test_multiple_warnings(self):
        metrics = {"code_ratio": 0.3, "desu_masu_ratio": 0.5, "max_consecutive_same_band": 6}
        result = build_metrics_context(metrics)
        assert "コード比率" in result
        assert "です・ます比率" in result
        assert "連続同長文帯" in result
