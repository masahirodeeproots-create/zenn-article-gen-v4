"""Tests for validate_agents, validate_and_fix_agents."""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from orchestrator import (
    validate_agents,
    validate_and_fix_agents,
    AgentValidationError,
    RunState,
)


class TestValidateAgents:
    def test_valid_agents(self, project_root):
        gen_dir = project_root / "agents" / "generated"
        gen_dir.mkdir(parents=True, exist_ok=True)

        # A generated agent with all required sections
        (gen_dir / "custom_agent.md").write_text(
            "---\nname: custom_agent\nbase_template: null\ntype: generated\nphase: test\n---\n\n"
            "# custom_agent\n\n## 役割\nDoes things\n\n## 入力\nGets input\n\n## 出力\nProduces output\n\n## 指示\nDo task\n"
        )

        # Valid workflow
        wf = {"phases": [{"name": "test", "agents": ["custom_agent"]}]}
        (gen_dir / "workflow.json").write_text(json.dumps(wf))

        errors = validate_agents()
        assert errors == []

    def test_missing_section_in_generated(self, project_root):
        gen_dir = project_root / "agents" / "generated"
        gen_dir.mkdir(parents=True, exist_ok=True)

        # Missing "## 指示" section
        (gen_dir / "bad_agent.md").write_text(
            "---\nname: bad_agent\nbase_template: null\ntype: generated\nphase: test\n---\n\n"
            "# bad_agent\n\n## 役割\nDoes things\n\n## 入力\nGets input\n\n## 出力\nProduces output\n"
        )

        wf = {"phases": [{"name": "test", "agents": ["bad_agent"]}]}
        (gen_dir / "workflow.json").write_text(json.dumps(wf))

        errors = validate_agents()
        assert any("missing section '## 指示'" in e for e in errors)

    def test_missing_workflow(self, project_root):
        gen_dir = project_root / "agents" / "generated"
        gen_dir.mkdir(parents=True, exist_ok=True)
        errors = validate_agents()
        assert any("workflow.json not found" in e for e in errors)

    def test_invalid_workflow_json(self, project_root):
        gen_dir = project_root / "agents" / "generated"
        gen_dir.mkdir(parents=True, exist_ok=True)
        (gen_dir / "workflow.json").write_text("{bad json")
        errors = validate_agents()
        assert any("invalid JSON" in e for e in errors)

    def test_template_based_agent_no_section_check(self, project_root):
        gen_dir = project_root / "agents" / "generated"
        gen_dir.mkdir(parents=True, exist_ok=True)

        # A template-based agent (no "base_template: null" or "type: generated")
        (gen_dir / "writer.md").write_text(
            "---\nname: writer\nbase_template: writer_base\ntype: template\nphase: article\n---\n\n"
            "# writer\nJust a basic writer.\n"
        )
        wf = {"phases": [{"name": "article", "agents": ["writer"]}]}
        (gen_dir / "workflow.json").write_text(json.dumps(wf))

        errors = validate_agents()
        # Should not complain about missing sections for template-based agents
        assert not any("V3:" in e for e in errors)

    def test_workflow_validation_errors(self, project_root):
        gen_dir = project_root / "agents" / "generated"
        gen_dir.mkdir(parents=True, exist_ok=True)
        wf = {"phases": [{"name": "test", "agents": ["missing_agent"]}]}
        (gen_dir / "workflow.json").write_text(json.dumps(wf))
        errors = validate_agents()
        assert any("missing_agent" in e for e in errors)

    def test_skips_workflow_json_file(self, project_root):
        gen_dir = project_root / "agents" / "generated"
        gen_dir.mkdir(parents=True, exist_ok=True)
        # workflow.json shouldn't be checked as an agent
        wf = {"phases": []}
        (gen_dir / "workflow.json").write_text(json.dumps(wf))
        errors = validate_agents()
        assert errors == []


class TestValidateAndFixAgents:
    @patch("orchestrator.validate_agents")
    def test_passes_on_first_try(self, mock_validate, project_root, sample_run_state):
        mock_validate.return_value = []
        validate_and_fix_agents(sample_run_state)
        mock_validate.assert_called_once()

    @patch("orchestrator.call_agent_with_retry")
    @patch("orchestrator.validate_agents")
    def test_fixes_on_retry(self, mock_validate, mock_call, project_root, sample_run_state):
        mock_validate.side_effect = [
            ["error1", "error2"],  # First call: errors
            [],                     # Second call: no errors
        ]
        mock_call.return_value = "fixed"
        validate_and_fix_agents(sample_run_state)
        assert mock_validate.call_count == 2
        mock_call.assert_called_once()

    @patch("orchestrator.call_agent_with_retry")
    @patch("orchestrator.validate_agents")
    def test_raises_after_max_retries(self, mock_validate, mock_call, project_root, sample_run_state):
        mock_validate.return_value = ["persistent error"]
        mock_call.return_value = "tried to fix"
        with pytest.raises(AgentValidationError, match="Validation failed"):
            validate_and_fix_agents(sample_run_state)
        # MAX_AGENT_EDITOR_RETRIES is 2, so total attempts = 3
        assert mock_validate.call_count == 3
        assert mock_call.call_count == 2

    @patch("orchestrator.call_agent_with_retry")
    @patch("orchestrator.validate_agents")
    def test_retry_prompt_includes_errors(self, mock_validate, mock_call, project_root, sample_run_state):
        mock_validate.side_effect = [["missing section"], []]
        mock_call.return_value = "ok"
        validate_and_fix_agents(sample_run_state)
        call_args = mock_call.call_args[0][1]
        assert "missing section" in call_args
