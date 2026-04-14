"""Tests for parse_updater_response, handle_cannot_resolve."""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from orchestrator import (
    parse_updater_response,
    handle_cannot_resolve,
    UpdaterResponseParseError,
    RunState,
    AgentRegistry,
)


class TestParseUpdaterResponse:
    def test_basic_parse_json_fallback(self):
        """When yaml is not available, falls back to JSON parsing."""
        output = '```yaml\n{"response_report": [{"action": "resolved", "id": "i1"}]}\n```'
        result = parse_updater_response(output)
        assert len(result) == 1
        assert result[0]["action"] == "resolved"

    def test_no_yaml_block_raises(self):
        with pytest.raises(UpdaterResponseParseError, match="No YAML block"):
            parse_updater_response("No yaml here")

    def test_invalid_content_raises(self):
        output = '```yaml\n{{{invalid\n```'
        with pytest.raises(UpdaterResponseParseError):
            parse_updater_response(output)

    def test_empty_report(self):
        output = '```yaml\n{"response_report": []}\n```'
        result = parse_updater_response(output)
        assert result == []

    def test_missing_response_report_key(self):
        output = '```yaml\n{"other_key": "value"}\n```'
        result = parse_updater_response(output)
        assert result == []

    def test_multiple_items(self):
        data = {"response_report": [
            {"action": "resolved", "id": "i1"},
            {"action": "cannot_resolve", "id": "i2", "reason": "material_shortage"},
        ]}
        output = f'```yaml\n{json.dumps(data)}\n```'
        result = parse_updater_response(output)
        assert len(result) == 2

    def test_non_dict_returns_empty(self):
        output = '```yaml\n["list", "not", "dict"]\n```'
        result = parse_updater_response(output)
        assert result == []


class TestHandleCannotResolve:
    @patch("orchestrator.execute_pdca_loop")
    @patch("orchestrator.load_workflow")
    def test_material_shortage_triggers_fallback(self, mock_load_wf, mock_pdca, project_root, sample_run_state):
        mock_load_wf.return_value = {"phases": [
            {"name": "material_review", "agents": [], "loop": True, "max_iterations": 3,
             "stagnation_window": 3, "stagnation_tolerance": 0.5},
        ]}

        actions = [{"action": "cannot_resolve", "reason": "material_shortage"}]
        phase = {"name": "article_review", "agents": ["writer"], "loop": True,
                 "max_iterations": 5, "stagnation_window": 3, "stagnation_tolerance": 0.5}
        registry = AgentRegistry()

        handle_cannot_resolve(actions, phase, registry, sample_run_state)
        assert sample_run_state.material_fallback_count.get("article_review") == 1
        mock_pdca.assert_called_once()

    @patch("orchestrator.call_agent_with_retry")
    def test_eval_mismatch(self, mock_call, project_root, sample_run_state):
        mock_call.return_value = "adjusted eval"
        (project_root / "eval_criteria.md").write_text("# Eval")
        (project_root / "agent_memory").mkdir(parents=True, exist_ok=True)

        actions = [{"action": "cannot_resolve", "reason": "eval_mismatch"}]
        phase = {"name": "article_review", "agents": ["writer"], "loop": True,
                 "max_iterations": 5}
        registry = AgentRegistry()
        handle_cannot_resolve(actions, phase, registry, sample_run_state)
        mock_call.assert_called_once()

    @patch("orchestrator.handle_escalation")
    def test_strategy_level_escalates(self, mock_esc, project_root, sample_run_state):
        actions = [{"action": "cannot_resolve", "reason": "strategy_level"}]
        phase = {"name": "article_review", "agents": [], "loop": True, "max_iterations": 5}
        registry = AgentRegistry()
        handle_cannot_resolve(actions, phase, registry, sample_run_state)
        assert sample_run_state.is_escalated("article_review") is True
        mock_esc.assert_called_once()

    def test_strategy_level_already_escalated(self, project_root, sample_run_state):
        sample_run_state.mark_escalated("article_review")
        actions = [{"action": "cannot_resolve", "reason": "strategy_level"}]
        phase = {"name": "article_review", "agents": [], "loop": True, "max_iterations": 5}
        registry = AgentRegistry()
        handle_cannot_resolve(actions, phase, registry, sample_run_state)
        assert "[article_review] strategy_level but escalation used" in sample_run_state.log[-1]

    @patch("orchestrator.handle_escalation")
    def test_material_shortage_second_time_escalates(self, mock_esc, project_root, sample_run_state):
        # Already used fallback once
        sample_run_state.material_fallback_count["article_review"] = 1
        actions = [{"action": "cannot_resolve", "reason": "material_shortage"}]
        phase = {"name": "article_review", "agents": [], "loop": True, "max_iterations": 5}
        registry = AgentRegistry()
        handle_cannot_resolve(actions, phase, registry, sample_run_state)
        assert sample_run_state.is_escalated("article_review") is True
        mock_esc.assert_called_once()
