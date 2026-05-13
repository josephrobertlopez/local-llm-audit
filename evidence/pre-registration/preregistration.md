# Pre-registration: /v1/rlm endpoint rollout

**Date:** 2026-05-13
**Methodology:** MC (Markov Chain) empirical discipline — pre-register outcomes, build instrument first, falsifiable.

## Question
Does exposing the L5 depth-1 hierarchical_dispatch orchestrator as a new /v1/rlm HTTP endpoint preserve the quality + latency of in-process orchestrator dispatch?

The in-process Arm-B baseline (measurement 2026-05-12_rlm-hybrid/free-results.json) achieved 3/3 vs single-pass 1/3 on H-001/H-002/H-003. This pre-reg asks whether the HTTP wrapper preserves that win.

## State space
- Hub state: model loaded, queue depth, /v1/rlm route active
- Orchestrator state: subtask list, specialist outputs, aggregation
- HTTP layer: status, response body, headers, latency

## Transition mechanism
POST /v1/rlm {prompt} -> router.classify -> controller.run(decomposer=llm_decomposer, specialist_call=hub_only) -> in-process specialist calls (via existing cache.acquire/release) -> aggregator -> JSON response.

NOTE: orchestrator calls back into the same hub via httpx for specialist dispatch. This is intentional and matches Arm-B baseline behavior. No new external dependencies.

## Observables
- correctness: Q-scorer regex match per tasks_rlm.yaml success_check_regex
- end-to-end latency: HTTP request to response (ms)
- trace fidelity: same subtask count + same specialist routes as in-process baseline
- token count: sum of all specialist call tokens (from local hub responses)

## Pre-registered outcomes (matched pair vs in-process baseline on H-001/H-002/H-003)

| Outcome | Criterion | Decision |
|---|---|---|
| (a) | 3/3 correctness AND HTTP latency overhead <30% vs in-process | SHIP as default /v1/rlm API |
| (b) | 3/3 correctness AND HTTP latency overhead 30-100% | SHIP as opt-in, document overhead |
| (c) | correctness <3/3 OR latency >2x in-process | DON'T SHIP, document semantic gap or perf trap |

**Stop-rule:** if outcome (c), max 2 design iterations to chase (a). Beyond that = chasing, per MC discipline.

## N
N=3 tasks (H-001/H-002/H-003), matched-pair with the Arm-B baseline. Same N as the win we are trying to preserve.

## Falsification criteria (instrument validity)
- 500 status or malformed JSON -> INSTRUMENT FAILURE, fix and retry once
- HTTP layer produces different subtask count than in-process -> SEMANTIC DIVERGENCE, investigate before scoring
- Total wall-clock >10 min -> dispatch timeout, partial results discarded

## Instrument
- /v1/rlm route in hub.py (~25 LOC), wraps existing orchestrator.run with hub-only specialist binding
- Harness script (~50 LOC): dispatches H-001/H-002/H-003 via HTTP AND via direct in-process import, compares
- Existing Q-scorer (src/benchmark/quality/scorer.py) applied unchanged

## Pre-commit assertion
Zero /v1/rlm code exists at the time of this writing.
