from silent_compound_failures.cost import (
    RATE_CARD_DEFAULT,
    CostEntry,
    CostTracker,
)


def test_record_returns_entry_with_correct_cost():
    tracker = CostTracker(budget_usd=1.0)
    entry = tracker.record("claude-haiku-4-5", prompt_tokens=1000, completion_tokens=1000)
    assert isinstance(entry, CostEntry)
    # 1k prompt × $0.001 + 1k completion × $0.005 = $0.006
    assert abs(entry.cost_usd - 0.006) < 1e-9


def test_local_model_costs_zero():
    tracker = CostTracker(budget_usd=1.0)
    e = tracker.record("qwen2.5-coder:14b", prompt_tokens=10000, completion_tokens=10000)
    assert e.cost_usd == 0.0
    assert tracker.total_spent() == 0.0


def test_unknown_model_defaults_to_zero_rate():
    tracker = CostTracker(budget_usd=1.0)
    e = tracker.record("not-in-rate-card", prompt_tokens=1000, completion_tokens=1000)
    assert e.cost_usd == 0.0


def test_should_halt_when_budget_reached():
    tracker = CostTracker(budget_usd=0.01)
    tracker.record("claude-opus-4-7", prompt_tokens=1000, completion_tokens=1000)  # $0.015 + $0.075 = $0.090
    assert tracker.should_halt() is True
    assert tracker.remaining() < 0


def test_remaining_decreases_with_spend():
    tracker = CostTracker(budget_usd=1.0)
    tracker.record("claude-haiku-4-5", prompt_tokens=1000, completion_tokens=1000)
    assert abs(tracker.remaining() - (1.0 - 0.006)) < 1e-9


def test_summary_groups_by_model():
    tracker = CostTracker(budget_usd=10.0)
    tracker.record("claude-haiku-4-5", prompt_tokens=1000, completion_tokens=0)
    tracker.record("claude-haiku-4-5", prompt_tokens=1000, completion_tokens=0)
    tracker.record("claude-opus-4-7", prompt_tokens=1000, completion_tokens=0)
    summary = tracker.summary()
    assert set(summary.keys()) == {"claude-haiku-4-5", "claude-opus-4-7"}
    assert abs(summary["claude-haiku-4-5"] - 0.002) < 1e-9


def test_default_rate_card_includes_common_providers():
    keys = set(RATE_CARD_DEFAULT.keys())
    assert "qwen2.5-coder:14b" in keys
    assert any(k.startswith("claude-") for k in keys)
    assert any(k.startswith("gpt-") for k in keys)
