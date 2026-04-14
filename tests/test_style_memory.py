"""Tests for count_important_rules, filter_style_rules, check_important_rule_limit."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from orchestrator import (
    count_important_rules,
    filter_style_rules,
    check_important_rule_limit,
    IMPORTANT_RULE_MAX,
)


class TestCountImportantRules:
    def test_basic_count(self, tmp_path):
        sg = tmp_path / "style_guide.md"
        sg.write_text("# Style Guide\n\n## IMPORTANT Rules\n\n- Rule 1\n- Rule 2\n- Rule 3\n\n## Learned Rules\n\n- Old rule\n")
        assert count_important_rules(sg) == 3

    def test_no_rules(self, tmp_path):
        sg = tmp_path / "style_guide.md"
        sg.write_text("# Style Guide\n\n## IMPORTANT Rules\n\n## Learned Rules\n")
        assert count_important_rules(sg) == 0

    def test_file_not_exists(self, tmp_path):
        sg = tmp_path / "nonexistent.md"
        assert count_important_rules(sg) == 0

    def test_no_important_section(self, tmp_path):
        sg = tmp_path / "style_guide.md"
        sg.write_text("# Style Guide\n\n## Learned Rules\n\n- Rule 1\n")
        assert count_important_rules(sg) == 0

    def test_many_rules(self, tmp_path):
        sg = tmp_path / "style_guide.md"
        rules = "\n".join([f"- Rule {i}" for i in range(20)])
        sg.write_text(f"# Style Guide\n\n## IMPORTANT Rules\n\n{rules}\n\n## Learned Rules\n")
        assert count_important_rules(sg) == 20

    def test_indented_lines_not_counted(self, tmp_path):
        sg = tmp_path / "style_guide.md"
        sg.write_text("# Style Guide\n\n## IMPORTANT Rules\n\n- Rule 1\n  detail\n- Rule 2\n\n## Learned Rules\n")
        assert count_important_rules(sg) == 2


class TestCheckImportantRuleLimit:
    def test_below_limit(self, project_root):
        sm_dir = project_root / "style_memory"
        sm_dir.mkdir(parents=True, exist_ok=True)
        sg = sm_dir / "style_guide.md"
        sg.write_text("# Style Guide\n\n## IMPORTANT Rules\n\n- Rule 1\n\n## Learned Rules\n")
        assert check_important_rule_limit() is False

    def test_at_limit(self, project_root):
        sm_dir = project_root / "style_memory"
        sm_dir.mkdir(parents=True, exist_ok=True)
        sg = sm_dir / "style_guide.md"
        rules = "\n".join([f"- Rule {i}" for i in range(IMPORTANT_RULE_MAX)])
        sg.write_text(f"# Style Guide\n\n## IMPORTANT Rules\n\n{rules}\n\n## Learned Rules\n")
        assert check_important_rule_limit() is True

    def test_above_limit(self, project_root):
        sm_dir = project_root / "style_memory"
        sm_dir.mkdir(parents=True, exist_ok=True)
        sg = sm_dir / "style_guide.md"
        rules = "\n".join([f"- Rule {i}" for i in range(IMPORTANT_RULE_MAX + 5)])
        sg.write_text(f"# Style Guide\n\n## IMPORTANT Rules\n\n{rules}\n\n## Learned Rules\n")
        assert check_important_rule_limit() is True

    def test_no_file(self, project_root):
        assert check_important_rule_limit() is False


class TestFilterStyleRules:
    def test_filter_by_category(self, tmp_path):
        sg = tmp_path / "style_guide.md"
        sg.write_text(
            "# Style Guide\n\n"
            "## IMPORTANT Rules\n\n"
            "- [rhythm] Use varied sentence lengths\n"
            "- [structure] Start with a hook\n"
            "- [voice] Keep personal tone\n"
            "\n## Learned Rules\n\n"
            "- [density] Avoid redundancy\n"
        )
        result = filter_style_rules(sg, ["rhythm", "voice"])
        assert "varied sentence lengths" in result
        assert "personal tone" in result
        assert "Start with a hook" not in result

    def test_uncategorized_rules(self, tmp_path):
        sg = tmp_path / "style_guide.md"
        sg.write_text(
            "# Style Guide\n\n"
            "## IMPORTANT Rules\n\n"
            "- [rhythm] Tagged rule\n"
            "- Untagged rule\n"
        )
        result = filter_style_rules(sg, ["uncategorized"])
        assert "Untagged rule" in result
        assert "Tagged rule" not in result

    def test_no_matches_returns_full(self, tmp_path):
        sg = tmp_path / "style_guide.md"
        sg.write_text("# Style Guide\n\n## IMPORTANT Rules\n\n- [rhythm] A rule\n")
        result = filter_style_rules(sg, ["density"])
        # No matches -> returns full text
        assert "A rule" in result

    def test_file_not_exists(self, tmp_path):
        sg = tmp_path / "nonexistent.md"
        assert filter_style_rules(sg, ["rhythm"]) == ""

    def test_continuation_lines_included(self, tmp_path):
        sg = tmp_path / "style_guide.md"
        sg.write_text(
            "## IMPORTANT Rules\n\n"
            "- [rhythm] Main rule\n"
            "  continuation detail\n"
            "- [structure] Other rule\n"
        )
        result = filter_style_rules(sg, ["rhythm"])
        assert "Main rule" in result
        assert "continuation detail" in result
        assert "Other rule" not in result

    def test_empty_categories(self, tmp_path):
        sg = tmp_path / "style_guide.md"
        sg.write_text("## IMPORTANT Rules\n\n- [rhythm] A rule\n")
        result = filter_style_rules(sg, [])
        # No matches -> full text returned
        assert "A rule" in result
