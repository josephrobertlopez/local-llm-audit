import pytest

from silent_compound_failures.stats import (
    StatsResult,
    bootstrap_ci_diff,
    fisher_exact_aggregate,
    mcnemar_matched_pairs,
    power_analysis,
)


def test_fisher_known_values():
    # 8/9 vs 6/9 should be far from significant
    r = fisher_exact_aggregate(8, 9, 6, 9)
    assert isinstance(r, StatsResult)
    assert r.test_name == "fisher_exact"
    assert 0.3 < r.p_value < 0.9, f"expected p in mid-range for 8/9 vs 6/9, got {r.p_value}"


def test_fisher_extreme_effect_is_significant():
    # 9/9 vs 0/9 → p << 0.05
    r = fisher_exact_aggregate(9, 9, 0, 9)
    assert r.p_value < 0.001
    assert r.interpretation == "significant"


def test_mcnemar_handles_zero_discordant():
    # All pairs agree → no discordant cells → p = 1.0, "null"
    a = [1, 1, 0, 0, 1]
    b = [1, 1, 0, 0, 1]
    r = mcnemar_matched_pairs(a, b)
    assert r.p_value == 1.0
    assert r.interpretation == "null"


def test_mcnemar_strong_discordant():
    # All pairs flip a=1, b=0 → maximal discordance
    a = [1] * 12
    b = [0] * 12
    r = mcnemar_matched_pairs(a, b)
    assert r.p_value < 0.01
    assert r.interpretation == "significant"


def test_mcnemar_length_mismatch_raises():
    with pytest.raises(ValueError):
        mcnemar_matched_pairs([1, 0], [1, 0, 0])


def test_bootstrap_ci_includes_zero_when_null():
    # Two arms drawn from identical distribution → CI should include 0
    a = [0.5] * 50
    b = [0.5] * 50
    lo, hi = bootstrap_ci_diff(a, b, n_iter=500, seed=0)
    assert lo <= 0.0 <= hi


def test_bootstrap_ci_excludes_zero_when_effect_large():
    a = [1.0] * 50
    b = [0.0] * 50
    lo, hi = bootstrap_ci_diff(a, b, n_iter=500, seed=0)
    # All bootstrap samples will have diff = 1.0 → CI is exactly [1.0, 1.0]
    assert lo > 0.0


def test_power_analysis_returns_sensible_n():
    # Small effect → large N needed
    n_small = power_analysis(effect_size=0.1, alpha=0.05, desired_power=0.8)
    # Large effect → small N needed
    n_large = power_analysis(effect_size=0.5, alpha=0.05, desired_power=0.8)
    assert n_small > n_large
    assert n_large >= 1
