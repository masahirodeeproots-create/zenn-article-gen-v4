"""knowledge_store.py — 知識DB API v4.0

責務: knowledge/配下のファイルの追記・検索・フィルタリング・アーカイブ
原則: 機械的な操作のみ。判断はエージェント側。
"""

import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

KNOWLEDGE_DIR = Path("/tmp/zenn-article-gen/knowledge")
SEARCH_CACHE_DIR = KNOWLEDGE_DIR / "search_cache"
ARCHIVE_DIR = KNOWLEDGE_DIR / "archive"

CACHE_TTL_DAYS = 7
ARCHIVE_THRESHOLD_MONTHS = 6
MAX_FILTERED_LINES = 200


def init_knowledge_dir():
    """知識DBディレクトリを初期化（冪等）"""
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    SEARCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for fname in ["trends.md", "reader_pains.md"]:
        path = KNOWLEDGE_DIR / fname
        if not path.exists():
            path.write_text(f"# {fname.replace('.md', '').replace('_', ' ').title()}\n\n")


def append_entry(file_name: str, entry: str, timestamp: str = None):
    """knowledge/のファイルにエントリを追記する。"""
    if file_name not in ("trends.md", "reader_pains.md"):
        raise ValueError(f"Invalid file_name: {file_name}")
    if not entry.strip():
        return

    timestamp = timestamp or datetime.now().strftime("%Y-%m-%d")
    file_path = KNOWLEDGE_DIR / file_name

    first_line = entry.strip().split("\n")[0]
    formatted = f"\n---\n### {timestamp}: {first_line}\n{entry.strip()}\n"

    with open(file_path, "a", encoding="utf-8") as f:
        f.write(formatted)


def filter_by_topic(file_name: str, topic: str, max_lines: int = MAX_FILTERED_LINES) -> str:
    """knowledge/のファイルからtopic関連セクションだけを抽出し、max_lines以内に収めて返す。"""
    file_path = KNOWLEDGE_DIR / file_name
    if not file_path.exists():
        return ""

    text = file_path.read_text(encoding="utf-8")
    sections = text.split("\n---\n")

    keywords = [k.strip().lower() for k in topic.split() if k.strip()]
    if not keywords:
        return ""

    matched = []
    for section in reversed(sections):
        section_lower = section.lower()
        if any(kw in section_lower for kw in keywords):
            matched.append(section.strip())

    result_lines = []
    for section in matched:
        section_lines = section.split("\n")
        if len(result_lines) + len(section_lines) + 1 > max_lines:
            break
        if result_lines:
            result_lines.append("---")
        result_lines.extend(section_lines)

    return "\n".join(result_lines)


def cache_search_result(query: str, result: dict):
    """検索結果をキャッシュに保存する。"""
    SEARCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    query_hash = hashlib.md5(query.encode()).hexdigest()[:12]
    cache_path = SEARCH_CACHE_DIR / f"{query_hash}.json"

    now = datetime.now()
    data = {
        "query": query,
        "result": result,
        "cached_at": now.isoformat(),
        "expires_at": (now + timedelta(days=CACHE_TTL_DAYS)).isoformat(),
    }

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_cached_search(query: str) -> dict | None:
    """キャッシュから検索結果を取得する。期限切れの場合はNoneを返す。"""
    query_hash = hashlib.md5(query.encode()).hexdigest()[:12]
    cache_path = SEARCH_CACHE_DIR / f"{query_hash}.json"

    if not cache_path.exists():
        return None

    with open(cache_path, encoding="utf-8") as f:
        data = json.load(f)

    expires_at = datetime.fromisoformat(data["expires_at"])
    if datetime.now() > expires_at:
        cache_path.unlink()
        return None

    return data["result"]


def cleanup_expired_cache() -> int:
    """期限切れのキャッシュファイルを一括削除する。"""
    if not SEARCH_CACHE_DIR.exists():
        return 0

    deleted = 0
    for cache_file in SEARCH_CACHE_DIR.glob("*.json"):
        try:
            with open(cache_file, encoding="utf-8") as f:
                data = json.load(f)
            expires_at = datetime.fromisoformat(data["expires_at"])
            if datetime.now() > expires_at:
                cache_file.unlink()
                deleted += 1
        except (json.JSONDecodeError, KeyError):
            cache_file.unlink()
            deleted += 1

    return deleted


def archive_old_entries():
    """6ヶ月超のエントリをknowledge/archive/に移動する。"""
    threshold = datetime.now() - timedelta(days=180)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    for file_name in ("trends.md", "reader_pains.md"):
        file_path = KNOWLEDGE_DIR / file_name
        if not file_path.exists():
            continue

        text = file_path.read_text(encoding="utf-8")
        sections = text.split("\n---\n")

        keep = []
        archive = []

        for section in sections:
            date_match = re.search(r"### (\d{4}-\d{2}-\d{2}):", section)
            if date_match:
                try:
                    entry_date = datetime.strptime(date_match.group(1), "%Y-%m-%d")
                    if entry_date < threshold:
                        archive.append(section)
                        continue
                except ValueError:
                    pass
            keep.append(section)

        if archive:
            archive_path = ARCHIVE_DIR / f"{file_name.replace('.md', '')}_archived.md"
            with open(archive_path, "a", encoding="utf-8") as f:
                for section in archive:
                    f.write(f"\n---\n{section.strip()}\n")

            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n---\n".join(keep))
