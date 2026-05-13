from pathlib import Path
from typing import Optional

from silent_compound_failures.audit_battery import (
    AuditBattery,
    AuditVerdict,
    VerdictBreakdown,
    _classify,
)
from silent_compound_failures.llm_adapter import LLMResult

REPO_ROOT = Path(__file__).parent.parent
TASKS_YAML = REPO_ROOT / "tasks_example.yaml"


# ----- Mock adapters -----

class _ChatScript:
    """Returns canned LLMResults in order. Recycles if exhausted."""

    def __init__(self, results: list[LLMResult]):
        self.results = results
        self.i = 0
        self.calls: list[tuple] = []

    def __call__(self, model, messages, max_tokens, timeout) -> LLMResult:
        self.calls.append((model, len(messages), max_tokens, timeout))
        r = self.results[self.i % len(self.results)]
        self.i += 1
        return r


class _RLMScript:
    def __init__(self, results: list[tuple[Optional[str], float, Optional[dict]]]):
        self.results = results
        self.i = 0

    def __call__(self, prompt, timeout):
        r = self.results[self.i % len(self.results)]
        self.i += 1
        return r


class _MockAdapter:
    def __init__(self, chat_script: _ChatScript, rlm_script: _RLMScript):
        self._chat = chat_script
        self._rlm = rlm_script

    def chat(self, model, messages, max_tokens, timeout):
        return self._chat(model, messages, max_tokens, timeout)

    def rlm_decompose(self, prompt, timeout):
        return self._rlm(prompt, timeout)


GOOD_YAML = (
    "- prompt: Write a python function\n  intent: code\n"
    "- prompt: Verify the result\n  intent: verification\n"
)


def _ok(content=GOOD_YAML, tokens=20, finish="stop"):
    return LLMResult(content=content, latency_s=0.1, completion_tokens=tokens, finish_reason=finish, http_status=200, error=None)


def _empty():
    return LLMResult(content="", latency_s=0.1, completion_tokens=0, finish_reason="length", http_status=200, error=None)


def _trace_ok():
    return (GOOD_YAML, 0.1, {"n_subtasks": 3, "subtask_intents": ["code", "verification", "synthesis"], "backends": ["x"]})


# ----- Tests -----

def test_audit_battery_construct():
    b = AuditBattery(target_endpoint="x", target_token="y", tasks_path=str(TASKS_YAML))
    assert b.reps == 3
    assert b.target_endpoint == "x"


def test_audit_battery_run_with_mocked_adapter():
    chat = _ChatScript([_ok()] * 18)  # 9 for test1, 9 for test2
    rlm = _RLMScript([_trace_ok()] * 3)
    adapter = _MockAdapter(chat, rlm)
    b = AuditBattery(
        target_endpoint="x",
        target_token="y",
        tasks_path=str(TASKS_YAML),
        reps=3,
        adapter=adapter,
        rlm_adapter=adapter,
    )
    verdict = b.run()
    assert isinstance(verdict, AuditVerdict)
    assert verdict.breakdown is not None
    # 3 tasks × 3 reps × 2 tests (test1 + test2) + 3 test3 reps = 21
    assert len(verdict.raw_results) == 21


def test_audit_verdict_overall_healthy():
    chat = _ChatScript([_ok()] * 18)
    rlm = _RLMScript([_trace_ok()] * 3)
    adapter = _MockAdapter(chat, rlm)
    b = AuditBattery(target_endpoint="x", target_token="y", tasks_path=str(TASKS_YAML), reps=3, adapter=adapter, rlm_adapter=adapter)
    verdict = b.run()
    # All tests pass + test2 has same rate as test1 → no-evidence; total_n=18 ≥ 12 and rates equal → null
    # That gives: t1 pass, t2 no-evidence, t3 pass, t4 null  → healthy via _classify
    assert verdict.breakdown.test1_fix_reliability == "pass"
    assert verdict.breakdown.test3_trace_verification == "pass"
    assert verdict.breakdown.test2_historical_bug_proof == "no-evidence"
    assert verdict.overall == "healthy"


def test_audit_verdict_bug_confirmed():
    # test 1: all pass. test 2: all fail (empty content → parse_success=False)
    chat = _ChatScript([_ok()] * 9 + [_empty()] * 9)
    rlm = _RLMScript([_trace_ok()] * 3)
    adapter = _MockAdapter(chat, rlm)
    b = AuditBattery(target_endpoint="x", target_token="y", tasks_path=str(TASKS_YAML), reps=3, adapter=adapter, rlm_adapter=adapter)
    verdict = b.run()
    assert verdict.breakdown.test1_fix_reliability == "pass"
    assert verdict.breakdown.test2_historical_bug_proof == "confirmed"
    assert verdict.overall == "bug-confirmed"


def test_audit_verdict_needs_more_data_when_underpowered():
    # reps=1 → 3 tasks × 1 × 2 + 1 = 7 results, t1+t2=6 < 12 → underpowered
    chat = _ChatScript([_ok()] * 6)
    rlm = _RLMScript([_trace_ok()] * 1)
    adapter = _MockAdapter(chat, rlm)
    b = AuditBattery(target_endpoint="x", target_token="y", tasks_path=str(TASKS_YAML), reps=1, adapter=adapter, rlm_adapter=adapter)
    verdict = b.run()
    assert verdict.breakdown.test4_statistical_significance == "underpowered"
    assert verdict.overall == "needs-more-data"


def test_classify_helper_direct():
    bd = VerdictBreakdown(
        test1_fix_reliability="pass",
        test2_historical_bug_proof="no-evidence",
        test3_trace_verification="pass",
        test4_statistical_significance="null",
    )
    assert _classify(bd) == "healthy"

    bd_bug = VerdictBreakdown(
        test1_fix_reliability="pass",
        test2_historical_bug_proof="confirmed",
        test3_trace_verification="pass",
        test4_statistical_significance="significant",
    )
    assert _classify(bd_bug) == "bug-confirmed"
