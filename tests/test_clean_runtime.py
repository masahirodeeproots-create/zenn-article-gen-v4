"""Tests for init_project, clean_runtime_dirs, generate_run_id."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from orchestrator import init_project, clean_runtime_dirs, generate_run_id


class TestGenerateRunId:
    def test_format(self):
        run_id = generate_run_id()
        # Should be YYYYMMDD_HHMMSS format
        assert len(run_id) == 15
        assert run_id[8] == "_"
        assert run_id[:8].isdigit()
        assert run_id[9:].isdigit()

    def test_unique_over_time(self):
        # Two calls at the same second should return the same id
        # but we just test format consistency
        run_id = generate_run_id()
        assert "_" in run_id

    def test_parseable(self):
        import time
        run_id = generate_run_id()
        # Should be parseable back to a time struct
        time.strptime(run_id, "%Y%m%d_%H%M%S")


class TestInitProject:
    def test_creates_directories(self, project_root):
        # Also patch knowledge_store dirs
        with patch("knowledge_store.KNOWLEDGE_DIR", project_root / "knowledge"), \
             patch("knowledge_store.SEARCH_CACHE_DIR", project_root / "knowledge" / "search_cache"), \
             patch("knowledge_store.ARCHIVE_DIR", project_root / "knowledge" / "archive"):
            init_project()

        assert (project_root / "source-material").is_dir()
        assert (project_root / "knowledge").is_dir()
        assert (project_root / "style_memory").is_dir()
        assert (project_root / "agent_templates").is_dir()
        assert (project_root / "agents" / "generated").is_dir()
        assert (project_root / "agent_memory").is_dir()
        assert (project_root / "human-bench" / "articles").is_dir()
        assert (project_root / "materials" / "fixed").is_dir()

    def test_creates_style_files(self, project_root):
        with patch("knowledge_store.KNOWLEDGE_DIR", project_root / "knowledge"), \
             patch("knowledge_store.SEARCH_CACHE_DIR", project_root / "knowledge" / "search_cache"), \
             patch("knowledge_store.ARCHIVE_DIR", project_root / "knowledge" / "archive"):
            init_project()

        sg = project_root / "style_memory" / "style_guide.md"
        assert sg.exists()
        assert "IMPORTANT Rules" in sg.read_text()

        ll = project_root / "style_memory" / "learning_log.md"
        assert ll.exists()
        assert "Learning Log" in ll.read_text()

    def test_idempotent(self, project_root):
        with patch("knowledge_store.KNOWLEDGE_DIR", project_root / "knowledge"), \
             patch("knowledge_store.SEARCH_CACHE_DIR", project_root / "knowledge" / "search_cache"), \
             patch("knowledge_store.ARCHIVE_DIR", project_root / "knowledge" / "archive"):
            init_project()
            # Write custom content
            sg = project_root / "style_memory" / "style_guide.md"
            sg.write_text("custom content")
            init_project()
            # Should NOT overwrite existing file
            assert sg.read_text() == "custom content"

    def test_knowledge_files_created(self, project_root):
        kdir = project_root / "knowledge"
        with patch("knowledge_store.KNOWLEDGE_DIR", kdir), \
             patch("knowledge_store.SEARCH_CACHE_DIR", kdir / "search_cache"), \
             patch("knowledge_store.ARCHIVE_DIR", kdir / "archive"):
            init_project()
        assert (kdir / "trends.md").exists()
        assert (kdir / "reader_pains.md").exists()


class TestCleanRuntimeDirs:
    def test_removes_runtime_files(self, project_root):
        # Create runtime files
        (project_root / "strategy.md").write_text("old strategy")
        (project_root / "eval_criteria.md").write_text("old eval")
        (project_root / "fb_log.json").write_text("{}")

        clean_runtime_dirs()

        assert not (project_root / "strategy.md").exists()
        assert not (project_root / "eval_criteria.md").exists()
        assert not (project_root / "fb_log.json").exists()

    def test_recreates_dirs(self, project_root):
        gen_dir = project_root / "agents" / "generated"
        gen_dir.mkdir(parents=True, exist_ok=True)
        (gen_dir / "old_agent.md").write_text("old")

        mat_dir = project_root / "materials"
        mat_dir.mkdir(parents=True, exist_ok=True)
        (mat_dir / "old_material.md").write_text("old")

        clean_runtime_dirs()

        assert gen_dir.is_dir()
        assert not (gen_dir / "old_agent.md").exists()
        assert mat_dir.is_dir()
        assert not (mat_dir / "old_material.md").exists()
        assert (project_root / "materials" / "fixed").is_dir()

    def test_handles_missing_dirs(self, project_root):
        # Should not raise even if dirs don't exist
        clean_runtime_dirs()
        assert (project_root / "agents" / "generated").is_dir()
        assert (project_root / "materials").is_dir()

    def test_preserves_persistent_data(self, project_root):
        sm_dir = project_root / "style_memory"
        sm_dir.mkdir(parents=True, exist_ok=True)
        (sm_dir / "style_guide.md").write_text("keep this")

        runs_dir = project_root / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / "old_run").mkdir()

        clean_runtime_dirs()

        assert (sm_dir / "style_guide.md").exists()
        assert (runs_dir / "old_run").is_dir()
