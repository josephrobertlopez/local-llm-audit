"""Cost tracker — bind LLM token usage to estimated USD spend with budget halting.

Rate card current as of 2026-05. Future contributors: update RATE_CARD_DEFAULT
when provider pricing changes, and bump the constant below.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

RATE_CARD_VERSION = "2026-05"

# {model_name: {'prompt': $/1k_tokens, 'completion': $/1k_tokens}}
RATE_CARD_DEFAULT: dict[str, dict[str, float]] = {
    # Local — free
    "qwen2.5-coder:14b": {"prompt": 0.0, "completion": 0.0},
    "qwen2.5-coder:7b": {"prompt": 0.0, "completion": 0.0},
    "qwen2.5-32b-instruct-awq": {"prompt": 0.0, "completion": 0.0},
    "qwq-32b-awq": {"prompt": 0.0, "completion": 0.0},
    # Anthropic (rate card as of 2026-05)
    "claude-haiku-4-5": {"prompt": 0.001, "completion": 0.005},
    "claude-sonnet-4-6": {"prompt": 0.003, "completion": 0.015},
    "claude-opus-4-7": {"prompt": 0.015, "completion": 0.075},
    # OpenAI (rate card as of 2026-05)
    "gpt-4o": {"prompt": 0.0025, "completion": 0.010},
    "gpt-4o-mini": {"prompt": 0.00015, "completion": 0.0006},
}


@dataclass
class CostEntry:
    timestamp: str
    model: str
    completion_tokens: int
    prompt_tokens: int
    cost_usd: float


@dataclass
class CostTracker:
    budget_usd: float
    rate_card: dict[str, dict[str, float]] = field(default_factory=lambda: dict(RATE_CARD_DEFAULT))
    entries: list[CostEntry] = field(default_factory=list)

    def _rate_for(self, model: str) -> dict[str, float]:
        return self.rate_card.get(model, {"prompt": 0.0, "completion": 0.0})

    def record(self, model: str, prompt_tokens: int, completion_tokens: int) -> CostEntry:
        rate = self._rate_for(model)
        cost = (prompt_tokens / 1000.0) * rate["prompt"] + (completion_tokens / 1000.0) * rate["completion"]
        entry = CostEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            model=model,
            completion_tokens=completion_tokens,
            prompt_tokens=prompt_tokens,
            cost_usd=cost,
        )
        self.entries.append(entry)
        return entry

    def total_spent(self) -> float:
        return sum(e.cost_usd for e in self.entries)

    def remaining(self) -> float:
        return self.budget_usd - self.total_spent()

    def should_halt(self) -> bool:
        return self.total_spent() >= self.budget_usd

    def summary(self) -> dict[str, float]:
        by_model: dict[str, float] = {}
        for e in self.entries:
            by_model[e.model] = by_model.get(e.model, 0.0) + e.cost_usd
        return by_model
