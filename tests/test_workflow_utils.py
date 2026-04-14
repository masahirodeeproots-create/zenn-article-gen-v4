"""Tests for load_workflow, validate_workflow_schema, find_phase_by_name."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from orchestrator import (
    load_workflow,
    validate_workflow_schema,
    find_phase_by_name,
    WorkflowLoadError,
    WorkflowValidationError,
)


class TestLoadWorkflow:
    def test_load_valid(self, project_root):
        wf_dir = project_root / "agents" / "generated"
        wf_dir.mkdir(parents=True, exist_ok=True)
        wf = {"phases": [{"name": "test", "agents": []}]}
        (wf_dir / "workflow.json").write_text(json.dumps(wf))
        result = load_workflow()
        assert result == wf

    def test_missing_file_raises(self, project_root):
        (project_root / "agents" / "generated").mkdir(parents=True, exist_ok=True)
        with pytest.raises(WorkflowLoadError, match="workflow.json not found"):
            load_workflow()

    def test_invalid_json_raises(self, project_root):
        wf_dir = project_root / "agents" / "generated"
        wf_dir.mkdir(parents=True, exist_ok=True)
        (wf_dir / "workflow.json").write_text("{bad json")
        with pytest.raises(Exception):
            load_workflow()


class TestValidateWorkflowSchema:
    def test_valid_workflow(self, project_root, sample_workflow):
        # Create agent files so validation passes
        gen_dir = project_root / "agents" / "generated"
        gen_dir.mkdir(parents=True, exist_ok=True)
        for phase in sample_workflow["phases"]:
            for agent in phase["agents"]:
                (gen_dir / f"{agent}.md").write_text(f"# {agent}\n")
        validate_workflow_schema(sample_workflow)  # Should not raise

    def test_missing_phases_key(self):
        with pytest.raises(WorkflowValidationError, match="Missing 'phases'"):
            validate_workflow_schema({})

    def test_missing_phase_name(self, project_root):
        wf = {"phases": [{"agents": ["writer"]}]}
        gen_dir = project_root / "agents" / "generated"
        gen_dir.mkdir(parents=True, exist_ok=True)
        (gen_dir / "writer.md").write_text("# writer\n")
        with pytest.raises(WorkflowValidationError, match="missing 'name'"):
            validate_workflow_schema(wf)

    def test_duplicate_phase_names(self, project_root):
        wf = {"phases": [
            {"name": "dup", "agents": []},
            {"name": "dup", "agents": []},
        ]}
        with pytest.raises(WorkflowValidationError, match="duplicate name"):
            validate_workflow_schema(wf)

    def test_missing_agents_key(self, project_root):
        wf = {"phases": [{"name": "test"}]}
        with pytest.raises(WorkflowValidationError, match="missing 'agents'"):
            validate_workflow_schema(wf)

    def test_loop_without_max_iterations(self, project_root):
        wf = {"phases": [{"name": "test", "agents": [], "loop": True}]}
        with pytest.raises(WorkflowValidationError, match="loop=true but no max_iterations"):
            validate_workflow_schema(wf)

    def test_missing_agent_definition(self, project_root):
        gen_dir = project_root / "agents" / "generated"
        gen_dir.mkdir(parents=True, exist_ok=True)
        wf = {"phases": [{"name": "test", "agents": ["nonexistent"]}]}
        with pytest.raises(WorkflowValidationError, match="agent 'nonexistent' definition not found"):
            validate_workflow_schema(wf)

    def test_loop_false_no_max_iterations_ok(self, project_root):
        wf = {"phases": [{"name": "test", "agents": [], "loop": False}]}
        validate_workflow_schema(wf)  # Should not raise


class TestFindPhaseByName:
    def test_found(self, sample_workflow):
        phase = find_phase_by_name(sample_workflow, "article_review")
        assert phase is not None
        assert phase["name"] == "article_review"

    def test_not_found(self, sample_workflow):
        assert find_phase_by_name(sample_workflow, "nonexistent") is None

    def test_empty_workflow(self):
        assert find_phase_by_name({"phases": []}, "test") is None

    def test_first_phase(self, sample_workflow):
        phase = find_phase_by_name(sample_workflow, "material_generation")
        assert phase is not None
        assert phase["parallel"] is True

    def test_missing_phases_key(self):
        assert find_phase_by_name({}, "test") is None
