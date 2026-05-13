"""Mocked-LLM integration test for AuditBattery.run().

Mocks requests.post at the network layer so the full adapter -> battery -> verdict
path executes without any real LLM call. Encodes the canonical bug-confirmed
pattern: test1 healthy, test2 broken (historical compound bug shape),
test3 trace OK. This is the regression net for dead-code wiring — if a future
refactor wires AuditBattery so it skips test 3, this test fails.
"""
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from silent_compound_failures.audit_battery import AuditBattery
from silent_compound_failures.llm_adapter import OpenAICompatAdapter, RLMHubAdapter

REPO_ROOT = Path(__file__).parent.parent
TASKS_YAML = REPO_ROOT / "tasks_example.yaml"

GOOD_YAML = (
    "- prompt: Write the function\n  intent: code\n"
    "- prompt: Verify the result\n  intent: verification\n"
    "- prompt: Synthesize answer\n  intent: synthesis\n"
)

# Prose with malformed YAML — parses as None per test_parser test_handles_malformed_yaml
HYBRID_BROKEN = """Let me decompose this task:

- prompt: foo
  bad: :
  broken: yaml: syntax:
"""


def _chat_response(content: str, tokens: int = 100, finish: str = "stop"):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": content}, "finish_reason": finish}],
        "usage": {"completion_tokens": tokens},
    }
    return resp


def _rlm_response(content: str, n_subtasks: int):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "content": content,
        "trace": {
            "n_subtasks": n_subtasks,
            "subtask_intents": ["code", "verification", "synthesis"][:n_subtasks],
            "backends": ["mock-backend"],
        },
    }
    return resp


@pytest.fixture
def mock_network():
    """Route requests.post to canned responses based on URL + payload."""
    test1_count = {"n": 0}
    test2_count = {"n": 0}
    test3_count = {"n": 0}
    test3_n_subtasks = [3, 4, 3]

    # 4 empty + 5 prose+broken-YAML hybrids for test 2 — both shapes fail parsing.
    test2_responses = [_chat_response("", tokens=1500, finish="length")] * 4 + [
        _chat_response(HYBRID_BROKEN, tokens=200, finish="stop")
    ] * 5

    def fake_post(url: str, json=None, headers=None, timeout=None, **_kw):
        if url.endswith("/v1/rlm"):
            i = test3_count["n"]
            test3_count["n"] += 1
            return _rlm_response(GOOD_YAML, test3_n_subtasks[i % len(test3_n_subtasks)])
        # /v1/chat/completions — branch on model name
        model = (json or {}).get("model", "")
        if "qwq" in model:
            i = test2_count["n"]
            test2_count["n"] += 1
            return test2_responses[i % len(test2_responses)]
        # default: test1 (qwen)
        test1_count["n"] += 1
        return _chat_response(GOOD_YAML)

    with patch("silent_compound_failures.llm_adapter.requests.post", side_effect=fake_post):
        yield {"test1": test1_count, "test2": test2_count, "test3": test3_count}


def test_integration_bug_confirmed_via_mocked_network(mock_network):
    battery = AuditBattery(
        target_endpoint="http://mock-endpoint",
        target_token="mock-token",
        tasks_path=str(TASKS_YAML),
        reps=3,
        adapter=OpenAICompatAdapter(base_url="http://mock-endpoint", token="mock-token"),
        rlm_adapter=RLMHubAdapter(base_url="http://mock-endpoint", token="mock-token"),
    )
    verdict = battery.run()

    # Network was actually exercised — 9 + 9 + 3 = 21 calls
    assert mock_network["test1"]["n"] == 9, "Test 1 should fire 9 chat calls (3 tasks × 3 reps)"
    assert mock_network["test2"]["n"] == 9, "Test 2 should fire 9 chat calls"
    assert mock_network["test3"]["n"] == 3, "Test 3 should fire 3 rlm calls"

    # Canonical bug-confirmed pattern assertions
    assert verdict.breakdown.test1_fix_reliability == "pass", "Test 1 had 9/9 valid YAML — must be 'pass'"
    assert verdict.breakdown.test2_historical_bug_proof == "confirmed", "Test 2 had 9/9 fail — compound bug must be 'confirmed'"
    assert verdict.breakdown.test3_trace_verification == "pass", "Test 3 traces had n_subtasks > 1 — must be 'pass'"
    assert verdict.breakdown.test4_statistical_significance == "underpowered", "N=18 with effect but <30 → 'underpowered' per stats heuristic"

    assert verdict.overall == "bug-confirmed"
    assert len(verdict.raw_results) == 21


def test_integration_test3_skip_would_fail_assertion(mock_network):
    """Dead-code guard: if AuditBattery.run() ever stops calling _test3_trace_verification,
    the n_per_task for H-001 will drop below the 3+3 (test1+test2) + 3 (test3) baseline,
    and test3 breakdown will be 'fail'. This pins the behavior so a future refactor
    can't silently skip the trace verification step.
    """
    battery = AuditBattery(
        target_endpoint="http://mock-endpoint",
        target_token="mock-token",
        tasks_path=str(TASKS_YAML),
        reps=3,
        adapter=OpenAICompatAdapter(base_url="http://mock-endpoint", token="mock-token"),
        rlm_adapter=RLMHubAdapter(base_url="http://mock-endpoint", token="mock-token"),
    )
    verdict = battery.run()
    test3_results = [r for r in verdict.raw_results if r.test == "rlm_trace_h001"]
    assert len(test3_results) == 3, "Battery must run all 3 test3 reps — wiring guard"
