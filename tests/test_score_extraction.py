"""Tests for extract_overall_score and extract_axis_scores."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from orchestrator import extract_overall_score, extract_axis_scores, ScoreExtractionError


class TestExtractOverallScore:
    def test_basic_extraction(self, sample_review_text):
        assert extract_overall_score(sample_review_text) == 7.5

    def test_integer_score(self):
        text = "## Overall: 8/10\nSome text"
        assert extract_overall_score(text) == 8.0

    def test_decimal_score(self):
        text = "## Overall: 9.2/10\nSome text"
        assert extract_overall_score(text) == 9.2

    def test_zero_score(self):
        text = "## Overall: 0/10\n"
        assert extract_overall_score(text) == 0.0

    def test_perfect_score(self):
        text = "## Overall: 10/10\n"
        assert extract_overall_score(text) == 10.0

    def test_missing_score_raises(self):
        with pytest.raises(ScoreExtractionError, match="Overall score not found"):
            extract_overall_score("No score here")

    def test_wrong_format_raises(self):
        with pytest.raises(ScoreExtractionError):
            extract_overall_score("Overall: 8/10")  # missing ##

    def test_score_in_middle_of_text(self):
        text = "Some preamble\n\n## Overall: 6.5/10\n\nMore text after"
        assert extract_overall_score(text) == 6.5


class TestExtractAxisScores:
    def test_basic_extraction(self, sample_review_text):
        scores = extract_axis_scores(sample_review_text)
        assert scores["構成"] == 8.0
        assert scores["文体"] == 7.0
        assert scores["技術深度"] == 7.5

    def test_empty_text(self):
        assert extract_axis_scores("") == {}

    def test_no_axis_scores(self):
        text = "## Overall: 8/10\nNo axis scores here"
        assert extract_axis_scores(text) == {}

    def test_single_axis(self):
        text = "### S1. リズム: 9.0/10\nGood rhythm"
        scores = extract_axis_scores(text)
        assert scores == {"リズム": 9.0}

    def test_a_prefix_axes(self):
        text = "### A1. 独自性: 8.5/10\n### A2. 実用性: 7.0/10\n"
        scores = extract_axis_scores(text)
        assert scores["独自性"] == 8.5
        assert scores["実用性"] == 7.0

    def test_mixed_s_and_a(self):
        text = "### S1. 構成: 8.0/10\n### A1. 深度: 7.0/10\n"
        scores = extract_axis_scores(text)
        assert len(scores) == 2
        assert "構成" in scores
        assert "深度" in scores
