"""Tests for CLI argument parsing."""

import argparse
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import orchestrator


class TestCLIParsing:
    def _parse(self, args):
        parser = argparse.ArgumentParser(description="Zenn Article Generator v4.0")
        subparsers = parser.add_subparsers(dest="command")

        rp = subparsers.add_parser("run")
        rp.add_argument("--source", required=True)
        rp.add_argument("--instruction", required=True)
        rp.add_argument("--model", default="sonnet")

        fp = subparsers.add_parser("feedback")
        fp.add_argument("run_id")
        fp.add_argument("feedback_text")

        hp = subparsers.add_parser("history")
        hp.add_argument("--limit", type=int, default=10)
        hp.add_argument("--detail", action="store_true")

        return parser.parse_args(args)

    def test_run_command(self):
        args = self._parse(["run", "--source", "src/", "--instruction", "write article"])
        assert args.command == "run"
        assert args.source == "src/"
        assert args.instruction == "write article"
        assert args.model == "sonnet"

    def test_run_custom_model(self):
        args = self._parse(["run", "--source", "s", "--instruction", "i", "--model", "opus"])
        assert args.model == "opus"

    def test_feedback_command(self):
        args = self._parse(["feedback", "20260413_120000", "good article"])
        assert args.command == "feedback"
        assert args.run_id == "20260413_120000"
        assert args.feedback_text == "good article"

    def test_history_command(self):
        args = self._parse(["history"])
        assert args.command == "history"
        assert args.limit == 10
        assert args.detail is False

    def test_history_with_options(self):
        args = self._parse(["history", "--limit", "5", "--detail"])
        assert args.limit == 5
        assert args.detail is True

    def test_no_command(self):
        args = self._parse([])
        assert args.command is None

    def test_run_missing_source(self):
        with pytest.raises(SystemExit):
            self._parse(["run", "--instruction", "test"])

    def test_run_missing_instruction(self):
        with pytest.raises(SystemExit):
            self._parse(["run", "--source", "src/"])


class TestMainDispatch:
    @patch("orchestrator.cmd_run")
    @patch("orchestrator.validate_source_files")
    def test_main_run(self, mock_validate, mock_run):
        mock_validate.return_value = Path("/tmp/src")
        mock_run.return_value = "20260413_120000"
        with patch("sys.argv", ["prog", "run", "--source", "/tmp/src", "--instruction", "test"]):
            orchestrator.main()
        mock_run.assert_called_once_with("/tmp/src", "test", "sonnet")

    @patch("orchestrator.cmd_feedback")
    def test_main_feedback(self, mock_fb):
        with patch("sys.argv", ["prog", "feedback", "run123", "nice work"]):
            orchestrator.main()
        mock_fb.assert_called_once_with("run123", "nice work")

    @patch("orchestrator.cmd_history")
    def test_main_history(self, mock_hist):
        with patch("sys.argv", ["prog", "history", "--limit", "5"]):
            orchestrator.main()
        mock_hist.assert_called_once_with(5, False)

    @patch("orchestrator.cmd_history")
    def test_main_history_detail(self, mock_hist):
        with patch("sys.argv", ["prog", "history", "--detail"]):
            orchestrator.main()
        mock_hist.assert_called_once_with(10, True)

    def test_main_no_args(self, capsys):
        with patch("sys.argv", ["prog"]):
            orchestrator.main()
        captured = capsys.readouterr()
        assert "usage" in captured.out.lower() or captured.out == ""
