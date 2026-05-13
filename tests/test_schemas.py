from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from silent_compound_failures.schemas import (
    AuditResult,
    ExpectedDecompositionStep,
    RunResult,
    Task,
    TaskAggregate,
    TaskSuite,
    TraceData,
)

REPO_ROOT = Path(__file__).parent.parent
TASKS_YAML = REPO_ROOT / "tasks_example.yaml"


def test_task_minimal_valid():
    t = Task(id="X", description="Y")
    assert t.id == "X"
    assert t.description == "Y"
    assert t.expected_decomposition == []
    assert t.success_check_regex is None


def test_task_accepts_unknown_intent_for_forward_compat():
    step = ExpectedDecompositionStep(prompt="X", intent="bogus")
    assert step.intent == "bogus"


def test_task_suite_loads_yaml_with_4_tasks():
    suite = TaskSuite(**yaml.safe_load(TASKS_YAML.read_text()))
    assert len(suite.tasks) == 4
    ids = [t.id for t in suite.tasks]
    assert ids == ["H-001", "H-002", "H-003", "H-004"]


def test_task_suite_rejects_malformed_yaml():
    with pytest.raises(ValidationError):
        TaskSuite(**{"tasks": [{"id": "X"}]})  # missing description


def test_run_result_json_roundtrip():
    r = RunResult(
        task_id="H-001",
        rep=0,
        latency_s=1.23,
        score=1.0,
        content_chars=42,
        trace_n_subtasks=3,
        trace_subtask_intents=["code", "verification"],
        trace_backends=["x"],
        real_decomposition=True,
        http_status=200,
    )
    s = r.model_dump_json()
    r2 = RunResult.model_validate_json(s)
    assert r == r2


def test_run_result_trace_helper_returns_nested_view():
    r = RunResult(
        task_id="H-001",
        rep=0,
        latency_s=1.0,
        score=0.0,
        content_chars=0,
        trace_n_subtasks=2,
        trace_subtask_intents=["code"],
        trace_backends=[],
        real_decomposition=True,
        http_status=200,
    )
    trace = r.trace()
    assert isinstance(trace, TraceData)
    assert trace.n_subtasks == 2
    assert trace.subtask_intents == ["code"]


def test_audit_result_handles_missing_optional_fields():
    a = AuditResult(test="qwen_decomp", rep=0, latency_s=1.0, task_id="H-001")
    assert a.test == "qwen_decomp"
    assert a.completion_tokens is None
    assert a.finish_reason is None


def test_audit_result_preserves_extra_fields():
    a = AuditResult(
        test="rlm_trace_h001",
        rep=0,
        latency_s=1.0,
        trace_n_subtasks=3,
        trace_subtask_intents=["code"],
        trace_backends=["x"],
        h001_score_match=True,
    )
    d = a.model_dump()
    # extras flow through
    assert d["trace_n_subtasks"] == 3
    assert d["h001_score_match"] is True


def test_task_aggregate_basic():
    agg = TaskAggregate(n_real_decomp=3, n_correct=2, mean_latency_s=10.0, stddev_latency_s=1.0)
    assert agg.n_correct == 2
