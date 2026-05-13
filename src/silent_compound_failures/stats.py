"""Stats module — Fisher's exact, McNemar, bootstrap CI, power analysis.

All routines return StatsResult so downstream consumers can render uniformly.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional, Sequence

from scipy import stats as sp_stats


@dataclass
class StatsResult:
    test_name: str
    p_value: float
    test_statistic: float
    interpretation: str  # "significant" | "underpowered" | "null"
    ci_low: Optional[float] = None
    ci_high: Optional[float] = None


def _interpret(p_value: float, n_total: int, alpha: float = 0.05, min_n: int = 12) -> str:
    if n_total < min_n:
        return "underpowered"
    return "significant" if p_value < alpha else "null"


def fisher_exact_aggregate(
    arm_a_correct: int,
    arm_a_total: int,
    arm_b_correct: int,
    arm_b_total: int,
    alpha: float = 0.05,
) -> StatsResult:
    """2x2 Fisher's exact on arm-A vs arm-B success counts."""
    table = [
        [arm_a_correct, arm_a_total - arm_a_correct],
        [arm_b_correct, arm_b_total - arm_b_correct],
    ]
    odds, p = sp_stats.fisher_exact(table, alternative="two-sided")
    n_total = arm_a_total + arm_b_total
    return StatsResult(
        test_name="fisher_exact",
        p_value=float(p),
        test_statistic=float(odds),
        interpretation=_interpret(float(p), n_total, alpha=alpha),
    )


def mcnemar_matched_pairs(
    arm_a_results: Sequence[int],
    arm_b_results: Sequence[int],
    alpha: float = 0.05,
) -> StatsResult:
    """McNemar's test on paired binary outcomes. arm_a/arm_b are 0/1 lists of equal length."""
    if len(arm_a_results) != len(arm_b_results):
        raise ValueError("arm_a_results and arm_b_results must be equal length (matched pairs)")
    b = sum(1 for a, c in zip(arm_a_results, arm_b_results) if a == 1 and c == 0)
    c = sum(1 for a, cc in zip(arm_a_results, arm_b_results) if a == 0 and cc == 1)
    n_discordant = b + c
    if n_discordant == 0:
        return StatsResult(
            test_name="mcnemar",
            p_value=1.0,
            test_statistic=0.0,
            interpretation="null",
        )
    # Continuity-corrected chi-square approximation
    statistic = ((abs(b - c) - 1) ** 2) / n_discordant
    p = 1.0 - sp_stats.chi2.cdf(statistic, df=1)
    return StatsResult(
        test_name="mcnemar",
        p_value=float(p),
        test_statistic=float(statistic),
        interpretation=_interpret(float(p), len(arm_a_results), alpha=alpha),
    )


def bootstrap_ci_diff(
    arm_a: Sequence[float],
    arm_b: Sequence[float],
    n_iter: int = 10000,
    alpha: float = 0.05,
    seed: Optional[int] = 0,
) -> tuple[float, float]:
    """Percentile bootstrap CI for the mean difference (arm_a - arm_b)."""
    rng = random.Random(seed)
    a = list(arm_a)
    b = list(arm_b)
    if not a or not b:
        return (0.0, 0.0)
    n_a = len(a)
    n_b = len(b)
    diffs: list[float] = []
    for _ in range(n_iter):
        sample_a = [a[rng.randrange(n_a)] for _ in range(n_a)]
        sample_b = [b[rng.randrange(n_b)] for _ in range(n_b)]
        diffs.append(sum(sample_a) / n_a - sum(sample_b) / n_b)
    diffs.sort()
    lo_idx = int((alpha / 2) * n_iter)
    hi_idx = int((1 - alpha / 2) * n_iter)
    return diffs[lo_idx], diffs[hi_idx]


def power_analysis(
    effect_size: float,
    alpha: float = 0.05,
    desired_power: float = 0.8,
) -> int:
    """Approximate N-per-arm for a two-proportion z-test at given effect size.

    effect_size = |p1 - p2| treated as Cohen's h proxy (close for moderate proportions).
    """
    if effect_size <= 0:
        return math.inf  # type: ignore[return-value]
    z_alpha = float(sp_stats.norm.ppf(1 - alpha / 2))
    z_beta = float(sp_stats.norm.ppf(desired_power))
    # Conservative variance assumption p(1-p) ≤ 0.25
    n = ((z_alpha + z_beta) ** 2) * 2 * 0.25 / (effect_size ** 2)
    return int(math.ceil(n))
