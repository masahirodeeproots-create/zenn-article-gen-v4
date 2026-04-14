"""Common fixtures for Zenn Article Generator tests."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add project root to sys.path so we can import orchestrator and knowledge_store
PROJECT_SRC = str(Path(__file__).resolve().parent.parent)
if PROJECT_SRC not in sys.path:
    sys.path.insert(0, PROJECT_SRC)


@pytest.fixture
def project_root(tmp_path):
    """Override PROJECT_ROOT and all derived paths to use tmp_path."""
    root = tmp_path / "zenn-article-gen"
    root.mkdir()

    patches = {
        "orchestrator.PROJECT_ROOT": root,
        "orchestrator.AGENTS_GENERATED_DIR": root / "agents" / "generated",
        "orchestrator.AGENT_TEMPLATES_DIR": root / "agent_templates",
        "orchestrator.MATERIALS_DIR": root / "materials",
        "orchestrator.ITERATIONS_DIR": root / "iterations",
        "orchestrator.MATERIAL_REVIEWS_DIR": root / "material_reviews",
        "orchestrator.RUNS_DIR": root / "runs",
        "orchestrator.AGENT_MEMORY_DIR": root / "agent_memory",
        "orchestrator.STYLE_MEMORY_DIR": root / "style_memory",
        "orchestrator.KNOWLEDGE_DIR": root / "knowledge",
        "orchestrator.HUMAN_BENCH_DIR": root / "human-bench",
        "orchestrator.SOURCE_MATERIAL_DIR": root / "source-material",
    }

    stack = []
    for target, value in patches.items():
        p = patch(target, value)
        p.start()
        stack.append(p)

    yield root

    for p in stack:
        p.stop()


@pytest.fixture
def knowledge_root(tmp_path):
    """Override knowledge_store paths to use tmp_path."""
    kdir = tmp_path / "knowledge"
    kdir.mkdir()
    cache_dir = kdir / "search_cache"
    cache_dir.mkdir()
    archive_dir = kdir / "archive"
    archive_dir.mkdir()

    patches = {
        "knowledge_store.KNOWLEDGE_DIR": kdir,
        "knowledge_store.SEARCH_CACHE_DIR": cache_dir,
        "knowledge_store.ARCHIVE_DIR": archive_dir,
    }

    stack = []
    for target, value in patches.items():
        p = patch(target, value)
        p.start()
        stack.append(p)

    yield kdir

    for p in stack:
        p.stop()


@pytest.fixture
def sample_run_state():
    """Create a sample RunState for testing."""
    import orchestrator
    state = orchestrator.RunState(
        run_id="20260413_120000",
        article_type="体験記",
        source_dir="source-material",
        user_instruction="Claude Codeの体験記を書く",
    )
    return state


@pytest.fixture
def sample_workflow():
    """Return a sample workflow dict."""
    return {
        "phases": [
            {
                "name": "material_generation",
                "agents": ["code_analyzer", "trend_searcher"],
                "loop": False,
                "parallel": True,
            },
            {
                "name": "material_review",
                "agents": ["material_reviewer", "material_updater"],
                "loop": True,
                "max_iterations": 5,
                "score_threshold": 8.0,
                "stagnation_window": 3,
                "stagnation_tolerance": 0.5,
            },
            {
                "name": "article_writing",
                "agents": ["writer"],
                "loop": False,
            },
            {
                "name": "article_review",
                "agents": ["writer", "article_reviewer", "style_guide_updater"],
                "loop": True,
                "max_iterations": 10,
                "score_threshold": 9.0,
                "stagnation_window": 3,
                "stagnation_tolerance": 0.5,
                "allow_material_fallback": True,
            },
        ]
    }


@pytest.fixture
def sample_review_text():
    """Return a sample review text with scores and JSON FB data."""
    return """# Review

## Overall: 7.5/10

### S1. 構成: 8.0/10
Good structure overall.

### S2. 文体: 7.0/10
Needs more variety.

### A1. 技術深度: 7.5/10
Could go deeper.

```json
{
  "issues": [
    {"id": "s1_001", "severity": "major", "detail": "導入が弱い", "resolved": false},
    {"id": "s2_001", "severity": "minor", "detail": "語尾が単調", "resolved": false},
    {"id": "a1_001", "severity": "major", "detail": "コード例が不足", "resolved": true}
  ]
}
```
"""


@pytest.fixture
def sample_fb_log():
    """Return a sample fb_log structure."""
    return {
        "phase": "article_review",
        "iterations": [
            {
                "iteration": 1,
                "issues": [
                    {"id": "s1_001", "severity": "major", "detail": "導入が弱い", "resolved": False},
                    {"id": "s2_001", "severity": "minor", "detail": "語尾が単調", "resolved": False},
                    {"id": "a1_001", "severity": "major", "detail": "コード例が不足", "resolved": False},
                ],
            },
            {
                "iteration": 2,
                "issues": [
                    {"id": "s1_001", "severity": "major", "detail": "導入が弱い", "resolved": False},
                    {"id": "s2_001", "severity": "minor", "detail": "語尾が単調", "resolved": True},
                    {"id": "a1_001", "severity": "major", "detail": "コード例が不足", "resolved": True},
                    {"id": "s3_001", "severity": "major", "detail": "結論が唐突", "resolved": False},
                ],
            },
        ],
    }
