"""Tests for knowledge_store: append_entry, filter_by_topic, cache, archive."""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import knowledge_store


class TestAppendEntry:
    def test_append_to_trends(self, knowledge_root):
        trends = knowledge_root / "trends.md"
        trends.write_text("# Trends\n\n")
        knowledge_store.append_entry("trends.md", "AI trend update\nDetails here", "2026-01-15")
        content = trends.read_text()
        assert "### 2026-01-15: AI trend update" in content
        assert "Details here" in content

    def test_append_to_reader_pains(self, knowledge_root):
        rp = knowledge_root / "reader_pains.md"
        rp.write_text("# Reader Pains\n\n")
        knowledge_store.append_entry("reader_pains.md", "Setup frustration")
        content = rp.read_text()
        assert "Setup frustration" in content

    def test_invalid_file_raises(self, knowledge_root):
        with pytest.raises(ValueError, match="Invalid file_name"):
            knowledge_store.append_entry("bad_file.md", "test")

    def test_empty_entry_skipped(self, knowledge_root):
        trends = knowledge_root / "trends.md"
        trends.write_text("# Trends\n\n")
        knowledge_store.append_entry("trends.md", "   ")
        content = trends.read_text()
        assert content == "# Trends\n\n"

    def test_default_timestamp(self, knowledge_root):
        trends = knowledge_root / "trends.md"
        trends.write_text("# Trends\n\n")
        knowledge_store.append_entry("trends.md", "test entry")
        content = trends.read_text()
        today = datetime.now().strftime("%Y-%m-%d")
        assert today in content

    def test_multiple_appends(self, knowledge_root):
        trends = knowledge_root / "trends.md"
        trends.write_text("# Trends\n\n")
        knowledge_store.append_entry("trends.md", "Entry 1", "2026-01-01")
        knowledge_store.append_entry("trends.md", "Entry 2", "2026-01-02")
        content = trends.read_text()
        assert "Entry 1" in content
        assert "Entry 2" in content


class TestFilterByTopic:
    def test_match_found(self, knowledge_root):
        trends = knowledge_root / "trends.md"
        trends.write_text("# Trends\n\n---\n### 2026-01-01: AI tools\nAI details\n\n---\n### 2026-01-02: Cooking tips\nRecipe")
        result = knowledge_store.filter_by_topic("trends.md", "AI")
        assert "AI" in result
        assert "Cooking" not in result

    def test_no_match(self, knowledge_root):
        trends = knowledge_root / "trends.md"
        trends.write_text("# Trends\n\n---\n### 2026-01-01: Python news\nDetails")
        result = knowledge_store.filter_by_topic("trends.md", "Rust")
        assert result == ""

    def test_empty_topic(self, knowledge_root):
        trends = knowledge_root / "trends.md"
        trends.write_text("# Trends\n\nSomething")
        assert knowledge_store.filter_by_topic("trends.md", "") == ""

    def test_file_not_exists(self, knowledge_root):
        assert knowledge_store.filter_by_topic("nonexistent.md", "test") == ""

    def test_max_lines_respected(self, knowledge_root):
        trends = knowledge_root / "trends.md"
        # Create a large file
        sections = []
        for i in range(50):
            sections.append(f"### 2026-01-{i+1:02d}: AI topic {i}\n" + "\n".join([f"Line {j}" for j in range(10)]))
        trends.write_text("# Trends\n\n---\n" + "\n---\n".join(sections))
        result = knowledge_store.filter_by_topic("trends.md", "AI", max_lines=50)
        assert len(result.split("\n")) <= 50

    def test_case_insensitive(self, knowledge_root):
        trends = knowledge_root / "trends.md"
        trends.write_text("# Trends\n\n---\n### 2026-01-01: Python News\nDetails")
        result = knowledge_store.filter_by_topic("trends.md", "python")
        assert "Python" in result


class TestCacheSearchResult:
    def test_cache_and_retrieve(self, knowledge_root):
        knowledge_store.cache_search_result("test query", {"data": "value"})
        result = knowledge_store.get_cached_search("test query")
        assert result == {"data": "value"}

    def test_cache_miss(self, knowledge_root):
        assert knowledge_store.get_cached_search("nonexistent") is None

    def test_expired_cache(self, knowledge_root):
        knowledge_store.cache_search_result("old query", {"data": "old"})
        # Manually expire the cache
        import hashlib
        qh = hashlib.md5("old query".encode()).hexdigest()[:12]
        cache_path = knowledge_root / "search_cache" / f"{qh}.json"
        with open(cache_path) as f:
            data = json.load(f)
        data["expires_at"] = (datetime.now() - timedelta(days=1)).isoformat()
        with open(cache_path, "w") as f:
            json.dump(data, f)
        assert knowledge_store.get_cached_search("old query") is None

    def test_cache_overwrite(self, knowledge_root):
        knowledge_store.cache_search_result("q", {"v": 1})
        knowledge_store.cache_search_result("q", {"v": 2})
        assert knowledge_store.get_cached_search("q") == {"v": 2}


class TestCleanupExpiredCache:
    def test_cleanup_removes_expired(self, knowledge_root):
        knowledge_store.cache_search_result("q1", {"d": 1})
        # Expire it
        import hashlib
        qh = hashlib.md5("q1".encode()).hexdigest()[:12]
        cp = knowledge_root / "search_cache" / f"{qh}.json"
        with open(cp) as f:
            data = json.load(f)
        data["expires_at"] = (datetime.now() - timedelta(days=1)).isoformat()
        with open(cp, "w") as f:
            json.dump(data, f)
        deleted = knowledge_store.cleanup_expired_cache()
        assert deleted == 1

    def test_cleanup_keeps_valid(self, knowledge_root):
        knowledge_store.cache_search_result("q1", {"d": 1})
        deleted = knowledge_store.cleanup_expired_cache()
        assert deleted == 0
        assert knowledge_store.get_cached_search("q1") is not None

    def test_cleanup_invalid_json(self, knowledge_root):
        bad = knowledge_root / "search_cache" / "bad.json"
        bad.write_text("not json")
        deleted = knowledge_store.cleanup_expired_cache()
        assert deleted == 1

    def test_cleanup_empty_dir(self, knowledge_root):
        assert knowledge_store.cleanup_expired_cache() == 0


class TestArchiveOldEntries:
    def test_archive_old(self, knowledge_root):
        trends = knowledge_root / "trends.md"
        old_date = (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d")
        trends.write_text(f"# Trends\n\n---\n### {old_date}: Old entry\nOld content")
        knowledge_store.archive_old_entries()
        archived = knowledge_root / "archive" / "trends_archived.md"
        assert archived.exists()
        assert "Old entry" in archived.read_text()

    def test_keep_recent(self, knowledge_root):
        trends = knowledge_root / "trends.md"
        today = datetime.now().strftime("%Y-%m-%d")
        trends.write_text(f"# Trends\n\n---\n### {today}: New entry\nNew content")
        knowledge_store.archive_old_entries()
        assert "New entry" in trends.read_text()
        archived = knowledge_root / "archive" / "trends_archived.md"
        assert not archived.exists()

    def test_archive_nonexistent_file(self, knowledge_root):
        # Should not raise
        knowledge_store.archive_old_entries()
