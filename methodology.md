# Methodology: Silent Compound Failures in Agentic Decomposition Pipelines

## TL;DR

A 4-test audit battery detects silent compound failures in agentic decomposition
pipelines — failures where the system *appears* to be doing decomposition-and-recursion
but is in fact running singleton-fallback under the hood. The battery proves
bug existence, fix reliability, construct validity (real decomposition per call),
and statistical validity in under one hour of inference time. This document
describes the audit battery, the bug class it detects, and the evidence logs
from one validated instance (N=9, hybrid math/code tasks).

This methodology applies Cook & Campbell's *validity quartet* (1979) and Huang
et al.'s *gray failure* framing (HotOS 2017) to the agentic-pipeline setting.
We do not claim novelty on the validity types. We document one specific instance
of fallback-to-control artifact and propose this battery as a reusable instrument.

## The bug class (general pattern)

**Silent compound failure** in this context = two independent failure modes that
combine multiplicatively such that:

1. Each failure mode is incomplete (partial failure rate)
2. Their compound failure rate approaches 100%
3. Neither failure mode produces an error signal, log warning, or crash
4. The system gracefully degrades to a fallback that is *semantically identical*
   to the control arm being compared against
5. Apparent metrics on the failing arm match the control arm + noise + selection
   bias on the rare working calls

**Detection difficulty.** Standard test pyramid stops short of this layer:

- Unit tests pass (each component returns *something* of the expected type)
- Integration tests pass (fallback works correctly, just not the actual feature)
- E2E tests pass (system produces outputs of the expected shape)
- The bug is only visible if you ask: *"is this call doing what it claimed to be doing?"*
  — which requires per-call trace inspection, not metric inspection.

This is the **gray failure** class (Huang et al., HotOS 2017): the system appears
healthy to monitoring while broken to the actual use case. The *artifact-of-improvement*
twist — where gray failure on the experimental arm produces apparently-better metrics
because the failure mode is the control arm — is the specific variant this audit
battery targets.

## The specific bug observed

This methodology was developed catching a real instance:

### Component A: a decomposer model at a thinking-budget limit

- Stochastically exhausted its thinking budget and returned empty output 33–67% of
  the time on hybrid (multi-step math/code) tasks
- No error raised. No log warning. Empty string returned.

### Component B: a parser for the decomposer's output

- Designed for pure-YAML output
- Failed silently 100% of the time on prose+YAML hybrid output (which the model
  emitted by default)

### Compound effect

- P(success) = P(model emits content) × P(parser accepts) ≈ 33–67% × 0% (for the
  prose+YAML case) OR 33–67% × ~30% (for the rare pure-YAML output)
- Effective working rate: **0–33% per task**
- Failure mode: **singleton-fallback** — the system silently degraded to single-pass
  on failed decomposition. Single-pass was semantically identical to the control arm.

### Why it stayed hidden ~24 hours

- No exception, no log, no warning, no crash
- Apparent metrics on the experimental arm looked like apparent metrics on the
  control arm + noise + selection bias on the rare working calls
- Direction-of-difference was attributed to "decomposition helps" when it was
  actually selection-bias on the working calls
- The prior claim — *"decomposition beats single-pass"* — was entirely artifact

## The audit battery (4 tests, ~45 min)

Designed to answer four independent questions, none of which trust the others' answers.
Each test maps to one type from Cook & Campbell's validity quartet.

### Test 1 — Fix reliability (forward / internal validity)

**Question:** Is the patched system reliable, or did the validation smoke test get lucky?

**Method:** 3 calls per task × 3 tasks = 9 invocations with the patched config.
Measure parse-success rate.

**What it bulletproofs:** the fix claim. Without this, "we fixed it" rests on one
or two lucky calls.

### Test 2 — Historical bug proof (historical validity)

**Question:** Was the prior failure systematic or stochastic? Was the bug real?

**Method:** 9 direct calls to the OLD buggy config — 3 calls per task. Measure
empty-output rate and parse-failure rate independently to confirm the compound
mechanism.

**What it bulletproofs:** the bug claim. Most postmortems skip this step. Without
it, you cannot rule out that the prior measurements happened to be unlucky rather
than systematically broken.

This is the test most postmortems skip. Most "we fixed the bug" reports stop at
Test 1.

### Test 3 — Trace re-verification (construct validity)

**Question:** When the system *did* run decomposition, was it actually doing real
decomposition, or fallback in disguise?

**Method:** N reps with per-call trace capture. Record `n_subtasks` per call.
Confirm or refute that real decomposition occurred.

**What it bulletproofs:** construct validity — that the measurement is measuring
what it claims to measure. This is the layer the standard test pyramid omits by
default. Unit / integration / E2E tests verify type / composition / output shape.
They do not ask whether *this specific call* did what the system claimed. Per-call
trace capture is the only known way to assert construct validity on agentic
decomposition pipelines.

### Test 4 — Statistical analysis (statistical-conclusion validity)

**Question:** Is the apparent difference between arms actually significant?

**Method:** McNemar's exact test (matched pairs) + Fisher's exact test (aggregate)
+ direction-of-effect analysis.

**What it bulletproofs:** statistical-conclusion validity — that any reported
"difference" survives standard inference.

## Evidence logs (one validated instance)

### Test 1 (audit) — Fix reliability, N=9

```
9/9 parse success across 3 hybrid tasks.
Latency 9-14s per call.
No failures observed in N=9.
```

### Test 2 (audit) — Historical bug proof, N=9

```
Task   | Parse success | Pattern
-------|---------------|----------------------------------------------
H-001  | 1/3 (33%)     | model exhausted thinking budget on 2 of 3
H-002  | 3/3 (100%)    | model succeeded reliably on this task
H-003  | 1/3 (33%)     | exhausted on 2 of 3
```

Combined with the parser's 100% failure rate on prose+YAML output:
**compound bug guaranteed singleton-fallback on most prior calls.**

### Test 3 (audit) — Trace re-verification on H-001, N=3

```
Rep | n_subtasks | Correctness
0   | 3          | 0 (wrong answer)
1   | 4          | 0
2   | 3          | 0
```

Real decomposition confirmed: 3/3 reps had `n_subtasks > 1`.
All 3 produced wrong final answers.

### Test 4 (audit) — Statistical analysis on N=3

```
McNemar's exact (matched pairs):
  arm_A=1, arm_C=0 pairs: 2
  arm_A=0, arm_C=1 pairs: 0
  p = 0.5 (two-tailed)

Fisher's exact (aggregate 8/9 vs 6/9):
  p ≈ 0.58

Direction: arm_A (single-pass) ≥ arm_C (decomposition) on all 3 tasks.
```

### Clean rerun (post-audit), N=9 — confirmatory

| Task | n_real / 3 | correct / 3 | mean latency | vs single-pass |
|---|---|---|---|---|
| H-001 | 3/3 real ✓ | 0/3 ❌ | 180s | regresses |
| H-002 | 3/3 real ✓ | 3/3 ✓ | 292s ± 181 | ties, ~2× slower |
| H-003 | 3/3 real ✓ | 3/3 ✓ | 381s ± 23 | ties, ~2.4× slower |
| Total | 9/9 verified real | 6/9 | — | arm_A 8/9 = 89%, arm_C 6/9 = 67% |

Fisher's exact at N=9: p ≈ 0.58, never significant. Direction consistent.

## Defensible claims (final)

| Claim | N | Status |
|---|---|---|
| Compound bug existed | N=9 historical | ✓ irrefutable |
| Fix is reliable | N=18 combined | ✓ zero failures observed |
| Decomposition is real post-fix | N=9 | ✓ trace-verified per call |
| Decomposition arm regresses on H-001 | N=3 | ✓ 0/3 vs 2/3 |
| Decomposition arm ≤ single-pass on hybrid tasks | N=9 | ✓ direction consistent |
| Decomposition arm has 2-2.4× latency cost on tie cases | N=9 | ✓ new finding |
| Decomposition arm significantly worse | N=9 | ❌ underpowered (Fisher p ≈ 0.58) |
| Decomposition has *any* quality benefit on hybrid | N=9 | ❌ no positive direction observed |

## Methodology contribution

The audit battery's reusable contribution: **Test 2 (historical replay) + Test 3
(per-call trace verification) together rule out the gray-failure / fallback-to-control
artifact.** Standard postmortems do Test 1 (forward) and Test 4 (stats). The middle
two tests are what catch this failure class.

**Test 3 in particular** asks the question no unit/integration/E2E test asks by
default: *did this specific call do what the system claimed?* Trace capture per call
is the only known way to answer construct validity on agentic decomposition pipelines.

## When to use this battery

Apply this audit battery to any agentic system where:

1. The system claims to do internal decomposition / recursion / multi-step planning
2. The system has a fallback path (degraded mode, retries, simpler model)
3. The fallback path is semantically identical or similar to your control comparison
4. You're publishing or relying on metrics that compare the multi-step path vs single-pass

**Especially apply this battery if any of:**

- You're claiming a complex pipeline outperforms a simple baseline
- Your monitoring shows the pipeline is "healthy" but downstream metrics seem noisy
- Your test suite passes but you've never per-call-verified that the right code path executed
- You have a recent change to the decomposition stage and you're seeing surprising results

## Caveats and scope

**This methodology has been validated once.** Apply it to your own pipeline before
claiming it generalizes. The specific bug pattern (model thinking-budget exhaustion ×
parser format mismatch) is one of many possible compound-failure mechanisms. The
audit battery as a *pattern* (four-tier validity quartet applied to agentic systems)
is more durable than the specific tests, but neither is a guaranteed catch-all.

**N=9 is sufficient for the bug-finding contribution** (categorical: bug existed,
fix works, decomposition is real post-fix). **N=9 is insufficient for the comparison
claim** at standard significance thresholds. For publication-grade comparison work,
plan N=30+ per cell across 15-20 tasks with matched system prompts and controlled
temperature.

## References

- Cook, T. D., & Campbell, D. T. (1979). *Quasi-Experimentation: Design & Analysis
  Issues for Field Settings*. Houghton Mifflin. The validity quartet (internal,
  external, construct, statistical-conclusion).
- Huang, P., Guo, C., Zhou, L., Lorch, J. R., Dang, Y., Chintalapati, M., & Yao, R.
  (2017). *Gray Failure: The Achilles' Heel of Cloud-Scale Systems*. HotOS '17.
  The naming and analysis of "system appears healthy to monitoring, broken to users."
- Bairavasundaram, L. N., Goodson, G. R., Schroeder, B., Arpaci-Dusseau, A. C., &
  Arpaci-Dusseau, R. H. (2008). *An Analysis of Data Errors in the Storage Stack*.
  FAST '08. Silent data corruption as a category.
- Reason, J. (1990). *Human Error*. Cambridge University Press. The Swiss-cheese
  model for compound failures.
