# Timeline — silent compound failure → audit → fix → honest re-measurement

All times America/Chicago, 2026-05-12 unless otherwise noted.

## Phase 1 — bogus claims accumulating (prior 24h, ending ~2026-05-12 morning)

- 2026-05-12 free-results.json: "Arm-B RLM beats single-pass 3/3 vs 1/3 on hybrid tasks" — bogus, broken decomposer
- 2026-05-12 depth2-validation-results.json: "depth-2 dormant: decomposer rejected recurse" — bogus, decomposer never executed real decomposition
- 2026-05-12 ablation-6k-results.json: "RLM is architectural win at $0/token" — bogus same reason
- 2026-05-13 iter-1/iter-2 verdicts on /v1/rlm rollout: "SHIP as opt-in" — singleton-vs-singleton comparison

## Phase 2 — adversarial reductionist audit

- 18:30 — pre-registration written for /v1/rlm rollout (MC methodology), N=3 matched-pair design
- 18:45 — iter-1 measurement run, results "look reasonable" — H-001 hit outcome (c) edge
- 19:00 — iter-2 measurement run (duplicate-decompose fix), reduced latency 25-32%
- 19:30 — joey: "use adversarial reductionism" → audit on own work
- 19:35 — pink elephant identified: every trace file shows singleton-fallback fingerprint `## reasoning_fast` × 1 header
- 19:40 — direct probe of `_hub_call("qwq-32b-awq", decompose_prompt, max_tokens=1500)`: returns 0 chars on 3/3 tasks
  - Caveat: probe ran with auth env LLAMA_API_KEY="test" → 401, masked real failure mode
- 19:50 — real cause identified: qwq emits prose+yaml; `_parse_decomposition` uses `yaml.safe_load` on whole string; parse fails 100% on prose+yaml
- 20:00 — synthetic repro of parser failure (see evidence/bug-repro/parser_failure_synthetic.py)

## Phase 3 — fix

- 20:50 — parser patched: multi-candidate extraction (fenced YAML, from-first-prompt-marker, whole text)
- 20:50 — decomposer model swap qwq-32b-awq → qwen2.5-32b-instruct-awq (non-thinking, structured-output-reliable, 15s vs 240s decompose)
- 21:00 — hub restarted with both fixes

## Phase 4 — verification (audit battery, 3 tests)

- Test 1 — Qwen-decomposer reliability: 9 calls (3 tasks × 3 reps). Result: 9/9 parse success.
- Test 2 — Prior-config repro (qwq at max_tokens=1500): 9 calls. Result: 5/9 parse success (33-67% failure on H-001/H-003, 100% success on H-002). Empirical confirmation that compound bug existed and was load-bearing on prior claims.
- Test 3 — Per-call trace verification on H-001 via /v1/rlm post-fix: 3 calls. Result: 3/3 reps had n_subtasks ∈ {3, 4, 3}. Real decomposition confirmed in production endpoint.

## Phase 5 — honest re-measurement

- N=3 matched-pair (arm_A: single-pass qwq CoT; arm_C: /v1/rlm post-fix)
- Per-call trace capture: all 9 arm_C calls confirmed n_subtasks > 1 (3, 3, 2, 3, 3, 4, 3, 3, 3)

| Task  | arm_A correct/3 | arm_C correct/3 | arm_A mean lat | arm_C mean lat |
|-------|------------------|------------------|----------------|----------------|
| H-001 | 2/3              | 0/3              | ~150s          | 180s ±60       |
| H-002 | 3/3              | 3/3              | ~150s          | 292s ±181      |
| H-003 | 3/3              | 3/3              | 158s ±2        | 381s ±23       |
| TOTAL | **8/9 = 89%**   | **6/9 = 67%**   |                |                |

Statistical: Fisher's exact p=0.58. NOT significant at N=3. Directional only: arm_A ≥ arm_C on every task; arm_C never beats arm_A; H-001 is a clear regression direction.

## Phase 6 — what got published

- Email to Jacob (msg ID 19e1e8c955c50606, 2026-05-12 18:36 CDT) — correction + bug story + honest measurement + offer of N=30 rerun
- Kronos commit a7a791c on branch 001-multi-box-api — bug fix + honest measurement evidence + INVALIDATED_PRIOR.md sibling files in prior measurement dirs
- T36 paper outline (author's local notes)
- This repo (silent-compound-failures) — methodology + reusable audit battery + evidence logs

## Recoverable / not recoverable

Recoverable:
- Fix is reliable in N=9 (qwen-32b decomposer + patched parser)
- Audit battery now exists as reusable instrument-validation infra
- Honest direction claim: RLM ≤ single-pass on tested 3-hybrid-task set

Not recoverable:
- 24h of work-time spent on a metric that was measuring nothing
- Confidence in any prior comparative experiments (any RLM-vs-X claim from before 2026-05-12 fix needs re-runs)
- The pre-fix communications (correction email is the only remedy)
