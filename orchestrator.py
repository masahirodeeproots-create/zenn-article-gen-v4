#!/usr/bin/env python3
"""
Zenn Article Generator — Orchestrator v4.0

MetaAgentによる動的エージェント構成で記事を自動生成する。
- 層1: MetaAgent（Strategist, Agent Editor, Eval Designer）
- 層2: 動的生成されたエージェント群（素材PDCA + 記事PDCA）
- 層3: 蓄積基盤（knowledge, style_memory, agent_memory, human-bench）
"""

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    yaml = None

import knowledge_store

# ============================================================
# 定数
# ============================================================

PROJECT_ROOT = Path("/tmp/zenn-article-gen")
AGENTS_GENERATED_DIR = PROJECT_ROOT / "agents" / "generated"
AGENT_TEMPLATES_DIR = PROJECT_ROOT / "agent_templates"
MATERIALS_DIR = PROJECT_ROOT / "materials"
ITERATIONS_DIR = PROJECT_ROOT / "iterations"
MATERIAL_REVIEWS_DIR = PROJECT_ROOT / "material_reviews"
RUNS_DIR = PROJECT_ROOT / "runs"
AGENT_MEMORY_DIR = PROJECT_ROOT / "agent_memory"
STYLE_MEMORY_DIR = PROJECT_ROOT / "style_memory"
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"
HUMAN_BENCH_DIR = PROJECT_ROOT / "human-bench"
SOURCE_MATERIAL_DIR = PROJECT_ROOT / "source-material"

DEFAULT_TIMEOUT = 1800  # 30分
MAX_AGENT_EDITOR_RETRIES = 2
RETRY_BASE_DELAY = 5
IMPORTANT_RULE_MAX = 15
VALID_CATEGORIES = {"rhythm", "structure", "distance", "density", "emotion", "voice", "uncategorized"}


# ============================================================
# 例外クラス階層
# ============================================================

class ZennArticleGenError(Exception):
    """基底例外"""

class AgentError(ZennArticleGenError):
    """エージェント関連の中間基底"""

class AgentTimeoutError(AgentError):
    pass

class AgentExecutionError(AgentError):
    pass

class AgentNotFoundError(AgentError):
    pass

class AgentValidationError(AgentError):
    pass

class ScoreExtractionError(ZennArticleGenError):
    pass

class EscalationParseError(ZennArticleGenError):
    pass

class WorkflowLoadError(ZennArticleGenError):
    pass

class WorkflowValidationError(ZennArticleGenError):
    pass

class WorkflowExecutionError(ZennArticleGenError):
    pass

class FBLogParseError(ZennArticleGenError):
    pass

class UpdaterResponseParseError(ZennArticleGenError):
    pass


# ============================================================
# RunState — インメモリ状態管理
# ============================================================

@dataclass
class RunState:
    """1回の実行に関する全状態を保持。"""
    run_id: str
    article_type: str = ""
    source_dir: str = ""
    user_instruction: str = ""
    scores: dict = field(default_factory=dict)
    escalated: dict = field(default_factory=dict)
    material_fallback_count: dict = field(default_factory=dict)
    metrics_history: dict = field(default_factory=dict)
    fb_log: dict = field(default_factory=dict)
    fb_diff_history: dict = field(default_factory=dict)
    axis_scores_history: dict = field(default_factory=dict)  # {phase_name: [{軸名: score}, ...]}
    log: list = field(default_factory=list)
    token_usage: dict = field(default_factory=lambda: {
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cache_creation_tokens": 0,
        "total_cache_read_tokens": 0,
        "total_cost_usd": 0.0,
        "by_agent": {},
    })

    def record_tokens(self, agent_name: str, usage: dict, cost: float):
        """エージェント呼び出しのトークン消費を記録"""
        self.token_usage["total_input_tokens"] += usage.get("input_tokens", 0)
        self.token_usage["total_output_tokens"] += usage.get("output_tokens", 0)
        self.token_usage["total_cache_creation_tokens"] += usage.get("cache_creation_input_tokens", 0)
        self.token_usage["total_cache_read_tokens"] += usage.get("cache_read_input_tokens", 0)
        self.token_usage["total_cost_usd"] += cost
        if agent_name not in self.token_usage["by_agent"]:
            self.token_usage["by_agent"][agent_name] = {
                "input_tokens": 0, "output_tokens": 0, "cost": 0.0, "calls": 0,
            }
        ag = self.token_usage["by_agent"][agent_name]
        ag["input_tokens"] += usage.get("input_tokens", 0)
        ag["output_tokens"] += usage.get("output_tokens", 0)
        ag["cost"] += cost
        ag["calls"] += 1

    def add_score(self, phase_name: str, score: float):
        if phase_name not in self.scores:
            self.scores[phase_name] = []
        self.scores[phase_name].append(score)

    def get_scores(self, phase_name: str) -> list:
        return self.scores.get(phase_name, [])

    def is_escalated(self, phase_name: str) -> bool:
        return self.escalated.get(phase_name, False)

    def mark_escalated(self, phase_name: str):
        self.escalated[phase_name] = True


# ============================================================
# ログ
# ============================================================

def log(msg: str):
    print(f"[orchestrator] {msg}", flush=True)


# ============================================================
# 初期化 (Phase 0)
# ============================================================

def generate_run_id() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def init_project():
    """蓄積ディレクトリと初期ファイルの初回作成（冪等）"""
    for d in [
        SOURCE_MATERIAL_DIR,
        KNOWLEDGE_DIR, KNOWLEDGE_DIR / "search_cache", KNOWLEDGE_DIR / "archive",
        STYLE_MEMORY_DIR, AGENT_TEMPLATES_DIR, AGENTS_GENERATED_DIR,
        AGENT_MEMORY_DIR,
        HUMAN_BENCH_DIR, HUMAN_BENCH_DIR / "articles",
        HUMAN_BENCH_DIR / "articles" / "体験記",
        HUMAN_BENCH_DIR / "articles" / "比較検証",
        HUMAN_BENCH_DIR / "articles" / "チュートリアル",
        HUMAN_BENCH_DIR / "articles" / "思想記",
        MATERIALS_DIR, MATERIALS_DIR / "fixed",
        MATERIAL_REVIEWS_DIR, ITERATIONS_DIR, RUNS_DIR,
    ]:
        d.mkdir(parents=True, exist_ok=True)

    knowledge_store.init_knowledge_dir()

    sg = STYLE_MEMORY_DIR / "style_guide.md"
    if not sg.exists():
        sg.write_text("# Style Guide\n\n## IMPORTANT Rules\n\n## Learned Rules\n\n## Failure Patterns\n\n")
    ll = STYLE_MEMORY_DIR / "learning_log.md"
    if not ll.exists():
        ll.write_text("# Learning Log\n\n")


def clean_runtime_dirs():
    """実行時生成ファイルをクリア。蓄積データには触れない。"""
    for f in ["strategy.md", "eval_criteria.md", "fb_log.json"]:
        p = PROJECT_ROOT / f
        if p.exists():
            p.unlink()
    for d in [AGENTS_GENERATED_DIR, MATERIALS_DIR, MATERIAL_REVIEWS_DIR, ITERATIONS_DIR]:
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)
    (MATERIALS_DIR / "fixed").mkdir(exist_ok=True)


# ============================================================
# エージェント呼び出し基盤 (Phase 1)
# ============================================================

def _parse_agent_output(raw_stdout: str, name: str, state: Optional[RunState] = None) -> str:
    """JSON出力をパースしてテキストを返す。トークン計測をstateに記録。"""
    try:
        data = json.loads(raw_stdout)
    except (json.JSONDecodeError, TypeError):
        # フォールバック: JSON非対応CLIバージョンの場合、生テキストとして返す
        return raw_stdout

    # is_errorチェック（returncode=0でもエラーの場合がある）
    if data.get("is_error"):
        raise AgentExecutionError(f"Agent {name} returned is_error=true: {data.get('result', '')[:300]}")

    # トークン計測
    if state and "usage" in data:
        state.record_tokens(name, data["usage"], data.get("total_cost_usd", 0.0))

    text = data.get("result", "").strip()
    cost = data.get("total_cost_usd", 0)
    usage = data.get("usage", {})
    in_tok = usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
    out_tok = usage.get("output_tokens", 0)
    log(f"  tokens: {in_tok} in / {out_tok} out / ${cost:.4f}")
    return text


def call_agent(name: str, prompt: str, model: str = "sonnet", timeout: int = DEFAULT_TIMEOUT,
               state: Optional[RunState] = None) -> str:
    log(f"CALL {name} (model={model})")
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", model,
             "--output-format", "json", "--permission-mode", "bypassPermissions",
             "--max-turns", "30"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise AgentTimeoutError(f"Agent {name} timed out after {timeout}s")
    if result.returncode != 0:
        raise AgentExecutionError(f"Agent {name} failed (rc={result.returncode}): {result.stderr[:500]}")
    output = _parse_agent_output(result.stdout, name, state)
    log(f"DONE {name} ({len(output)} chars)")
    return output


async def call_agent_async(name: str, prompt: str, model: str = "sonnet", timeout: int = DEFAULT_TIMEOUT,
                           state: Optional[RunState] = None) -> str:
    log(f"CALL_ASYNC {name} (model={model})")
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", prompt, "--model", model,
            "--output-format", "json", "--permission-mode", "bypassPermissions",
            "--max-turns", "30",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(PROJECT_ROOT),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise AgentTimeoutError(f"Agent {name} timed out after {timeout}s")
    if proc.returncode != 0:
        raise AgentExecutionError(f"Agent {name} failed (rc={proc.returncode}): {stderr.decode()[:500]}")
    output = _parse_agent_output(stdout.decode(), name, state)
    log(f"DONE_ASYNC {name} ({len(output)} chars)")
    return output


def call_agent_with_retry(name: str, prompt: str, model: str = "sonnet",
                          timeout: int = DEFAULT_TIMEOUT, max_retries: int = 3,
                          state: Optional[RunState] = None) -> str:
    for attempt in range(max_retries):
        try:
            return call_agent(name, prompt, model, timeout, state=state)
        except AgentExecutionError:
            if attempt == max_retries - 1:
                raise
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            log(f"RETRY {name} in {delay}s (attempt {attempt + 1}/{max_retries})")
            time.sleep(delay)
        except AgentTimeoutError:
            raise


async def call_agent_async_with_retry(name: str, prompt: str, model: str = "sonnet",
                                       timeout: int = DEFAULT_TIMEOUT, max_retries: int = 3,
                                       state: Optional[RunState] = None) -> str:
    for attempt in range(max_retries):
        try:
            return await call_agent_async(name, prompt, model, timeout, state=state)
        except AgentExecutionError:
            if attempt == max_retries - 1:
                raise
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            log(f"RETRY_ASYNC {name} in {delay}s (attempt {attempt + 1}/{max_retries})")
            await asyncio.sleep(delay)
        except AgentTimeoutError:
            raise


# ============================================================
# Style Memory 管理 (Phase 2)
# ============================================================

def count_important_rules(style_guide_path: Path) -> int:
    if not style_guide_path.exists():
        return 0
    text = style_guide_path.read_text(encoding="utf-8")
    m = re.search(r"^## IMPORTANT Rules\s*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if not m:
        return 0
    return len(re.findall(r"^- ", m.group(1), re.MULTILINE))


def check_important_rule_limit() -> bool:
    return count_important_rules(STYLE_MEMORY_DIR / "style_guide.md") >= IMPORTANT_RULE_MAX


def build_retirement_context(state: RunState) -> str:
    sg = STYLE_MEMORY_DIR / "style_guide.md"
    text = sg.read_text(encoding="utf-8") if sg.exists() else ""
    return (f"## 現在のstyle_guide.md\n\n{text}\n\n"
            "## IMPORTANTルール数が上限(15)に達しています。\n"
            "直近3イテレーションで一度も違反がなかったルールを退役（Learned Rulesに降格）してください。\n")


def should_run_consolidator() -> bool:
    sg = STYLE_MEMORY_DIR / "style_guide.md"
    if not sg.exists():
        return False
    return len(sg.read_text().splitlines()) > 200


def get_recent_learning_log(limit: int = 10) -> str:
    log_path = STYLE_MEMORY_DIR / "learning_log.md"
    if not log_path.exists():
        return ""
    text = log_path.read_text(encoding="utf-8")
    sections = re.split(r"(?=^## run_)", text, flags=re.MULTILINE)
    sections = [s.strip() for s in sections if s.strip().startswith("## run_")]
    recent = sections[-limit:] if len(sections) > limit else sections
    return "\n\n---\n\n".join(recent)


def filter_style_rules(style_guide_path: Path, categories: list) -> str:
    if not style_guide_path.exists():
        return ""
    text = style_guide_path.read_text(encoding="utf-8")
    categories_set = set(categories)
    sections = re.split(r"(?=^## )", text, flags=re.MULTILINE)
    filtered_sections = []
    total_matched = 0

    for section in sections:
        lines = section.split("\n")
        filtered_lines = []
        include_current_rule = False
        for line in lines:
            if line.startswith("## ") or line.startswith("# ") or line.startswith("<!--"):
                filtered_lines.append(line)
                continue
            tag_match = re.match(r"^- \[(\w+)\]", line)
            if tag_match:
                tag = tag_match.group(1)
                include_current_rule = tag in categories_set
                if include_current_rule:
                    filtered_lines.append(line)
                    total_matched += 1
                continue
            elif line.startswith("- "):
                include_current_rule = "uncategorized" in categories_set
                if include_current_rule:
                    filtered_lines.append(line)
                    total_matched += 1
                continue
            if line.startswith("  ") and include_current_rule:
                filtered_lines.append(line)
                continue
            if not line.strip():
                filtered_lines.append(line)
        filtered_sections.append("\n".join(filtered_lines))

    if total_matched == 0:
        return text
    return "\n".join(filtered_sections)


# ============================================================
# Agent Memory 管理 (Phase 2)
# ============================================================

def _load_yaml(path: Path) -> dict:
    if yaml:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def _dump_yaml(data: dict, path: Path):
    if yaml:
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
    else:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def filter_agent_memory(article_type: str, limit: int = 5) -> list:
    if not AGENT_MEMORY_DIR.exists():
        return []
    entries = []
    for yf in sorted(AGENT_MEMORY_DIR.glob("run_*.yaml"), reverse=True):
        try:
            e = _load_yaml(yf)
            if e:
                entries.append(e)
        except Exception:
            continue
    if article_type == "Strategist":
        return entries[:limit]
    matched = [e for e in entries if e.get("article_type") == article_type]
    with_fb = [e for e in matched if e.get("human_feedback") is not None]
    without_fb = [e for e in matched if e.get("human_feedback") is None]
    return (with_fb + without_fb)[:limit]


def write_agent_memory(run_id: str, state: RunState, registry: "AgentRegistry"):
    AGENT_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    agents_used = []
    for name, info in registry.list_all().items():
        agents_used.append({"name": name, "type": info.get("type", "unknown"),
                            "invocations": info.get("invocations", 0)})
    fb_summary = {}
    for pname, pfb in state.fb_log.items():
        iters = pfb.get("iterations", [])
        if iters:
            last = iters[-1]
            majors = [i["detail"] for i in last.get("issues", [])
                      if i.get("severity") == "major" and not i.get("resolved", False)]
            rate = 1.0
            if len(iters) >= 2:
                diff = compute_fb_diff(pfb, iters[-2]["iteration"], iters[-1]["iteration"])
                rate = diff.get("resolution_rate", 1.0)
            fb_summary[pname] = {"final_resolution_rate": rate, "remaining_major_issues": majors}

    data = {
        "run_id": run_id, "created_at": datetime.now().isoformat(),
        "article_type": state.article_type, "user_instruction": state.user_instruction,
        "agents_used": agents_used,
        "final_score": state.get_scores("article_review")[-1] if state.get_scores("article_review") else 0.0,
        "score_by_axis": {p: axes[-1] if axes else {} for p, axes in state.axis_scores_history.items()},
        "iterations_used": {p: len(s) for p, s in state.scores.items()},
        "escalations": {p: state.is_escalated(p) for p in state.scores},
        "fb_summary": fb_summary, "human_feedback": None,
    }
    _dump_yaml(data, AGENT_MEMORY_DIR / f"run_{run_id}.yaml")


def update_human_feedback(run_id: str, feedback_data: dict):
    mp = AGENT_MEMORY_DIR / f"run_{run_id}.yaml"
    if not mp.exists():
        raise FileNotFoundError(f"Agent memory not found: {mp}")
    data = _load_yaml(mp)
    data["human_feedback"] = feedback_data
    _dump_yaml(data, mp)


# ============================================================
# ベンチマーク管理 (Phase 2)
# ============================================================

def load_bench_index() -> dict:
    ip = HUMAN_BENCH_DIR / "index.yaml"
    if not ip.exists():
        return {"articles": []}
    return _load_yaml(ip)


def get_reference_candidates(index: dict, quality_field: str, quality_value: str = "high") -> list:
    return [a for a in index.get("articles", []) if a.get(quality_field) == quality_value]


def load_bench_article(file_path: str) -> str:
    fp = HUMAN_BENCH_DIR / "articles" / file_path
    return fp.read_text(encoding="utf-8") if fp.exists() else ""


def resolve_references(strategy_text: str) -> dict:
    result = {"material": {}, "style": {}}
    try:
        if yaml:
            ym = re.search(r"```yaml\s*\n(.*?)\n```", strategy_text, re.DOTALL)
            data = yaml.safe_load(ym.group(1)) if ym else yaml.safe_load(strategy_text)
            if data and isinstance(data, dict):
                for ref in data.get("material_references", []):
                    f = ref.get("file", "")
                    if f:
                        result["material"][f] = load_bench_article(f)
                for ref in data.get("style_references", []):
                    f = ref.get("file", "")
                    if f:
                        result["style"][f] = load_bench_article(f)
    except Exception:
        pass
    return result


# ============================================================
# 実行履歴保存 (Phase 2)
# ============================================================

def save_scores(run_id: str, state: RunState):
    rd = RUNS_DIR / run_id
    rd.mkdir(parents=True, exist_ok=True)
    with open(rd / "scores.json", "w", encoding="utf-8") as f:
        json.dump(state.scores, f, ensure_ascii=False, indent=2)


def save_summary(run_id: str, state: RunState, partial: bool = False, error: str = None):
    rd = RUNS_DIR / run_id
    rd.mkdir(parents=True, exist_ok=True)
    summary = {
        "run_id": run_id, "article_type": state.article_type,
        "user_instruction": state.user_instruction, "scores": state.scores,
        "escalations": state.escalated,
        "metrics_history": {str(k): v for k, v in state.metrics_history.items()},
        "token_usage": state.token_usage,
        "partial": partial, "completed_at": datetime.now().isoformat(),
    }
    if error:
        summary["error"] = error
    with open(rd / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


# ============================================================
# AgentRegistry (Phase 3)
# ============================================================

class AgentRegistry:
    def __init__(self):
        self._agents = {}

    def register(self, name: str, definition_path: str, agent_type: str = "template", phase: str = ""):
        self._agents[name] = {
            "definition_path": definition_path, "type": agent_type, "phase": phase,
            "status": "registered", "invocations": 0, "last_output_chars": 0,
        }

    def get(self, name: str) -> dict:
        if name not in self._agents:
            raise AgentNotFoundError(f"Agent not found: {name}")
        return self._agents[name]

    def exists(self, name: str) -> bool:
        return name in self._agents

    def update_status(self, name: str, status: str):
        if name in self._agents:
            self._agents[name]["status"] = status

    def increment_invocations(self, name: str):
        if name in self._agents:
            self._agents[name]["invocations"] += 1

    def record_output_size(self, name: str, chars: int):
        if name in self._agents:
            self._agents[name]["last_output_chars"] = chars

    def list_by_phase(self, phase_name: str) -> dict:
        return {n: i for n, i in self._agents.items() if i["phase"] == phase_name}

    def list_all(self) -> dict:
        return dict(self._agents)

    def summary(self) -> str:
        lines = ["=== Agent Registry ==="]
        for name, info in self._agents.items():
            lines.append(f"  {name}: {info['status']} (type={info['type']}, invocations={info['invocations']})")
        return "\n".join(lines)


def extract_agent_type(agent_def_path: Path) -> str:
    if not agent_def_path.exists():
        return "unknown"
    text = agent_def_path.read_text(encoding="utf-8")
    m = re.search(r"^type:\s*(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else "template"


def build_registry(workflow: dict) -> AgentRegistry:
    registry = AgentRegistry()
    for phase in workflow.get("phases", []):
        for agent_name in phase.get("agents", []):
            dp = AGENTS_GENERATED_DIR / f"{agent_name}.md"
            registry.register(agent_name, str(dp), extract_agent_type(dp), phase["name"])
            registry.update_status(agent_name, "validated")
    return registry


# ============================================================
# 自動メトリクス (Phase 4)
# ============================================================

def compute_code_ratio(text: str) -> float:
    lines = text.split("\n")
    if not lines:
        return 0.0
    in_code, code_lines = False, 0
    for line in lines:
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            code_lines += 1
    return code_lines / len(lines)


def compute_desu_masu_ratio(text: str) -> float:
    # コードブロックを除去
    text_no_code = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    # テーブル行を除去
    lines = [l for l in text_no_code.split('\n') if not l.strip().startswith('|')]
    clean_text = '\n'.join(lines)
    sentences = re.split(r'[。！？\n]', clean_text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 5]
    if not sentences:
        return 1.0
    # 末尾の括弧・記号を無視してです・ます体を検出
    dm = sum(1 for s in sentences if re.search(
        r'(です|ます|でした|ました|でしょう|ません|でしょうか|ませんか)\s*[）)」』\s]*$', s))
    return dm / len(sentences)


def compute_section_length_ratio(text: str) -> float:
    sections = re.split(r'^##\s', text, flags=re.MULTILINE)
    sections = [s for s in sections if s.strip()]
    if len(sections) < 2:
        return 1.0
    lengths = [len(s.strip().split("\n")) for s in sections]
    return max(lengths) / max(min(lengths), 1)


def compute_max_consecutive_same_band(text: str) -> int:
    sentences = re.split(r'[。！？]', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 3]
    if not sentences:
        return 0
    def band(l):
        return "short" if l < 20 else ("medium" if l < 50 else "long")
    mx, cur = 1, 1
    for i in range(1, len(sentences)):
        if band(len(sentences[i])) == band(len(sentences[i - 1])):
            cur += 1
            mx = max(mx, cur)
        else:
            cur = 1
    return mx


def compute_sentence_length_stddev(text: str) -> float:
    sentences = re.split(r'[。！？]', text)
    lengths = [len(s.strip()) for s in sentences if len(s.strip()) > 3]
    if len(lengths) < 2:
        return 0.0
    mean = sum(lengths) / len(lengths)
    return (sum((l - mean) ** 2 for l in lengths) / len(lengths)) ** 0.5


def compute_total_chars(text: str) -> int:
    return len(text)


def compute_metrics(article_text: str) -> dict:
    return {
        "code_ratio": compute_code_ratio(article_text),
        "desu_masu_ratio": compute_desu_masu_ratio(article_text),
        "section_length_ratio": compute_section_length_ratio(article_text),
        "max_consecutive_same_band": compute_max_consecutive_same_band(article_text),
        "sentence_length_stddev": compute_sentence_length_stddev(article_text),
        "total_chars": compute_total_chars(article_text),
    }


def build_metrics_context(metrics: dict, strategy: dict = None) -> str:
    warnings = []
    if metrics.get("code_ratio", 0) > 0.20:
        warnings.append(f"- コード比率: {metrics['code_ratio']:.1%}（閾値: ≤20%）")
    if metrics.get("desu_masu_ratio", 1) < 0.80:
        warnings.append(f"- です・ます比率: {metrics['desu_masu_ratio']:.1%}（閾値: ≥80%）")
    if metrics.get("max_consecutive_same_band", 0) > 4:
        warnings.append(f"- 連続同長文帯: {metrics['max_consecutive_same_band']}文（閾値: ≤4文）")
    return ("## 自動メトリクス警告\n\n" + "\n".join(warnings) + "\n") if warnings else ""


# ============================================================
# スコア抽出 (Phase 4)
# ============================================================

def extract_overall_score(review_text: str) -> float:
    # 複数フォーマットに対応:
    #   "## Overall: 8.3/10"
    #   "**overall_score: 7.2 / 10.0**"
    #   "overall_score: 0.865"  (0-1スケール)
    #   "Overall Score: 8.3/10"
    patterns = [
        r"##\s*Overall:\s*([\d.]+)\s*/\s*10",
        r"\*?\*?overall_score:\s*([\d.]+)\s*/\s*10\.?0?\*?\*?",
        r"Overall\s*Score:\s*([\d.]+)\s*/\s*10",
        r"overall[_\s]*score:\s*([\d.]+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, review_text, re.IGNORECASE)
        if m:
            score = float(m.group(1))
            # 0-1スケールの場合は10倍にする
            if score <= 1.0 and "/10" not in review_text[m.start():m.end()+5]:
                score = score * 10
            return score
    raise ScoreExtractionError("Overall score not found in review output")


def extract_axis_scores(review_text: str) -> dict:
    scores = {}
    for m in re.finditer(r"### [SA]\d+\.\s*(.+?):\s*([\d.]+)/10", review_text):
        scores[m.group(1).strip()] = float(m.group(2))
    return scores


# ============================================================
# プロンプト組み立て (Phase 4)
# ============================================================

def read_agent_definition(name: str) -> str:
    for d in [AGENTS_GENERATED_DIR, AGENT_TEMPLATES_DIR]:
        p = d / f"{name}.md"
        if p.exists():
            return p.read_text(encoding="utf-8")
    return ""


def build_agent_prompt(agent_name: str, agent_def: dict, state: RunState) -> str:
    dp = Path(agent_def.get("definition_path", ""))
    definition = dp.read_text(encoding="utf-8") if dp.exists() else read_agent_definition(agent_name)

    style_rules = ""
    if agent_name in ("writer", "article_reviewer", "material_reviewer"):
        sp = PROJECT_ROOT / "strategy.md"
        categories = []
        if sp.exists():
            st = sp.read_text(encoding="utf-8")
            cm = re.search(r"priority_style_categories:\s*\n((?:\s*-\s*.+\n)+)", st)
            if cm:
                categories = [c.strip().strip("-").strip().strip('"').strip("'")
                              for c in cm.group(1).strip().split("\n") if c.strip()]
        if categories:
            style_rules = filter_style_rules(STYLE_MEMORY_DIR / "style_guide.md", categories)
        else:
            sg = STYLE_MEMORY_DIR / "style_guide.md"
            style_rules = sg.read_text(encoding="utf-8") if sg.exists() else ""

    prompt = f"あなたは {agent_name} エージェントです。\n\n{definition}\n\n## プロジェクトルート\n{PROJECT_ROOT}\n\n"
    if agent_name == "writer":
        prompt += ("## 【絶対ルール — 文体】\n"
                   "- 全文をです・ます体で書くこと。「〜です」「〜ます」「〜ました」「〜でしょう」で終わる文を基本とする\n"
                   "- 「だ」「である」「した。」「なかった。」（だ/である調）は1文も使わないこと\n"
                   "- 体言止め（名詞で文を終える）も禁止\n"
                   "- カジュアル表現（「〜なんですよね」「まあ正直」「で、結局〜」）は許可\n"
                   "- このルールは他の全てのルールより優先する\n\n")
    if style_rules:
        prompt += f"## Style Guide（フィルタ済み）\n\n{style_rules}\n\n"
    if "reviewer" in agent_name:
        ec = PROJECT_ROOT / "eval_criteria.md"
        if ec.exists():
            prompt += f"## 評価基準\n\n{ec.read_text(encoding='utf-8')}\n\n"
    if agent_name == "writer":
        strat = PROJECT_ROOT / "strategy.md"
        if strat.exists():
            prompt += f"## 戦略\n\n{strat.read_text(encoding='utf-8')}\n\n"
        # fixed/配下の素材
        for f in sorted((MATERIALS_DIR / "fixed").glob("*.md")):
            prompt += f"## 素材: fixed/{f.name}\n\n{f.read_text(encoding='utf-8')}\n\n"
        # materials/直下の全.mdファイル（fixed/配下は上で処理済み、globは直下のみ）
        for f in sorted(MATERIALS_DIR.glob("*.md")):
            content = f.read_text(encoding="utf-8")
            prompt += f"## 素材: {f.name}\n\n{content}\n\n"

    # code_analyzer: ソースファイルを埋め込む
    if agent_name == "code_analyzer":
        src = Path(state.source_dir) if Path(state.source_dir).is_absolute() else PROJECT_ROOT / state.source_dir
        if src.is_dir():
            for f in sorted(src.rglob("*")):
                if f.is_file() and f.suffix in (".md", ".py", ".ts", ".js", ".json", ".yaml", ".yml", ".txt"):
                    rel = f.relative_to(src)
                    prompt += f"## ソースファイル: {rel}\n\n{f.read_text(encoding='utf-8')}\n\n"
        prompt += f"## 出力\n以下の5ファイルの内容を、それぞれ独立した見出しセクション（## architecture / ## key_decisions / ## interesting_patterns / ## struggles / ## code_snippets）で出力してください。各セクション最低1500文字以上。\n- architecture.md — 全体構成・設計思想\n- key_decisions.md — 技術選定理由・トレードオフ\n- interesting_patterns.md — 特徴的な実装パターン\n- struggles.md — 苦労した箇所・失敗・リファクタ履歴\n- code_snippets.md — コードスニペット集\n\n"

    # trend_searcher: knowledge/とstrategy.mdを埋め込む
    if agent_name == "trend_searcher":
        strat = PROJECT_ROOT / "strategy.md"
        if strat.exists():
            prompt += f"## 戦略\n\n{strat.read_text(encoding='utf-8')}\n\n"
        for fn in ["trends.md", "reader_pains.md"]:
            kp = KNOWLEDGE_DIR / fn
            if kp.exists():
                content = kp.read_text(encoding="utf-8")[:5000]
                prompt += f"## 既存knowledge: {fn}\n\n{content}\n\n"
        prompt += "## 出力\nトレンドと読者ペインの調査結果を出力してください。\n\n"

    # dev_simulator: ソース+素材を埋め込む
    if agent_name == "dev_simulator":
        src = Path(state.source_dir) if Path(state.source_dir).is_absolute() else PROJECT_ROOT / state.source_dir
        if src.is_dir():
            for f in sorted(src.rglob("*")):
                if f.is_file() and f.suffix in (".md", ".py", ".ts", ".js", ".json", ".yaml", ".yml", ".txt"):
                    rel = f.relative_to(src)
                    prompt += f"## ソースファイル: {rel}\n\n{f.read_text(encoding='utf-8')}\n\n"
        for fn in ["trend_context.md", "reader_pain.md"]:
            fp = MATERIALS_DIR / fn
            if fp.exists():
                prompt += f"## 素材: {fn}\n\n{fp.read_text(encoding='utf-8')}\n\n"
        fixed = MATERIALS_DIR / "fixed" / "architecture.md"
        if fixed.exists():
            prompt += f"## 素材: architecture.md\n\n{fixed.read_text(encoding='utf-8')}\n\n"
        prompt += "## 出力\n開発シミュレーションの対話ログを出力してください。\n\n"

    # material_updater: レビュー結果+素材を埋め込む（素材ファイルの上書きが必要）
    if agent_name == "material_updater":
        for f in (MATERIALS_DIR / "fixed").glob("*.md"):
            prompt += f"## 現在の素材: {f.name}\n\n{f.read_text(encoding='utf-8')}\n\n"
        sim_log = MATERIALS_DIR / "dev_simulation_log.md"
        if sim_log.exists():
            prompt += f"## 現在の素材: dev_simulation_log.md\n\n{sim_log.read_text(encoding='utf-8')[:5000]}\n\n"

    # style_guide_updater: style_guide.mdを埋め込む
    if agent_name == "style_guide_updater":
        sg = STYLE_MEMORY_DIR / "style_guide.md"
        if sg.exists():
            prompt += f"## 現在のstyle_guide.md\n\n{sg.read_text(encoding='utf-8')}\n\n"

    # consolidator: style_guide.mdを埋め込む
    if agent_name == "consolidator":
        sg = STYLE_MEMORY_DIR / "style_guide.md"
        if sg.exists():
            prompt += f"## 現在のstyle_guide.md（圧縮対象）\n\n{sg.read_text(encoding='utf-8')}\n\n"
        prompt += "## 出力\n圧縮後のstyle_guide.md全文を出力してください。\n\n"

    return prompt


def build_escalation_prompt(phase_name: str, score_history: list, latest_review: str,
                           eval_criteria: str, options: dict, fb_diff: dict = None) -> str:
    opts = "\n".join(f"- {k}: {v['description']} (条件: {v['when']})" for k, v in options.items())
    prompt = (f"あなたはStrategist（エスカレーションモード）です。\n\n"
              f"## 状況\nフェーズ「{phase_name}」が停滞しています。\n\n"
              f"## スコア推移\n{json.dumps(score_history)}\n\n"
              f"## 直近のレビュー\n{latest_review[:3000]}\n\n"
              f"## 現在の評価基準\n{eval_criteria[:3000]}\n\n")
    if fb_diff:
        prompt += (f"## FB差分メトリクス\nresolution_rate: {fb_diff.get('resolution_rate', 'N/A')}\n"
                   f"resolved: {fb_diff.get('resolved', [])}\npersisted: {fb_diff.get('persisted', [])}\n"
                   f"new: {fb_diff.get('new', [])}\n\n")
    prompt += f"## 選択肢\n{opts}\n\n以下のフォーマットで1つ選んでください:\nACTION: <アクション名>\nREASON: <選択理由>\n"
    return prompt


def build_add_agent_prompt(strategy_path: Path, stagnant_axes: list) -> str:
    strat = strategy_path.read_text(encoding="utf-8") if strategy_path.exists() else ""
    return (f"あなたはAgent Editorです。\n\n以下の評価軸が停滞しています。専門エージェントを追加してください。\n\n"
            f"## 停滞軸\n{json.dumps(stagnant_axes, ensure_ascii=False)}\n\n## 現在の戦略\n{strat}\n\n"
            f"## 出力先\nagents/generated/ に新しいエージェント定義（.md）を生成してください。\n")


def build_eval_adjustment_prompt(eval_criteria_path: Path, latest_scores: list, filtered_memory: list) -> str:
    ec = eval_criteria_path.read_text(encoding="utf-8") if eval_criteria_path.exists() else ""
    return (f"あなたはEval Designerです。\n\n評価基準の重みが不適切な可能性があります。修正してください。\n\n"
            f"## 現在の評価基準\n{ec}\n\n## スコア推移\n{json.dumps(latest_scores)}\n\n"
            f"## 過去の実行記録\n{json.dumps(filtered_memory, ensure_ascii=False, default=str)[:3000]}\n\n"
            f"eval_criteria.md を修正して {eval_criteria_path} に上書き保存してください。\n")


def build_consolidator_prompt() -> str:
    sg = STYLE_MEMORY_DIR / "style_guide.md"
    return f"あなたはConsolidatorです。\n\n{sg} を読んで、内容を維持したまま200行以内に圧縮してください。\n上書き保存してください。\n"


# ============================================================
# MetaAgent 呼び出し (Phase 5)
# ============================================================

def call_strategist_plan(source_dir: str, user_instruction: str, state: RunState):
    source_path = Path(source_dir) if Path(source_dir).is_absolute() else PROJECT_ROOT / source_dir
    source_text = ""
    if source_path.is_dir():
        for f in sorted(source_path.rglob("*")):
            if f.is_file() and f.suffix in (".md", ".py", ".ts", ".js", ".json", ".yaml", ".yml", ".txt"):
                rel = f.relative_to(source_path)
                source_text += f"\n### {rel}\n\n{f.read_text(encoding='utf-8')}\n"
    elif source_path.is_file():
        source_text = source_path.read_text(encoding="utf-8")

    index = load_bench_index()
    idx_text = json.dumps(index, ensure_ascii=False, indent=2) if index.get("articles") else "（ペルソナ記事未登録）"
    mem = filter_agent_memory("Strategist", limit=10)
    mem_text = json.dumps(mem, ensure_ascii=False, default=str)[:5000] if mem else "（過去の実行記録なし）"
    learning = get_recent_learning_log(10)

    prompt = (f"あなたはStrategist（戦略立案モード）です。\n\n{read_agent_definition('strategist')}\n\n"
              f"## ソースファイル\n{source_text[:15000]}\n\n## ユーザーの方向性指定\n{user_instruction}\n\n"
              f"## ペルソナ記事インデックス\n{idx_text}\n\n## 過去の実行記録（直近10件）\n{mem_text}\n\n"
              f"## 過去の学び\n{learning}\n\n"
              f"## 出力\n{PROJECT_ROOT / 'strategy.md'} にstrategy.mdを保存してください。\n"
              "YAMLフォーマットで以下のフィールドを含めてください:\n"
              "- article_type, tone, tech_depth, emphasis, target_length\n"
              "- material_references (file + reason)\n- style_references (file + reason)\n"
              "- winning_strategy, death_patterns\n- priority_style_categories\n")

    output = call_agent_with_retry("strategist", prompt, state=state)
    sp = PROJECT_ROOT / "strategy.md"
    if not sp.exists():
        sp.write_text(output, encoding="utf-8")
    strat_text = sp.read_text(encoding="utf-8")
    tm = re.search(r'article_type:\s*"?([^"\n]+)"?', strat_text)
    state.article_type = tm.group(1).strip() if tm else "体験記"
    log(f"Strategy: article_type={state.article_type}")


def call_agent_editor(filtered_memory: list, state: RunState):
    strategy = (PROJECT_ROOT / "strategy.md").read_text(encoding="utf-8") if (PROJECT_ROOT / "strategy.md").exists() else ""
    templates = ""
    for f in sorted(AGENT_TEMPLATES_DIR.glob("*.md")):
        templates += f"\n### {f.name}\n\n{f.read_text(encoding='utf-8')[:2000]}\n"
    mem_text = json.dumps(filtered_memory, ensure_ascii=False, default=str)[:3000] if filtered_memory else ""

    prompt = (f"あなたはAgent Editorです。\n\n{read_agent_definition('agent_editor')}\n\n"
              f"## 戦略\n{strategy}\n\n## エージェントテンプレート\n{templates}\n\n"
              f"## 過去の実行記録\n{mem_text}\n\n"
              "## 出力\n1. agents/generated/ にエージェント定義ファイル（.md）を生成\n"
              "2. agents/generated/workflow.json にワークフロー定義を生成\n\n"
              "各エージェント定義にはフロントマター（name, base_template, type, phase）を含めてください。\n\n"
              'workflow.json形式:\n{"phases": [{"name": "...", "agents": [...], "loop": false, "parallel": false}, ...]}\n')

    call_agent_with_retry("agent_editor", prompt, state=state)

    # デフォルトworkflow.json
    wf_path = AGENTS_GENERATED_DIR / "workflow.json"
    if not wf_path.exists():
        default_wf = {"phases": [
            {"name": "material_generation", "agents": ["code_analyzer", "trend_searcher", "dev_simulator"],
             "loop": False, "parallel": True},
            {"name": "material_review", "agents": ["material_reviewer", "material_updater"],
             "loop": True, "max_iterations": 5, "score_threshold": 8.0,
             "stagnation_window": 3, "stagnation_tolerance": 0.5},
            {"name": "article_review", "agents": ["writer", "article_reviewer", "narrative_puncher", "style_guide_updater"],
             "loop": True, "max_iterations": 10, "score_threshold": 9.0,
             "stagnation_window": 3, "stagnation_tolerance": 0.5, "allow_material_fallback": True},
        ]}
        with open(wf_path, "w", encoding="utf-8") as f:
            json.dump(default_wf, f, indent=2, ensure_ascii=False)

    # テンプレートからコピー
    wf = json.loads(wf_path.read_text(encoding="utf-8"))
    for phase in wf.get("phases", []):
        for an in phase.get("agents", []):
            gp = AGENTS_GENERATED_DIR / f"{an}.md"
            if not gp.exists():
                tp = AGENT_TEMPLATES_DIR / f"{an}.md"
                if tp.exists():
                    shutil.copy(tp, gp)
                else:
                    gp.write_text(f"---\nname: {an}\nbase_template: null\ntype: generated\nphase: {phase['name']}\n---\n\n"
                                  f"# {an}\n\n## 役割\n{an}エージェント\n\n## 入力\n指示に従う\n\n## 出力\n指定ファイルに出力\n\n## 指示\nタスクを実行してください。\n")


def call_eval_designer(filtered_memory: list, state: RunState):
    sp = PROJECT_ROOT / "strategy.md"
    strategy = sp.read_text(encoding="utf-8") if sp.exists() else ""
    refs = resolve_references(strategy)
    ref_text = ""
    for label, articles in refs.items():
        for fname, content in articles.items():
            if content:
                ref_text += f"\n### {label}: {fname}\n\n{content[:3000]}\n"
    sg = STYLE_MEMORY_DIR / "style_guide.md"
    style_guide = sg.read_text(encoding="utf-8") if sg.exists() else ""
    mem_text = json.dumps(filtered_memory, ensure_ascii=False, default=str)[:3000] if filtered_memory else ""

    prompt = (f"あなたはEval Designerです。\n\n{read_agent_definition('eval_designer')}\n\n"
              f"## 戦略\n{strategy}\n\n## 参考記事\n{ref_text}\n\n## Style Guide\n{style_guide}\n\n"
              f"## 過去の実行記録\n{mem_text}\n\n"
              f"## 出力\n{PROJECT_ROOT / 'eval_criteria.md'} にeval_criteria.mdを保存してください。\n")
    output = call_agent_with_retry("eval_designer", prompt, state=state)
    ec = PROJECT_ROOT / "eval_criteria.md"
    if not ec.exists():
        ec.write_text(output, encoding="utf-8")


def call_strategist_retrospective(state: RunState):
    strategy = (PROJECT_ROOT / "strategy.md").read_text(encoding="utf-8") if (PROJECT_ROOT / "strategy.md").exists() else ""
    fb_text = json.dumps(state.fb_log, ensure_ascii=False, default=str)[:5000]
    prompt = (f"あなたはStrategist（振り返りモード）です。\n\n{read_agent_definition('strategist')}\n\n"
              f"## 今回の戦略\n{strategy[:3000]}\n\n## スコア推移\n{json.dumps(state.scores, default=str)}\n\n"
              f"## FB構造化ログ\n{fb_text}\n\n"
              f"## 出力\n{STYLE_MEMORY_DIR / 'learning_log.md'} に以下を追記:\n"
              f"## run_{state.run_id}: {state.article_type}\n"
              "### 勝ち筋の実現度\n### 評価軸の妥当性\n### カスタムエージェントの効果\n### FB残存率の分析\n### 次回への学び\n")
    call_agent_with_retry("strategist", prompt, state=state)


def call_strategist_escalation(phase_name: str, state: RunState, scores: list,
                                iteration: int, fb_diff: dict = None) -> str:
    latest_review = ""
    if "material" in phase_name:
        rp = MATERIAL_REVIEWS_DIR / f"review_{iteration}.md"
        if rp.exists():
            latest_review = rp.read_text(encoding="utf-8")
    else:
        rp = ITERATIONS_DIR / str(iteration) / "review.md"
        if rp.exists():
            latest_review = rp.read_text(encoding="utf-8")
    ec = (PROJECT_ROOT / "eval_criteria.md").read_text(encoding="utf-8") if (PROJECT_ROOT / "eval_criteria.md").exists() else ""
    options = ESCALATION_OPTIONS["material_review"] if "material" in phase_name else ESCALATION_OPTIONS["article"]
    prompt = build_escalation_prompt(phase_name, scores, latest_review, ec, options, fb_diff)
    return call_agent_with_retry("strategist", prompt, state=state)


# ============================================================
# ワークフロー管理 (Phase 6)
# ============================================================

def load_workflow() -> dict:
    wf = AGENTS_GENERATED_DIR / "workflow.json"
    if not wf.exists():
        raise WorkflowLoadError(f"workflow.json not found: {wf}")
    with open(wf, encoding="utf-8") as f:
        return json.load(f)


def find_phase_by_name(workflow: dict, name: str) -> Optional[dict]:
    for p in workflow.get("phases", []):
        if p["name"] == name:
            return p
    return None


def validate_workflow_schema(workflow: dict):
    errors = []
    if "phases" not in workflow:
        errors.append("Missing 'phases' key")
    names = set()
    for i, p in enumerate(workflow.get("phases", [])):
        pn = p.get("name", f"phase_{i}")
        if "name" not in p:
            errors.append(f"Phase {i}: missing 'name'")
        elif pn in names:
            errors.append(f"Phase {i}: duplicate name '{pn}'")
        else:
            names.add(pn)
        if "agents" not in p:
            errors.append(f"Phase {pn}: missing 'agents'")
        if p.get("loop") and "max_iterations" not in p:
            errors.append(f"Phase {pn}: loop=true but no max_iterations")
        for a in p.get("agents", []):
            if not (AGENTS_GENERATED_DIR / f"{a}.md").exists():
                errors.append(f"Phase {pn}: agent '{a}' definition not found")
    if errors:
        raise WorkflowValidationError("\n".join(errors))


# ============================================================
# フェーズディスパッチ + 並列実行 (Phase 6)
# ============================================================

def dispatch_phase(phase: dict, registry: AgentRegistry, state: RunState):
    pn = phase["name"]
    state.log.append(f"[{pn}] Phase started")
    log(f"=== PHASE: {pn} ===")
    if phase.get("parallel", False):
        asyncio.run(execute_parallel(phase, registry, state))
    elif phase.get("loop", False):
        execute_pdca_loop(phase, registry, state)
    else:
        execute_sequential(phase, registry, state)
    state.log.append(f"[{pn}] Phase completed")


def execute_sequential(phase: dict, registry: AgentRegistry, state: RunState):
    for an in phase["agents"]:
        ad = registry.get(an)
        prompt = build_agent_prompt(an, ad, state)
        output = call_agent_with_retry(an, prompt, state=state)
        registry.update_status(an, "completed")
        registry.increment_invocations(an)
        registry.record_output_size(an, len(output))
        _save_agent_output(an, output)
        verify_agent_outputs(an, ad)


async def execute_parallel(phase: dict, registry: AgentRegistry, state: RunState):
    tasks = []
    for an in phase["agents"]:
        ad = registry.get(an)
        prompt = build_agent_prompt(an, ad, state)
        tasks.append(_run_agent_async(an, prompt, registry, state))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            raise r


async def _run_agent_async(name: str, prompt: str, registry: AgentRegistry,
                           state: Optional[RunState] = None) -> str:
    output = await call_agent_async_with_retry(name, prompt, state=state)
    registry.update_status(name, "completed")
    registry.increment_invocations(name)
    registry.record_output_size(name, len(output))
    _save_agent_output(name, output)
    return output


def _save_agent_output(agent_name: str, output: str):
    """--add-dir廃止に伴い、エージェント出力をorchestrator側でファイルに保存する"""
    if not output or not output.strip():
        return

    if agent_name == "code_analyzer":
        fixed_dir = MATERIALS_DIR / "fixed"
        fixed_dir.mkdir(parents=True, exist_ok=True)
        # セクション見出しで分割を試みる（テンプレート通りの5ファイル、英語+日本語対応）
        # 長いキーを先に走査（誤マッチ防止）
        file_map = {
            "architecture": "architecture.md",
            "アーキテクチャ": "architecture.md",
            "key_decisions": "key_decisions.md",
            "key decisions": "key_decisions.md",
            "技術選定": "key_decisions.md",
            "設計判断": "key_decisions.md",
            "interesting_patterns": "interesting_patterns.md",
            "interesting patterns": "interesting_patterns.md",
            "実装パターン": "interesting_patterns.md",
            "特徴的な実装": "interesting_patterns.md",
            "struggles": "struggles.md",
            "苦労": "struggles.md",
            "失敗": "struggles.md",
            "試行錯誤": "struggles.md",
            "code_snippets": "code_snippets.md",
            "code snippets": "code_snippets.md",
            "コードスニペット": "code_snippets.md",
            "スニペット": "code_snippets.md",
        }
        # ##見出しで分割
        sections = re.split(r'^#{1,3}\s+', output, flags=re.MULTILINE)
        section_headers = re.findall(r'^(#{1,3}\s+.+)$', output, re.MULTILINE)
        saved_any = False
        for i, header in enumerate(section_headers):
            header_lower = header.lower()
            for key, fname in file_map.items():
                if key.replace("_", " ") in header_lower or key in header_lower:
                    content = sections[i + 1] if i + 1 < len(sections) else ""
                    (fixed_dir / fname).write_text(content.strip(), encoding="utf-8")
                    saved_any = True
                    break
        # フォールバック: 分割できなければ全文をarchitecture.mdに
        if not saved_any:
            (fixed_dir / "architecture.md").write_text(output, encoding="utf-8")
        # 空ファイルがあれば最低限のプレースホルダーを入れる（set()で重複排除）
        for fname in set(file_map.values()):
            fp = fixed_dir / fname
            if not fp.exists() or fp.stat().st_size == 0:
                fp.write_text(f"（{fname}: code_analyzerの出力から抽出できませんでした）", encoding="utf-8")

    elif agent_name == "trend_searcher":
        # 「読者ペイン」セクションで分割を試みる
        pain_patterns = [
            r'^#{1,3}\s+.*読者ペイン',
            r'^#{1,3}\s+.*読者が求めている',
            r'^#{1,3}\s+.*Reader Pain',
        ]
        trend_part = output
        pain_part = ""
        for pat in pain_patterns:
            m = re.search(pat, output, re.MULTILINE | re.IGNORECASE)
            if m:
                trend_part = output[:m.start()].rstrip()
                pain_part = output[m.start():].strip()
                break
        if not (MATERIALS_DIR / "trend_context.md").exists():
            (MATERIALS_DIR / "trend_context.md").write_text(
                trend_part if trend_part.strip() else output, encoding="utf-8")
        if not (MATERIALS_DIR / "reader_pain.md").exists():
            (MATERIALS_DIR / "reader_pain.md").write_text(
                pain_part if pain_part.strip() else output[:2000], encoding="utf-8")

    elif agent_name == "dev_simulator":
        # テンプレート指定: sim_log.md + sim_highlights.md + sim_metadata.json の3ファイル
        sim_file_map = {
            "sim_log": "sim_log.md",
            "sim log": "sim_log.md",
            "会話ログ": "sim_log.md",
            "sim_highlights": "sim_highlights.md",
            "sim highlights": "sim_highlights.md",
            "名場面": "sim_highlights.md",
            "ハイライト": "sim_highlights.md",
            "sim_metadata": "sim_metadata.json",
            "sim metadata": "sim_metadata.json",
            "メタデータ": "sim_metadata.json",
        }
        sections = re.split(r'^#{1,3}\s+', output, flags=re.MULTILINE)
        section_headers = re.findall(r'^(#{1,3}\s+.+)$', output, re.MULTILINE)
        saved_any = False
        for i, header in enumerate(section_headers):
            header_lower = header.lower()
            for key, fname in sim_file_map.items():
                if key.replace("_", " ") in header_lower or key in header_lower:
                    content = sections[i + 1] if i + 1 < len(sections) else ""
                    (MATERIALS_DIR / fname).write_text(content.strip(), encoding="utf-8")
                    saved_any = True
                    break
        # フォールバック: 分割失敗なら dev_simulation_log.md に全文（既存互換）
        if not saved_any:
            if not (MATERIALS_DIR / "dev_simulation_log.md").exists():
                (MATERIALS_DIR / "dev_simulation_log.md").write_text(output, encoding="utf-8")

    elif agent_name == "style_guide_updater":
        sg = STYLE_MEMORY_DIR / "style_guide.md"
        lines = output.strip().split("\n")
        if len(lines) >= 10:
            # 「# Style Guide」で始まる行を探し、そこ以降だけを保存（報告テキスト除去）
            sg_match = re.search(r'^# Style Guide\s*$', output, re.MULTILINE)
            if sg_match:
                clean_output = output[sg_match.start():].strip()
                if len(clean_output.split("\n")) >= 10:
                    sg.write_text(clean_output, encoding="utf-8")

    elif agent_name == "consolidator":
        sg = STYLE_MEMORY_DIR / "style_guide.md"
        if output.strip() and len(output) > 50:
            sg.write_text(output, encoding="utf-8")

    elif agent_name == "writer_handoff_generator":
        hp = MATERIALS_DIR / "writer_handoff.md"
        if output.strip():
            hp.write_text(output, encoding="utf-8")


def verify_agent_outputs(agent_name: str, agent_def: dict):
    dp = Path(agent_def.get("definition_path", ""))
    if not dp.exists():
        return
    text = dp.read_text(encoding="utf-8")
    om = re.search(r"## 出力\s*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if not om:
        return
    for line in om.group(1).split("\n"):
        line = line.strip().lstrip("- ")
        if line and "/" in line:
            p = PROJECT_ROOT / line.strip() if not line.startswith("/") else Path(line.strip())
            if not p.exists():
                log(f"WARNING: Expected output not found: {p}")


# ============================================================
# PDCA ループ (Phase 7)
# ============================================================

ESCALATION_OPTIONS = {
    "material_review": {
        "RESIMULATE": {"description": "Dev Simulatorを追加ラウンドで再実行する", "when": "素材の体験ログが薄い場合"},
        "RESEARCH": {"description": "Trend Searcherを別キーワードで再実行する", "when": "トレンド接続が弱い場合"},
        "ADJUST_EVAL": {"description": "素材評価軸の重みを修正する", "when": "評価軸の重みが不適切な場合"},
        "ABORT": {"description": "現状のベストで素材を確定する", "when": "これ以上の改善が困難な場合"},
    },
    "article": {
        "ADJUST_EVAL": {"description": "eval_criteriaの重みを修正する", "when": "特定軸のスコアが伸びない場合"},
        "MATERIAL_FALLBACK": {"description": "素材が弱い。素材PDCAに差し戻す", "when": "記事の問題が素材に起因する場合"},
        "ADD_AGENT": {"description": "専門エージェントの追加を指示する", "when": "特定の評価軸が一貫して低い場合"},
        "CONSOLIDATE": {"description": "style_guide.mdを圧縮する", "when": "ルールが多すぎて矛盾している場合"},
        "ABORT": {"description": "現状のベストで記事を確定する", "when": "これ以上の改善が困難な場合"},
    },
}


def execute_pdca_loop(phase: dict, registry: AgentRegistry, state: RunState):
    pn = phase["name"]
    max_iter = phase["max_iterations"]
    threshold = phase.get("score_threshold")
    sw = phase.get("stagnation_window", 3)
    st = phase.get("stagnation_tolerance", 0.5)
    allow_fb = phase.get("allow_material_fallback", False)

    for iteration in range(1, max_iter + 1):
        state.log.append(f"[{pn}] Iteration {iteration}/{max_iter}")
        log(f"--- {pn} Iteration {iteration}/{max_iter} ---")

        result = run_iteration(phase, registry, state, iteration)
        score = result["overall_score"]
        state.add_score(pn, score)
        scores = state.get_scores(pn)
        # 軸別スコアを蓄積
        if result.get("scores_by_axis"):
            if pn not in state.axis_scores_history:
                state.axis_scores_history[pn] = []
            state.axis_scores_history[pn].append(result["scores_by_axis"])
        log(f"Score: {score:.1f}/10")

        # MATERIAL_ISSUE即時差し戻し
        if result.get("material_issue") and allow_fb:
            fbc = state.material_fallback_count.get(pn, 0)
            if fbc < 1:
                state.material_fallback_count[pn] = fbc + 1
                log("MATERIAL_ISSUE — falling back to material phase")
                mp = find_phase_by_name(load_workflow(), "material_review")
                if mp:
                    execute_pdca_loop(mp, registry, state)
                continue

        # cannot_resolve自動アクション
        if result.get("cannot_resolve_actions"):
            handle_cannot_resolve(result["cannot_resolve_actions"], phase, registry, state)

        # 成功判定
        if threshold and consecutive_above_threshold(scores, threshold, required=2):
            log(f"SUCCESS: 2 consecutive scores >= {threshold}")
            break

        # FB差分計算
        fb_log_p = state.fb_log.get(pn, {})
        fb_diff = {}
        if iteration > 1:
            fb_diff = compute_fb_diff(fb_log_p, iteration - 1, iteration)
            if pn not in state.fb_diff_history:
                state.fb_diff_history[pn] = []
            state.fb_diff_history[pn].append(fb_diff)

        # FB差分停滞検出
        if check_fb_stagnation(fb_log_p, window=3):
            if state.is_escalated(pn):
                log("FB stagnation after escalation — stopping")
                break
            state.mark_escalated(pn)
            log("FB stagnation — escalating")
            aborted = handle_escalation(phase, registry, state, scores, iteration, fb_diff=fb_diff)
            if aborted:
                break
            continue

        # スコアベース停滞検出
        if len(scores) >= sw and check_stagnation(scores, sw, st):
            if state.is_escalated(pn):
                log("Re-stagnation after escalation — stopping")
                break
            state.mark_escalated(pn)
            log("Score stagnation — escalating")
            aborted = handle_escalation(phase, registry, state, scores, iteration, fb_diff=fb_diff)
            if aborted:
                break
            continue

    if scores:
        state.log.append(f"[{pn}] Final: {scores[-1]:.1f}/10 ({len(scores)} iters)")


def run_iteration(phase: dict, registry: AgentRegistry, state: RunState, iteration: int) -> dict:
    pn = phase["name"]
    is_material = "material" in pn
    result = {"overall_score": 0.0, "scores_by_axis": {}, "material_issue": False,
              "review_text": "", "cannot_resolve_actions": []}

    if is_material:
        # === 素材PDCA ===
        rp = build_agent_prompt("material_reviewer", registry.get("material_reviewer"), state)
        rp += f"\n\n## イテレーション: {iteration}\n素材を評価して {MATERIAL_REVIEWS_DIR / f'review_{iteration}.md'} に出力してください。\n"
        # 前回FBを注入（iteration > 1 のときのみ）
        if iteration > 1:
            prev_issues = []
            fb_log_p = state.fb_log.get(pn, {})
            for it in fb_log_p.get("iterations", []):
                if it.get("iteration") == iteration - 1:
                    prev_issues = it.get("issues", [])
                    break
            if prev_issues:
                rp += (f"\n\n## 前回（iteration {iteration-1}）のFB — ID再利用の約束\n"
                       f"以下の指摘が前回記録されました。今回のレビューでは:\n"
                       f"- 解消された指摘は **同じID** で `resolved: true` を出力してください\n"
                       f"- 未解消の指摘は **同じID** で `resolved: false` を継続してください\n"
                       f"- 新規指摘は新しいID（例: MAT-{len(prev_issues)+1:03d}）を使ってください\n\n"
                       f"```json\n{json.dumps({'issues': prev_issues}, ensure_ascii=False, indent=2)}\n```\n\n")
        rp += "\nレビューには ```json ``` ブロックでFB構造化データを含めてください。\n"
        ro = call_agent_with_retry("material_reviewer", rp, state=state)
        registry.increment_invocations("material_reviewer")

        review_path = MATERIAL_REVIEWS_DIR / f"review_{iteration}.md"
        if not review_path.exists():
            review_path.write_text(ro, encoding="utf-8")
        review_text = review_path.read_text(encoding="utf-8")
        result["review_text"] = review_text

        try:
            record_fb_log(review_text, pn, iteration, state)
        except FBLogParseError as e:
            log(f"WARNING: FB log parse failed: {e}")
        try:
            result["overall_score"] = extract_overall_score(review_text)
            result["scores_by_axis"] = extract_axis_scores(review_text)
        except ScoreExtractionError:
            log(f"WARNING: Score extraction failed, using 0.0")

        if registry.exists("material_updater"):
            up = build_agent_prompt("material_updater", registry.get("material_updater"), state)
            up += f"\n\n## 今回のレビュー指摘（必ず全て対応すること）\n{review_text[:5000]}\n\n"
            # 前回との差分を注入
            if iteration > 1:
                fb_log_p = state.fb_log.get(pn, {})
                if fb_log_p:
                    fb_diff = compute_fb_diff(fb_log_p, iteration - 1, iteration)
                    up += f"## FB差分（前回→今回の変化）\n"
                    up += f"- 解消された指摘: {fb_diff.get('resolved', [])}\n"
                    up += f"- 未解消の指摘（今回必ず対応）: {fb_diff.get('persisted', [])}\n"
                    up += f"- 新規指摘: {fb_diff.get('new', [])}\n"
                    up += f"- 解消率: {fb_diff.get('resolution_rate', 0):.0%}\n\n"
            up += ("素材を改善してください。\n"
                   "【必須】改善後のdev_simulation_log.md **全文** を出力した後、\n"
                   "対応可否レポートを ```yaml ``` ブロックで出力してください。\n"
                   "【重要】全文は最低5000文字以上。差分サマリや「〜を変更しました」という報告のみの出力は無効となります。\n")
            uo = call_agent_with_retry("material_updater", up, state=state)
            registry.increment_invocations("material_updater")
            # 出力を素材ファイルに保存（サイズチェックで破壊防止）
            sim_log = MATERIALS_DIR / "dev_simulation_log.md"
            if uo and len(uo) > 500:
                yaml_start = uo.find("```yaml")
                main_text = uo[:yaml_start].strip() if yaml_start > 0 else uo
                # 既存ファイルの50%以上のサイズがある場合のみ上書き（差分レポートで破壊されるのを防止）
                if main_text:
                    existing_size = sim_log.stat().st_size if sim_log.exists() else 0
                    new_size = len(main_text.encode("utf-8"))
                    if existing_size == 0 or new_size >= existing_size * 0.5:
                        sim_log.write_text(main_text, encoding="utf-8")
                    else:
                        log(f"WARNING: material_updater output too small ({new_size}B < {existing_size*0.5:.0f}B). Skipping overwrite.")
            try:
                rr = parse_updater_response(uo)
                result["cannot_resolve_actions"] = [r for r in rr if isinstance(r, dict) and r.get("action") == "cannot_resolve"]
            except UpdaterResponseParseError as e:
                log(f"WARNING: Updater response parse failed: {e}")
    else:
        # === 記事PDCA ===
        iter_dir = ITERATIONS_DIR / str(iteration)
        iter_dir.mkdir(parents=True, exist_ok=True)

        if registry.exists("writer"):
            wp = build_agent_prompt("writer", registry.get("writer"), state)

            if iteration == 1:
                # 初回: 新規生成
                wp += f"\n\n## 出力先\n{iter_dir / 'article.md'}\n\n記事を新規に執筆してください。\n"
            else:
                # 2回目以降: 前回記事をベースに修正
                prev_article = ITERATIONS_DIR / str(iteration - 1) / "article.md"
                if prev_article.exists():
                    wp += f"\n\n## 修正対象の前回記事\n\n{prev_article.read_text(encoding='utf-8')}\n\n"

                prev_review = ITERATIONS_DIR / str(iteration - 1) / "review.md"
                if prev_review.exists():
                    wp += f"\n\n## 前回のレビュー指摘（必ず全て対応すること）\n\n{prev_review.read_text(encoding='utf-8')[:5000]}\n\n"

                # FB差分サマリーを注入
                fb_log_p = state.fb_log.get(pn, {})
                if fb_log_p:
                    fb_diff = compute_fb_diff(fb_log_p, iteration - 2, iteration - 1) if iteration > 2 else {}
                    if fb_diff:
                        wp += f"## FB差分（前々回→前回の変化）\n"
                        wp += f"- 解消された指摘: {fb_diff.get('resolved', [])}\n"
                        wp += f"- 未解消の指摘（今回必ず対応）: {fb_diff.get('persisted', [])}\n"
                        wp += f"- 新規指摘: {fb_diff.get('new', [])}\n"
                        wp += f"- 解消率: {fb_diff.get('resolution_rate', 0):.0%}\n\n"

                # punched draftがあればそれも渡す
                prev_punched = ITERATIONS_DIR / str(iteration - 1) / "draft_punched.md"
                if prev_punched.exists():
                    wp += f"\n\n## 前イテレーションの強化済みドラフト（参考）\n{prev_punched.read_text(encoding='utf-8')[:6000]}\n\n"

                # 動的エージェントのアドバイスがあれば渡す
                prev_iter_dir = ITERATIONS_DIR / str(iteration - 1)
                for advice_file in prev_iter_dir.glob("dynamic_advice_*.md"):
                    wp += f"\n\n## 専門エージェントからのアドバイス（{advice_file.stem}）\n{advice_file.read_text(encoding='utf-8')[:3000]}\n\n"

                wp += (f"\n\n## 出力先\n{iter_dir / 'article.md'}\n\n"
                       "【重要】上記の「修正対象の前回記事」をベースに、レビュー指摘された箇所を中心に修正してください。\n"
                       "指摘されていない箇所はそのまま維持してください。全文を最初から書き直さないでください。\n")
            wo = call_agent_with_retry("writer", wp, state=state)
            registry.increment_invocations("writer")
            ap = iter_dir / "article.md"
            if not ap.exists():
                ap.write_text(wo, encoding="utf-8")

        ap = iter_dir / "article.md"
        metrics_ctx = ""
        if ap.exists():
            metrics = compute_metrics(ap.read_text(encoding="utf-8"))
            state.metrics_history[iteration] = metrics
            metrics_ctx = build_metrics_context(metrics)

        if registry.exists("article_reviewer"):
            arp = build_agent_prompt("article_reviewer", registry.get("article_reviewer"), state)
            arp += f"\n\n## 評価対象\n{ap}\n\n"
            if metrics_ctx:
                arp += metrics_ctx
            # 前回FBを注入（iteration > 1 のときのみ）
            if iteration > 1:
                prev_issues = []
                fb_log_p = state.fb_log.get(pn, {})
                for it in fb_log_p.get("iterations", []):
                    if it.get("iteration") == iteration - 1:
                        prev_issues = it.get("issues", [])
                        break
                if prev_issues:
                    arp += (f"\n\n## 前回（iteration {iteration-1}）のFB — ID再利用の約束\n"
                            f"以下の指摘が前回記録されました。今回のレビューでは:\n"
                            f"- 解消された指摘は **同じID** で `resolved: true` を出力してください\n"
                            f"- 未解消の指摘は **同じID** で `resolved: false` を継続してください\n"
                            f"- 新規指摘は新しいID（例: ART-{len(prev_issues)+1:03d}）を使ってください\n\n"
                            f"```json\n{json.dumps({'issues': prev_issues}, ensure_ascii=False, indent=2)}\n```\n\n")
            arp += f"\nレビューを {iter_dir / 'review.md'} に出力してください。\n"
            arp += "\n```json ``` ブロックでFB構造化データを含めてください。\n"
            aro = call_agent_with_retry("article_reviewer", arp, state=state)
            registry.increment_invocations("article_reviewer")
            rvp = iter_dir / "review.md"
            if not rvp.exists():
                rvp.write_text(aro, encoding="utf-8")
            review_text = rvp.read_text(encoding="utf-8")
            result["review_text"] = review_text

            try:
                record_fb_log(review_text, pn, iteration, state)
            except FBLogParseError as e:
                log(f"WARNING: FB log parse failed: {e}")
            try:
                result["overall_score"] = extract_overall_score(review_text)
                result["scores_by_axis"] = extract_axis_scores(review_text)
            except ScoreExtractionError:
                log(f"WARNING: Score extraction failed, using 0.0")
            result["material_issue"] = detect_material_issue(review_text)

            # === HARD FAIL自動判定（メトリクス違反で強制引き下げ）===
            if iteration in state.metrics_history:
                metrics = state.metrics_history[iteration]
                hard_fail_reasons = []
                if metrics.get("code_ratio", 0) > 0.20:
                    hard_fail_reasons.append(f"code_ratio={metrics['code_ratio']:.1%}>20%")
                if metrics.get("desu_masu_ratio", 1) < 0.80:
                    hard_fail_reasons.append(f"desu_masu={metrics['desu_masu_ratio']:.1%}<80%")
                if metrics.get("max_consecutive_same_band", 0) > 4:
                    hard_fail_reasons.append(f"same_band={metrics['max_consecutive_same_band']}>4")
                if hard_fail_reasons:
                    original_score = result["overall_score"]
                    # 違反1件で上限6.0、2件で5.5、3件で5.0
                    capped_score = min(original_score, 6.0 - 0.5 * (len(hard_fail_reasons) - 1))
                    if capped_score < original_score:
                        log(f"HARD FAIL: {hard_fail_reasons}. Score {original_score:.1f} → {capped_score:.1f}")
                        result["overall_score"] = capped_score
                        result["hard_fail_reasons"] = hard_fail_reasons

        # === Narrative Puncher: フック・失敗談が低い場合にセクションを強化 ===
        if registry.exists("narrative_puncher"):
            axis_scores = result.get("scores_by_axis", {})
            # extract_axis_scores は軸名（日本語）をキーにする
            a1 = axis_scores.get("フック力", axis_scores.get("A1", 10.0))
            a2 = axis_scores.get("失敗談のリアルさ", axis_scores.get("A2", 10.0))
            if a1 < 7.5 or a2 < 7.5:
                log(f"Narrative Puncher 起動: A1(フック力)={a1}, A2(失敗談)={a2}")
                npp = build_agent_prompt("narrative_puncher", registry.get("narrative_puncher"), state)
                npp += f"\n\n## 評価対象記事\n{ap}\n\n"
                rvp2 = iter_dir / "review.md"
                if rvp2.exists():
                    npp += f"## 直近のReviewerスコアとコメント\n\n{rvp2.read_text(encoding='utf-8')[:3000]}\n\n"
                for fn in ["sim_log_A.md", "sim_log_B.md", "sim_log_C.md"]:
                    slp = MATERIALS_DIR / fn
                    if slp.exists():
                        npp += f"## {fn}\n\n{slp.read_text(encoding='utf-8')[:2000]}\n\n"
                sp2 = MATERIALS_DIR / "fixed" / "struggles.md"
                if sp2.exists():
                    npp += f"## fixed/struggles.md\n\n{sp2.read_text(encoding='utf-8')[:2000]}\n\n"
                npp += f"\n\n## 出力先\n- {iter_dir / 'draft_punched.md'}\n- {iter_dir / 'punch_report.md'}\n\n書き直してください。\n"
                npo = call_agent_with_retry("narrative_puncher", npp, state=state)
                registry.increment_invocations("narrative_puncher")
                pp = iter_dir / "draft_punched.md"
                if not pp.exists():
                    pp.write_text(npo, encoding="utf-8")
            else:
                log(f"Narrative Puncher スキップ: A1={a1}, A2={a2} (両方 ≥ 7.5)")

        if registry.exists("style_guide_updater"):
            sgup = build_agent_prompt("style_guide_updater", registry.get("style_guide_updater"), state)
            rvp = iter_dir / "review.md"
            ap2 = iter_dir / "article.md"
            sgup += "\n\n## レビュー\n"
            if rvp.exists():
                sgup += rvp.read_text(encoding="utf-8")[:3000]
            sgup += "\n\n## 記事\n"
            if ap2.exists():
                sgup += ap2.read_text(encoding="utf-8")[:3000]
            sgup += ("\n\nstyle_guide.mdにルールを抽出・追記してください。\n"
                     "【重要】出力には更新後のstyle_guide.md全文を含めてください。"
                     "「# Style Guide」ヘッダーから始めてください。\n")
            if check_important_rule_limit():
                sgup += f"\n\n{build_retirement_context(state)}\n"
            sgu_output = call_agent_with_retry("style_guide_updater", sgup, state=state)
            registry.increment_invocations("style_guide_updater")
            _save_agent_output("style_guide_updater", sgu_output)
            if should_run_consolidator():
                log("Running Consolidator...")
                cons_output = call_agent_with_retry("consolidator", build_consolidator_prompt(), state=state)
                _save_agent_output("consolidator", cons_output)

        # === 動的エージェント実行（ADD_AGENTで生成されたエージェント） ===
        dynamic_agents = registry.list_by_phase("dynamic")
        if dynamic_agents:
            for da_name in dynamic_agents:
                log(f"Dynamic agent: {da_name}")
                da_def = registry.get(da_name)
                da_prompt = build_agent_prompt(da_name, da_def, state)
                # 記事とレビューを渡す
                if ap.exists():
                    da_prompt += f"\n\n## 現在の記事\n\n{ap.read_text(encoding='utf-8')[:8000]}\n\n"
                rvp_da = iter_dir / "review.md"
                if rvp_da.exists():
                    da_prompt += f"\n\n## 直近のレビュー\n\n{rvp_da.read_text(encoding='utf-8')[:3000]}\n\n"
                da_prompt += "\n\n## 出力\n記事を改善するためのアドバイスを出力してください。\n"
                da_output = call_agent_with_retry(da_name, da_prompt, state=state)
                registry.increment_invocations(da_name)
                # アドバイスとして保存（記事は上書きしない）
                advice_path = iter_dir / f"dynamic_advice_{da_name}.md"
                advice_path.write_text(da_output, encoding="utf-8")
                log(f"Dynamic agent {da_name} advice saved ({len(da_output)} chars)")

    return result


# ============================================================
# 判定関数 (Phase 7)
# ============================================================

def consecutive_above_threshold(scores: list, threshold: float, required: int = 2) -> bool:
    if len(scores) < required:
        return False
    return all(s > threshold for s in scores[-required:])


def check_stagnation(scores: list, window: int = 3, tolerance: float = 0.5) -> bool:
    if len(scores) < window:
        return False
    recent = scores[-window:]
    return (max(recent) - min(recent)) <= tolerance


def check_fb_stagnation(fb_log: dict, window: int = 3) -> bool:
    iterations = fb_log.get("iterations", [])
    if len(iterations) < window:
        return False
    recent = iterations[-window:]
    sets = []
    for it in recent:
        ids = {i["id"] for i in it.get("issues", [])
               if i.get("severity") == "major" and not i.get("resolved", False)}
        sets.append(ids)
    if not sets:
        return False
    persisted = sets[0]
    for s in sets[1:]:
        persisted = persisted & s
    return len(persisted) > 0


def detect_material_issue(review_text: str) -> bool:
    return bool(re.search(r"^## MATERIAL_ISSUE", review_text, re.MULTILINE))


# ============================================================
# FB構造化ログ・差分メトリクス (Phase 7)
# ============================================================

def record_fb_log(reviewer_output: str, phase_name: str, iteration: int, state: RunState):
    if phase_name not in state.fb_log:
        state.fb_log[phase_name] = {"phase": phase_name, "iterations": []}
    m = re.search(r"```json\s*\n(.*?)\n```", reviewer_output, re.DOTALL)
    if not m:
        raise FBLogParseError(f"No JSON block for {phase_name} iter {iteration}")
    try:
        fb_data = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise FBLogParseError(f"JSON parse failed for {phase_name} iter {iteration}: {e}")
    entry = {"iteration": iteration, "issues": fb_data.get("issues", [])}
    state.fb_log[phase_name]["iterations"].append(entry)


def compute_fb_diff(fb_log: dict, iter_a: int, iter_b: int) -> dict:
    iterations = fb_log.get("iterations", [])
    ea = next((it for it in iterations if it["iteration"] == iter_a), None)
    eb = next((it for it in iterations if it["iteration"] == iter_b), None)
    if not ea or not eb:
        return {"resolved": [], "persisted": [], "new": [], "resolution_rate": 1.0}
    a_unresolved = {i["id"] for i in ea.get("issues", []) if not i.get("resolved", False)}
    b_resolved = {i["id"] for i in eb.get("issues", []) if i.get("resolved", False)}
    b_unresolved = {i["id"] for i in eb.get("issues", []) if not i.get("resolved", False)}
    resolved = list(a_unresolved & b_resolved)
    persisted = list(a_unresolved & b_unresolved)
    new = list(b_unresolved - a_unresolved)
    total = len(resolved) + len(persisted)
    rate = len(resolved) / total if total > 0 else 1.0
    return {"resolved": resolved, "persisted": persisted, "new": new, "resolution_rate": rate}


# ============================================================
# Updater対応可否レポート (Phase 7)
# ============================================================

def parse_updater_response(updater_output: str) -> list:
    m = re.search(r"```yaml\s*\n(.*?)\n```", updater_output, re.DOTALL)
    if not m:
        raise UpdaterResponseParseError("No YAML block found in updater output")
    try:
        parsed = yaml.safe_load(m.group(1)) if yaml else json.loads(m.group(1))
    except Exception as e:
        raise UpdaterResponseParseError(f"Failed to parse updater YAML: {e}")
    return parsed.get("response_report", []) if isinstance(parsed, dict) else []


def handle_cannot_resolve(actions: list, phase: dict, registry: AgentRegistry, state: RunState):
    pn = phase["name"]
    for action in actions:
        reason = action.get("reason", "")
        if reason == "material_shortage":
            fbc = state.material_fallback_count.get(pn, 0)
            if fbc < 1:
                state.material_fallback_count[pn] = fbc + 1
                mp = find_phase_by_name(load_workflow(), "material_review")
                if mp:
                    execute_pdca_loop(mp, registry, state)
            else:
                if not state.is_escalated(pn):
                    state.mark_escalated(pn)
                    handle_escalation(phase, registry, state, state.get_scores(pn), -1)
        elif reason == "eval_mismatch":
            fm = filter_agent_memory(state.article_type, limit=5)
            call_agent_with_retry("eval_designer", build_eval_adjustment_prompt(
                PROJECT_ROOT / "eval_criteria.md", state.get_scores(pn), fm), state=state)
        elif reason == "strategy_level":
            if not state.is_escalated(pn):
                state.mark_escalated(pn)
                handle_escalation(phase, registry, state, state.get_scores(pn), -1)
            else:
                state.log.append(f"[{pn}] strategy_level but escalation used — continuing")


# ============================================================
# エスカレーション (Phase 7)
# ============================================================

def handle_escalation(phase: dict, registry: AgentRegistry, state: RunState,
                      scores: list, iteration: int, fb_diff: dict = None) -> bool:
    """Returns True if ABORT was selected."""
    pn = phase["name"]
    output = call_strategist_escalation(pn, state, scores, iteration, fb_diff)
    action = extract_escalation_action(output)
    log(f"Escalation action: {action}")
    execute_escalation_action(action, phase, registry, state)
    return action == "ABORT"


def extract_escalation_action(output: str) -> str:
    m = re.search(r"ACTION:\s*(\w+)", output)
    if not m:
        raise EscalationParseError("ACTION not found in strategist output")
    return m.group(1)


def execute_escalation_action(action: str, phase: dict, registry: AgentRegistry, state: RunState):
    pn = phase["name"]
    state.log.append(f"[{pn}] Executing escalation: {action}")
    if action == "RESIMULATE":
        if registry.exists("dev_simulator"):
            p = build_agent_prompt("dev_simulator", registry.get("dev_simulator"), state)
            call_agent_with_retry("dev_simulator", p, state=state)
            registry.increment_invocations("dev_simulator")
    elif action == "RESEARCH":
        if registry.exists("trend_searcher"):
            p = build_agent_prompt("trend_searcher", registry.get("trend_searcher"), state)
            call_agent_with_retry("trend_searcher", p, state=state)
            registry.increment_invocations("trend_searcher")
    elif action == "ADJUST_EVAL":
        fm = filter_agent_memory(state.article_type, limit=5)
        call_agent_with_retry("eval_designer", build_eval_adjustment_prompt(
            PROJECT_ROOT / "eval_criteria.md", state.get_scores(pn), fm), state=state)
    elif action == "MATERIAL_FALLBACK":
        mp = find_phase_by_name(load_workflow(), "material_review")
        if mp:
            execute_pdca_loop(mp, registry, state)
    elif action == "ADD_AGENT":
        sa = identify_stagnant_axes(state, pn)
        call_agent_with_retry("agent_editor", build_add_agent_prompt(PROJECT_ROOT / "strategy.md", sa), state=state)
        discover_new_agents(registry)
    elif action == "CONSOLIDATE":
        cons_out = call_agent_with_retry("consolidator", build_consolidator_prompt(), state=state)
        _save_agent_output("consolidator", cons_out)
    elif action == "ABORT":
        state.log.append(f"[{pn}] ABORT")
    else:
        log(f"WARNING: Unknown escalation action: {action}")


def identify_stagnant_axes(state: RunState, phase_name: str) -> list:
    scores = state.get_scores(phase_name)
    return [f"Score trend: {scores[-3:]}"] if scores else []


def discover_new_agents(registry: AgentRegistry):
    for f in AGENTS_GENERATED_DIR.glob("*.md"):
        an = f.stem
        if not registry.exists(an):
            registry.register(an, str(f), extract_agent_type(f), "dynamic")
            log(f"Discovered new agent: {an}")


# ============================================================
# エージェント検証 (Phase 8)
# ============================================================

def validate_agents() -> list:
    errors = []
    for af in AGENTS_GENERATED_DIR.glob("*.md"):
        if af.name == "workflow.json":
            continue
        text = af.read_text(encoding="utf-8")
        # V3: フルスクラッチの構造チェック
        if "base_template: null" in text or "type: generated" in text:
            for sec in ["## 役割", "## 入力", "## 出力", "## 指示"]:
                if sec not in text:
                    errors.append(f"V3: {af.name}: missing section '{sec}'")
    # W1-W4
    wf_path = AGENTS_GENERATED_DIR / "workflow.json"
    if wf_path.exists():
        try:
            wf = json.loads(wf_path.read_text(encoding="utf-8"))
            validate_workflow_schema(wf)
        except WorkflowValidationError as e:
            errors.extend(str(e).split("\n"))
        except json.JSONDecodeError as e:
            errors.append(f"workflow.json: invalid JSON: {e}")
    else:
        errors.append("workflow.json not found")
    return errors


def validate_and_fix_agents(state: RunState):
    for attempt in range(MAX_AGENT_EDITOR_RETRIES + 1):
        errors = validate_agents()
        if not errors:
            log("Agent validation passed")
            return
        log(f"Agent validation failed (attempt {attempt + 1}): {len(errors)} errors")
        if attempt >= MAX_AGENT_EDITOR_RETRIES:
            raise AgentValidationError(f"Validation failed after {MAX_AGENT_EDITOR_RETRIES + 1} attempts:\n" + "\n".join(errors))
        call_agent_with_retry("agent_editor",
                              f"以下の検証エラーを修正してください。\n\n## エラー\n" + "\n".join(errors) +
                              "\n\nagents/generated/ のファイルとworkflow.jsonを修正してください。\n",
                              state=state)


# ============================================================
# ソースファイル前処理 (Phase 9)
# ============================================================

def validate_source_files(source_dir: str) -> Path:
    sp = Path(source_dir) if Path(source_dir).is_absolute() else PROJECT_ROOT / source_dir
    if not sp.exists():
        raise FileNotFoundError(f"Source not found: {sp}")
    if sp.is_dir() and not list(sp.iterdir()):
        raise ValueError(f"Source directory is empty: {sp}")
    return sp


# ============================================================
# 実行履歴保存 (Phase 9)
# ============================================================

def select_final_article(state: RunState) -> Optional[Path]:
    for pn in ["article_review", "article"]:
        scores = state.get_scores(pn)
        if scores:
            best = scores.index(max(scores)) + 1
            ap = ITERATIONS_DIR / str(best) / "article.md"
            if ap.exists():
                return ap
    # Fallback
    for d in sorted(ITERATIONS_DIR.iterdir(), reverse=True):
        ap = d / "article.md"
        if ap.exists():
            return ap
    return None


def save_run(run_id: str, state: RunState):
    rd = RUNS_DIR / run_id
    rd.mkdir(parents=True, exist_ok=True)
    for f in ["strategy.md", "eval_criteria.md"]:
        s = PROJECT_ROOT / f
        if s.exists():
            shutil.copy(s, rd / f)
    wf = AGENTS_GENERATED_DIR / "workflow.json"
    if wf.exists():
        shutil.copy(wf, rd / "workflow.json")
    ag_dst = rd / "agents_generated"
    if AGENTS_GENERATED_DIR.exists():
        if ag_dst.exists():
            shutil.rmtree(ag_dst)
        shutil.copytree(AGENTS_GENERATED_DIR, ag_dst)
    final = select_final_article(state)
    if final:
        shutil.copy(final, rd / "final_article.md")
    with open(rd / "fb_log.json", "w", encoding="utf-8") as f:
        json.dump(state.fb_log, f, ensure_ascii=False, indent=2)
    save_scores(run_id, state)
    save_summary(run_id, state)


# ============================================================
# エラーハンドリング (Phase 10)
# ============================================================

def save_error_log(run_id: str, error: Exception):
    rd = RUNS_DIR / run_id
    rd.mkdir(parents=True, exist_ok=True)
    with open(rd / "error.log", "w", encoding="utf-8") as f:
        f.write(f"Error: {error}\n\n{traceback.format_exc()}")


def save_partial_run(run_id: str, state: RunState, error: Exception = None):
    rd = RUNS_DIR / run_id
    rd.mkdir(parents=True, exist_ok=True)
    for f in ["strategy.md", "eval_criteria.md"]:
        s = PROJECT_ROOT / f
        if s.exists():
            shutil.copy(s, rd / f)
    wf = AGENTS_GENERATED_DIR / "workflow.json"
    if wf.exists():
        shutil.copy(wf, rd / "workflow.json")
    with open(rd / "fb_log.json", "w", encoding="utf-8") as f:
        json.dump(state.fb_log, f, ensure_ascii=False, indent=2)
    save_scores(run_id, state)
    save_summary(run_id, state, partial=True, error=str(error) if error else None)
    if error:
        save_error_log(run_id, error)


# ============================================================
# メインフロー (Phase 9)
# ============================================================

def cmd_run(source_dir: str, user_instruction: str, model: str = "sonnet") -> str:
    run_id = generate_run_id()
    log(f"=== RUN {run_id} ===")
    init_project()
    clean_runtime_dirs()
    state = RunState(run_id=run_id, source_dir=source_dir, user_instruction=user_instruction)
    knowledge_store.cleanup_expired_cache()
    knowledge_store.archive_old_entries()

    try:
        # 層1: MetaAgent
        log("=== Layer 1: MetaAgent ===")
        call_strategist_plan(source_dir, user_instruction, state)
        filtered_memory = filter_agent_memory(state.article_type, limit=5)
        call_agent_editor(filtered_memory, state)
        validate_and_fix_agents(state)
        call_eval_designer(filtered_memory, state)

        # レジストリ構築
        log("=== Building Registry ===")
        workflow = load_workflow()
        validate_workflow_schema(workflow)
        registry = build_registry(workflow)
        log(registry.summary())

        # 層2: ワークフロー実行
        log("=== Layer 2: Workflow Execution ===")
        for phase in workflow["phases"]:
            dispatch_phase(phase, registry, state)

        # 振り返り
        log("=== Retrospective ===")
        call_strategist_retrospective(state)
        write_agent_memory(run_id, state, registry)

        # 実行履歴保存
        log("=== Saving Run ===")
        save_run(run_id, state)

        log("=" * 60)
        log(f"COMPLETE! run_id={run_id}")
        final = select_final_article(state)
        if final:
            log(f"Final article: {final}")
        log(f"Scores: {state.scores}")
        tu = state.token_usage
        log(f"Tokens: {tu['total_input_tokens']} in / {tu['total_output_tokens']} out / ${tu['total_cost_usd']:.4f}")
        agent_costs = {k: f"${v['cost']:.4f} ({v['calls']} calls)" for k, v in tu['by_agent'].items()}
        log(f"Agent costs: {agent_costs}")
        log("=" * 60)
        return run_id

    except KeyboardInterrupt:
        log("Interrupted — saving partial run")
        save_partial_run(run_id, state)
        sys.exit(1)
    except Exception as e:
        log(f"ERROR: {e}")
        save_partial_run(run_id, state, error=e)
        raise


def cmd_feedback(run_id: str, feedback_text: str):
    mp = AGENT_MEMORY_DIR / f"run_{run_id}.yaml"
    if not mp.exists():
        log(f"ERROR: Agent memory not found for run {run_id}")
        return
    ec_path = RUNS_DIR / run_id / "eval_criteria.md"
    ec = ec_path.read_text(encoding="utf-8") if ec_path.exists() else ""
    fb_log_path = RUNS_DIR / run_id / "fb_log.json"
    fb_text = fb_log_path.read_text(encoding="utf-8") if fb_log_path.exists() else ""
    mem = _load_yaml(mp)

    prompt = (f"あなたはStrategist（フィードバックモード）です。\n\n{read_agent_definition('strategist')}\n\n"
              f"## ユーザーフィードバック\n{feedback_text}\n\n"
              f"## 対象実行のメタデータ\n{json.dumps(mem, ensure_ascii=False, default=str)[:3000]}\n\n"
              f"## 評価基準\n{ec[:3000]}\n\n## FB構造化ログ\n{fb_text[:3000]}\n\n"
              f"## 出力\nhuman_feedbackのYAMLを出力してください。\n")
    output = call_agent_with_retry("strategist", prompt)
    fd = {"raw": feedback_text}
    try:
        ym = re.search(r"```yaml\s*\n(.*?)\n```", output, re.DOTALL)
        if ym and yaml:
            parsed = yaml.safe_load(ym.group(1))
            if isinstance(parsed, dict):
                fd = parsed.get("human_feedback", parsed)
    except Exception:
        pass
    update_human_feedback(run_id, fd)
    log(f"Feedback recorded for run {run_id}")


def cmd_history(limit: int = 10, detail: bool = False):
    if not RUNS_DIR.exists():
        log("No runs found")
        return
    for rd in sorted(RUNS_DIR.iterdir(), reverse=True)[:limit]:
        if not rd.is_dir():
            continue
        sp = rd / "summary.json"
        if sp.exists():
            with open(sp) as f:
                s = json.load(f)
            partial = " (PARTIAL)" if s.get("partial") else ""
            print(f"  {rd.name}{partial}: {s.get('article_type', '?')} — {s.get('user_instruction', '')[:50]}")
            if detail:
                print(f"    Scores: {s.get('scores', {})}")
        else:
            print(f"  {rd.name}: (no summary)")


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Zenn Article Generator v4.0")
    subparsers = parser.add_subparsers(dest="command")

    rp = subparsers.add_parser("run", help="記事を自動生成する")
    rp.add_argument("--source", required=True, help="ソースディレクトリまたはファイル")
    rp.add_argument("--instruction", required=True, help="記事の方向性指定")
    rp.add_argument("--model", default="sonnet", help="LLMモデル")

    fp = subparsers.add_parser("feedback", help="フィードバックを送信する")
    fp.add_argument("run_id", help="対象実行のID")
    fp.add_argument("feedback_text", help="フィードバックテキスト")

    hp = subparsers.add_parser("history", help="実行履歴を表示する")
    hp.add_argument("--limit", type=int, default=10, help="表示件数")
    hp.add_argument("--detail", action="store_true", help="詳細表示")

    args = parser.parse_args()
    if args.command == "run":
        src = validate_source_files(args.source)
        cmd_run(str(src), args.instruction, args.model)
    elif args.command == "feedback":
        cmd_feedback(args.run_id, args.feedback_text)
    elif args.command == "history":
        cmd_history(args.limit, args.detail)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
