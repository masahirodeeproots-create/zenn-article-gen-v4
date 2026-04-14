"""Tests for record_fb_log, compute_fb_diff."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from orchestrator import record_fb_log, compute_fb_diff, FBLogParseError, RunState


class TestRecordFBLog:
    def test_basic_record(self, sample_run_state):
        review = '```json\n{"issues": [{"id": "i1", "severity": "major", "resolved": false}]}\n```'
        record_fb_log(review, "article_review", 1, sample_run_state)
        assert "article_review" in sample_run_state.fb_log
        iters = sample_run_state.fb_log["article_review"]["iterations"]
        assert len(iters) == 1
        assert iters[0]["iteration"] == 1
        assert len(iters[0]["issues"]) == 1

    def test_no_json_block_raises(self, sample_run_state):
        with pytest.raises(FBLogParseError, match="No JSON block"):
            record_fb_log("No json here", "article_review", 1, sample_run_state)

    def test_invalid_json_raises(self, sample_run_state):
        review = '```json\n{bad json}\n```'
        with pytest.raises(FBLogParseError, match="JSON parse failed"):
            record_fb_log(review, "article_review", 1, sample_run_state)

    def test_multiple_iterations(self, sample_run_state):
        for i in range(1, 4):
            review = f'```json\n{{"issues": [{{"id": "i{i}", "severity": "major", "resolved": false}}]}}\n```'
            record_fb_log(review, "article_review", i, sample_run_state)
        iters = sample_run_state.fb_log["article_review"]["iterations"]
        assert len(iters) == 3

    def test_missing_issues_key(self, sample_run_state):
        review = '```json\n{"other": "data"}\n```'
        record_fb_log(review, "article_review", 1, sample_run_state)
        iters = sample_run_state.fb_log["article_review"]["iterations"]
        assert iters[0]["issues"] == []

    def test_different_phases(self, sample_run_state):
        review = '```json\n{"issues": []}\n```'
        record_fb_log(review, "material_review", 1, sample_run_state)
        record_fb_log(review, "article_review", 1, sample_run_state)
        assert "material_review" in sample_run_state.fb_log
        assert "article_review" in sample_run_state.fb_log

    def test_json_in_larger_text(self, sample_run_state):
        review = 'Some review text\n\n```json\n{"issues": [{"id": "x1", "severity": "minor", "resolved": true}]}\n```\n\nMore text'
        record_fb_log(review, "article_review", 1, sample_run_state)
        issues = sample_run_state.fb_log["article_review"]["iterations"][0]["issues"]
        assert len(issues) == 1
        assert issues[0]["id"] == "x1"


class TestComputeFBDiff:
    def test_basic_diff(self, sample_fb_log):
        diff = compute_fb_diff(sample_fb_log, 1, 2)
        assert "a1_001" in diff["resolved"]
        assert "s1_001" in diff["persisted"]
        assert "s3_001" in diff["new"]

    def test_resolution_rate(self, sample_fb_log):
        diff = compute_fb_diff(sample_fb_log, 1, 2)
        # a_unresolved in iter1: s1_001, s2_001, a1_001 (3 items)
        # b_resolved in iter2: s2_001, a1_001 (2 items)
        # resolved = a_unresolved & b_resolved = {s2_001, a1_001}? No.
        # Wait: s2_001 is minor in iter1 but still unresolved.
        # a_unresolved = {i for i in iter1 issues if not resolved} = {s1_001, s2_001, a1_001}
        # b_resolved = {i for i in iter2 issues if resolved} = {s2_001, a1_001}
        # resolved = a_unresolved & b_resolved = {s2_001, a1_001}
        # persisted = a_unresolved & b_unresolved = a_unresolved & {s1_001, s3_001} = {s1_001}
        # total = len(resolved) + len(persisted) = 2 + 1 = 3
        # rate = 2 / 3
        assert abs(diff["resolution_rate"] - 2/3) < 0.01

    def test_missing_iteration(self, sample_fb_log):
        diff = compute_fb_diff(sample_fb_log, 1, 99)
        assert diff["resolution_rate"] == 1.0
        assert diff["resolved"] == []

    def test_empty_fb_log(self):
        diff = compute_fb_diff({}, 1, 2)
        assert diff["resolution_rate"] == 1.0

    def test_all_resolved(self):
        fb_log = {
            "iterations": [
                {"iteration": 1, "issues": [
                    {"id": "i1", "resolved": False},
                ]},
                {"iteration": 2, "issues": [
                    {"id": "i1", "resolved": True},
                ]},
            ]
        }
        diff = compute_fb_diff(fb_log, 1, 2)
        assert diff["resolved"] == ["i1"]
        assert diff["persisted"] == []
        assert diff["resolution_rate"] == 1.0

    def test_no_overlap(self):
        fb_log = {
            "iterations": [
                {"iteration": 1, "issues": [
                    {"id": "i1", "resolved": False},
                ]},
                {"iteration": 2, "issues": [
                    {"id": "i2", "resolved": False},
                ]},
            ]
        }
        diff = compute_fb_diff(fb_log, 1, 2)
        assert diff["resolved"] == []
        assert diff["persisted"] == []
        assert "i2" in diff["new"]
