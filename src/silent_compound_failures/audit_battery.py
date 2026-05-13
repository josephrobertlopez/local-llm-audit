"""AuditBattery — the 4-test audit harness as a class.

External users:

    from silent_compound_failures.audit_battery import AuditBattery
    verdict = AuditBattery(
        target_endpoint="http://localhost:11434",
        target_token="...",
        tasks_path="tasks_example.yaml",
        reps=3,
    ).run()

CLI behavior preserved by the root `audit_battery.py` script.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Optional

import yaml
from statistics import mean as _mean

from .llm_adapter import LLMAdapter, OpenAICompatAdapter, RLMHubAdapter
from .schemas import AuditResult, TaskSuite

DECOMPOSE_SYSTEM = (
    "You decompose a complex task into 2-4 simpler subtasks, each tagged with an intent "
    "category. Allowed intents: code, reasoning_hard, reasoning_fast, verification, synthesis. "
    "Output a YAML list with fields prompt (the subtask text) and intent (the category). "
    "Do not execute the subtasks; only decompose."
)

DECOMPOSE_TEMPLATE = """TASK TO DECOMPOSE:
{task}

Decompose this into 2-4 simpler subtasks. Output a YAML list. Each item must have:
  - `prompt`: the subtask text the specialist will execute
  - `intent`: one of [code, reasoning_hard, reasoning_fast, verification, synthesis]
  - `recurse` (optional, default false)

Do NOT solve the subtasks. Output ONLY the YAML list, no preamble.

Example:
- prompt: Write a Python function add(a, b)
  intent: code
- prompt: Explain commutativity
  intent: reasoning_fast
"""

DEFAULT_TARGET_TASK_IDS = ("H-001", "H-002", "H-003")
TEST1_MODEL = "qwen2.5-32b-instruct-awq"
TEST1_MAX_TOKENS = 2000
TEST1_TIMEOUT = 120
TEST2_MODEL = "qwq-32b-awq"
TEST2_MAX_TOKENS = 1500
TEST2_TIMEOUT = 300
TEST3_TIMEOUT = 900


def parse_decomposition(content):
    try:
        match = re.search(r'(?m)^-\s+prompt:', content)
        if not match:
            return None, 0, []
        yaml_str = content[match.start():]
        parsed = yaml.safe_load(yaml_str)
        if not isinstance(parsed, list):
            return parsed, len(parsed) if parsed else 0, []
        intents = [item.get('intent', 'unknown') for item in parsed if isinstance(item, dict)]
        return parsed, len(parsed), intents
    except Exception:
        return None, 0, []


@dataclass
class VerdictBreakdown:
    test1_fix_reliability: Literal["pass", "fail"]
    test2_historical_bug_proof: Literal["confirmed", "no-evidence"]
    test3_trace_verification: Literal["pass", "fail"]
    test4_statistical_significance: Literal["significant", "underpowered", "null"]


@dataclass
class AuditVerdict:
    overall: Literal["healthy", "bug-confirmed", "needs-more-data"]
    breakdown: VerdictBreakdown
    n_per_task: dict[str, int]
    fisher_p: Optional[float]
    raw_results: list[AuditResult]
    notes: list[str] = field(default_factory=list)


def _classify(breakdown: VerdictBreakdown) -> Literal["healthy", "bug-confirmed", "needs-more-data"]:
    if breakdown.test2_historical_bug_proof == "confirmed":
        return "bug-confirmed"
    if breakdown.test4_statistical_significance == "underpowered":
        return "needs-more-data"
    if (
        breakdown.test1_fix_reliability == "pass"
        and breakdown.test3_trace_verification == "pass"
        and breakdown.test2_historical_bug_proof == "no-evidence"
    ):
        return "healthy"
    return "needs-more-data"


class AuditBattery:
    """4-test audit battery. Pluggable adapter; run() returns AuditVerdict."""

    def __init__(
        self,
        target_endpoint: str,
        target_token: str,
        tasks_path: str,
        reps: int = 3,
        adapter: Optional[LLMAdapter] = None,
        rlm_adapter: Optional[LLMAdapter] = None,
        target_task_ids: tuple[str, ...] = DEFAULT_TARGET_TASK_IDS,
    ):
        self.target_endpoint = target_endpoint
        self.target_token = target_token
        self.tasks_path = tasks_path
        self.reps = reps
        self.adapter: LLMAdapter = adapter or OpenAICompatAdapter(base_url=target_endpoint, token=target_token)
        self.rlm_adapter: LLMAdapter = rlm_adapter or RLMHubAdapter(base_url=target_endpoint, token=target_token)
        self.target_task_ids = target_task_ids

    def _load_tasks(self) -> list[dict]:
        with open(self.tasks_path) as f:
            raw = yaml.safe_load(f)
        if isinstance(raw, list):
            raw = {"tasks": raw}
        suite = TaskSuite(**raw)
        keep = set(self.target_task_ids)
        return [t.model_dump() for t in suite.tasks if t.id in keep]

    def _decompose_messages(self, description: str) -> list[dict]:
        return [
            {"role": "system", "content": DECOMPOSE_SYSTEM},
            {"role": "user", "content": DECOMPOSE_TEMPLATE.format(task=description)},
        ]

    def _test1_fix_reliability(self, tasks: list[dict]) -> list[AuditResult]:
        out: list[AuditResult] = []
        for task in tasks:
            for rep in range(self.reps):
                r = self.adapter.chat(
                    TEST1_MODEL,
                    self._decompose_messages(task["description"]),
                    TEST1_MAX_TOKENS,
                    TEST1_TIMEOUT,
                )
                content = r.content
                if content:
                    parsed, n_subtasks, intents = parse_decomposition(content)
                    parse_success = parsed is not None
                else:
                    n_subtasks, intents, parse_success = 0, [], False
                out.append(
                    AuditResult(
                        test="qwen_decomp",
                        task_id=task["id"],
                        rep=rep,
                        latency_s=r.latency_s,
                        content_chars=len(content) if content else 0,
                        parsed_n_subtasks=n_subtasks,
                        parsed_intents=intents,
                        parse_success=parse_success,
                    )
                )
        return out

    def _test2_historical_bug_proof(self, tasks: list[dict]) -> list[AuditResult]:
        out: list[AuditResult] = []
        for task in tasks:
            for rep in range(self.reps):
                r = self.adapter.chat(
                    TEST2_MODEL,
                    self._decompose_messages(task["description"]),
                    TEST2_MAX_TOKENS,
                    TEST2_TIMEOUT,
                )
                content = r.content
                if content:
                    parsed, n_subtasks, intents = parse_decomposition(content)
                    parse_success = parsed is not None
                else:
                    n_subtasks, intents, parse_success = 0, [], False
                out.append(
                    AuditResult(
                        test="qwq_1500_repro",
                        task_id=task["id"],
                        rep=rep,
                        latency_s=r.latency_s,
                        content_chars=len(content) if content else 0,
                        parsed_n_subtasks=n_subtasks,
                        parse_success=parse_success,
                        completion_tokens=r.completion_tokens or 0,
                        finish_reason=r.finish_reason,
                    )
                )
        return out

    def _test3_trace_verification(self, tasks: list[dict]) -> list[AuditResult]:
        h001 = next((t for t in tasks if t["id"] == "H-001"), None)
        out: list[AuditResult] = []
        if not h001:
            return out
        for rep in range(self.reps):
            content, latency, trace = self.rlm_adapter.rlm_decompose(h001["description"], TEST3_TIMEOUT)
            trace = trace or {}
            n_subtasks = trace.get("n_subtasks", 0)
            intents = trace.get("subtask_intents", trace.get("intents", []))
            backends = trace.get("backends", [])
            success_regex = h001.get("success_check_regex", "")
            score_match = bool(success_regex and content and re.search(success_regex, content))
            out.append(
                AuditResult(
                    test="rlm_trace_h001",
                    rep=rep,
                    latency_s=latency,
                    content_chars=len(content) if content else 0,
                    trace_n_subtasks=n_subtasks,
                    trace_subtask_intents=intents,
                    trace_backends=backends,
                    h001_score_match=score_match,
                )
            )
        return out

    def _test4_statistical(self, results: list[AuditResult]) -> tuple[Optional[float], VerdictBreakdown]:
        test1 = [r for r in results if r.test == "qwen_decomp"]
        test2 = [r for r in results if r.test == "qwq_1500_repro"]
        test3 = [r for r in results if r.test == "rlm_trace_h001"]

        t1_pass = test1 and all(r.parse_success for r in test1)
        test1_breakdown: Literal["pass", "fail"] = "pass" if t1_pass else "fail"

        t1_success = sum(1 for r in test1 if r.parse_success)
        t2_success = sum(1 for r in test2 if r.parse_success)
        t1_n = len(test1) or 1
        t2_n = len(test2) or 1
        t1_rate = t1_success / t1_n
        t2_rate = t2_success / t2_n
        bug_confirmed = (t2_n >= 6) and (t1_rate - t2_rate >= 0.3)
        test2_breakdown: Literal["confirmed", "no-evidence"] = "confirmed" if bug_confirmed else "no-evidence"

        t3_n_subtasks = [getattr(r, "trace_n_subtasks", 0) or r.model_dump().get("trace_n_subtasks", 0) for r in test3]
        t3_pass = bool(t3_n_subtasks) and max(t3_n_subtasks) > 1
        test3_breakdown: Literal["pass", "fail"] = "pass" if t3_pass else "fail"

        # Statistical significance heuristic (real Fisher's exact wired in wave-5 stats module)
        total_n = t1_n + t2_n
        if total_n < 12:
            test4_breakdown: Literal["significant", "underpowered", "null"] = "underpowered"
        elif abs(t1_rate - t2_rate) >= 0.4:
            test4_breakdown = "significant"
        else:
            test4_breakdown = "null"

        breakdown = VerdictBreakdown(
            test1_fix_reliability=test1_breakdown,
            test2_historical_bug_proof=test2_breakdown,
            test3_trace_verification=test3_breakdown,
            test4_statistical_significance=test4_breakdown,
        )
        return None, breakdown  # fisher_p computed in wave-5 stats module

    def _per_task_counts(self, results: list[AuditResult]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in results:
            tid = r.task_id
            if not tid:
                continue
            counts[tid] = counts.get(tid, 0) + 1
        return counts

    def run(self) -> AuditVerdict:
        tasks = self._load_tasks()
        results: list[AuditResult] = []
        results.extend(self._test1_fix_reliability(tasks))
        results.extend(self._test2_historical_bug_proof(tasks))
        results.extend(self._test3_trace_verification(tasks))
        fisher_p, breakdown = self._test4_statistical(results)
        return AuditVerdict(
            overall=_classify(breakdown),
            breakdown=breakdown,
            n_per_task=self._per_task_counts(results),
            fisher_p=fisher_p,
            raw_results=results,
            notes=[],
        )
