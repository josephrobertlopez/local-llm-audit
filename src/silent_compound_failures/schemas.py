"""Pydantic models for tasks, results, traces.

Design notes:
- TaskSuite is the input contract — validates tasks YAML on load.
- RunResult mirrors rerun_arm.py's on-disk JSON shape (FLAT trace_* fields).
  The on-disk evidence/*.json contracts predate this work; we keep the
  flat shape so existing analysis tooling still parses cleanly.
- AuditResult is a permissive container for the audit-battery raw dicts,
  which are polymorphic by `test` field (qwen_decomp / qwq_1500_repro /
  rlm_trace_h001 all use different field sets).
- TraceData is defined for downstream consumers that want a nested view;
  RunResult exposes a `.trace()` helper to materialize one.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ExpectedDecompositionStep(BaseModel):
    prompt: str
    intent: str = Field(
        description="convention: one of [code, reasoning_hard, reasoning_fast, verification, synthesis] — accepted as free string for forward-compat",
    )
    recurse: bool = False


class Task(BaseModel):
    id: str
    name: Optional[str] = None
    description: str
    expected_decomposition: list[ExpectedDecompositionStep] = Field(default_factory=list)
    success_check_regex: Optional[str] = None


class TaskSuite(BaseModel):
    tasks: list[Task]


class TraceData(BaseModel):
    n_subtasks: int = 0
    subtask_intents: list[str] = Field(default_factory=list)
    backends: list[str] = Field(default_factory=list)


class RunResult(BaseModel):
    """Per-task per-rep result from rerun_arm. FLAT shape to match on-disk JSON."""

    task_id: str
    rep: int
    latency_s: float
    score: float
    content_chars: int
    trace_n_subtasks: int = 0
    trace_subtask_intents: list[str] = Field(default_factory=list)
    trace_backends: list[str] = Field(default_factory=list)
    real_decomposition: bool
    http_status: int

    def trace(self) -> TraceData:
        return TraceData(
            n_subtasks=self.trace_n_subtasks,
            subtask_intents=list(self.trace_subtask_intents),
            backends=list(self.trace_backends),
        )


class TaskAggregate(BaseModel):
    n_real_decomp: int
    n_correct: int
    mean_latency_s: float
    stddev_latency_s: float


class AuditResult(BaseModel):
    """Audit-battery raw result. Polymorphic by `test`; extra fields allowed."""

    model_config = ConfigDict(extra="allow")

    test: str
    rep: int
    latency_s: float
    task_id: Optional[str] = None
    content_chars: Optional[int] = None
    parse_success: Optional[bool] = None
    parsed_n_subtasks: Optional[int] = None
    parsed_intents: Optional[list[str]] = None
    completion_tokens: Optional[int] = None
    finish_reason: Optional[str] = None
    # rlm_trace_h001 fields (declared so mypy accepts kwargs; extras still allowed)
    trace_n_subtasks: Optional[int] = None
    trace_subtask_intents: Optional[list[str]] = None
    trace_backends: Optional[list[str]] = None
    h001_score_match: Optional[bool] = None
