"""Tests for check_stagnation, consecutive_above_threshold, check_fb_stagnation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from orchestrator import check_stagnation, consecutive_above_threshold, check_fb_stagnation


class TestCheckStagnation:
    def test_stagnant_scores(self):
        assert check_stagnation([7.0, 7.1, 7.0], window=3, tolerance=0.5) is True

    def test_improving_scores(self):
        assert check_stagnation([6.0, 7.0, 8.0], window=3, tolerance=0.5) is False

    def test_too_few_scores(self):
        assert check_stagnation([7.0, 7.1], window=3, tolerance=0.5) is False

    def test_exact_tolerance(self):
        # max - min == 0.5, which is <= tolerance
        assert check_stagnation([7.0, 7.5, 7.2], window=3, tolerance=0.5) is True

    def test_just_above_tolerance(self):
        assert check_stagnation([7.0, 7.6, 7.0], window=3, tolerance=0.5) is False

    def test_window_only_looks_at_recent(self):
        # Early improvement, then stagnation in last 3
        assert check_stagnation([5.0, 6.0, 7.0, 7.1, 7.0], window=3, tolerance=0.5) is True

    def test_single_score(self):
        assert check_stagnation([7.0], window=3) is False

    def test_empty_scores(self):
        assert check_stagnation([], window=3) is False


class TestConsecutiveAboveThreshold:
    def test_two_above(self):
        assert consecutive_above_threshold([7.0, 9.5, 9.2], threshold=9.0) is True

    def test_one_above(self):
        assert consecutive_above_threshold([7.0, 8.5, 9.5], threshold=9.0) is False

    def test_equal_to_threshold_not_above(self):
        # > threshold, not >=
        assert consecutive_above_threshold([9.0, 9.0], threshold=9.0) is False

    def test_all_above(self):
        assert consecutive_above_threshold([9.5, 9.5, 9.5], threshold=9.0) is True

    def test_too_few_scores(self):
        assert consecutive_above_threshold([9.5], threshold=9.0) is False

    def test_empty_scores(self):
        assert consecutive_above_threshold([], threshold=9.0) is False

    def test_custom_required(self):
        assert consecutive_above_threshold([9.5, 9.5, 9.5], threshold=9.0, required=3) is True
        assert consecutive_above_threshold([9.5, 9.5], threshold=9.0, required=3) is False

    def test_non_consecutive_not_counted(self):
        # Last 2 must be above; here index -2 is 8.5
        assert consecutive_above_threshold([9.5, 8.5, 9.5], threshold=9.0) is False


class TestCheckFBStagnation:
    def test_stagnation_detected(self):
        fb_log = {
            "iterations": [
                {"iteration": 1, "issues": [
                    {"id": "i1", "severity": "major", "resolved": False},
                ]},
                {"iteration": 2, "issues": [
                    {"id": "i1", "severity": "major", "resolved": False},
                ]},
                {"iteration": 3, "issues": [
                    {"id": "i1", "severity": "major", "resolved": False},
                ]},
            ]
        }
        assert check_fb_stagnation(fb_log, window=3) is True

    def test_no_stagnation_when_resolved(self):
        fb_log = {
            "iterations": [
                {"iteration": 1, "issues": [
                    {"id": "i1", "severity": "major", "resolved": False},
                ]},
                {"iteration": 2, "issues": [
                    {"id": "i1", "severity": "major", "resolved": True},
                ]},
                {"iteration": 3, "issues": [
                    {"id": "i2", "severity": "major", "resolved": False},
                ]},
            ]
        }
        assert check_fb_stagnation(fb_log, window=3) is False

    def test_too_few_iterations(self):
        fb_log = {"iterations": [
            {"iteration": 1, "issues": [{"id": "i1", "severity": "major", "resolved": False}]},
        ]}
        assert check_fb_stagnation(fb_log, window=3) is False

    def test_empty_fb_log(self):
        assert check_fb_stagnation({}, window=3) is False

    def test_only_minor_issues_no_stagnation(self):
        fb_log = {
            "iterations": [
                {"iteration": i, "issues": [
                    {"id": "i1", "severity": "minor", "resolved": False},
                ]}
                for i in range(1, 4)
            ]
        }
        assert check_fb_stagnation(fb_log, window=3) is False

    def test_mixed_major_minor(self):
        fb_log = {
            "iterations": [
                {"iteration": i, "issues": [
                    {"id": "i1", "severity": "major", "resolved": False},
                    {"id": "i2", "severity": "minor", "resolved": False},
                ]}
                for i in range(1, 4)
            ]
        }
        assert check_fb_stagnation(fb_log, window=3) is True

    def test_no_issues(self):
        fb_log = {
            "iterations": [
                {"iteration": i, "issues": []}
                for i in range(1, 4)
            ]
        }
        assert check_fb_stagnation(fb_log, window=3) is False
