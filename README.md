# local-llm-audit

**Gray-failure detection in agentic decomposition pipelines.**

This repo documents a 4-test audit battery that catches silent compound failures in
recursive language model (RLM) / decomposition pipelines — the kind of failures where
the system *appears* to be doing decomposition-and-recursion but is in fact running
singleton-fallback under the hood, producing measurements that compare a control arm
against itself plus noise.

The audit battery applies Cook & Campbell's [validity quartet (1979)][cook-campbell]
and Huang et al.'s [gray-failure framing (2017)][gray-failures] to the agentic-pipeline
setting. We do not claim novelty on the validity types. We document one specific instance
where fallback-to-control creates an artifact-of-improvement, and propose this audit
battery as a reusable instrument for similar pipelines.

## The bug (one-paragraph)

Two independent silent failures combined multiplicatively:

1. The decomposer model (`qwq-32b-awq` at 1500-token thinking budget) stochastically
   exhausted its budget and returned empty output 33–67% of the time on hybrid tasks.
   No exception, no log warning.
2. The parser for the decomposer's output failed 100% of the time on its prose+YAML
   hybrid format (the parser was written for pure YAML).

The system gracefully degraded to **singleton-fallback** — semantically identical to
the control arm being compared against. The apparent "RLM beats single-pass" signal
was selection-bias on the rare working calls plus noise on the singleton-fallback runs.

Live for ~24 hours before catch.

## The 4-test audit battery

| Test | Question | Validity type | N | Method |
|------|----------|---------------|---|--------|
| **1. Fix reliability** | Is the patched system reliable, or did smoke testing get lucky? | Forward / internal | 9 | 3 reps × 3 tasks on patched config, measure parse-success rate |
| **2. Historical bug proof** | Was the prior failure systematic or stochastic? | Historical | 9 | 3 reps × 3 tasks on *unpatched* config, measure failure pattern |
| **3. Trace re-verification** | Did the system actually do what it claimed per-call? | Construct | 3+ | Per-call trace capture with `n_subtasks` recorded |
| **4. Statistical analysis** | Is the apparent difference significant? | Statistical-conclusion | All | Fisher's exact + McNemar |

**Test 2 is the one most postmortems skip.** Most "we fixed the bug" reports stop at
Test 1. Without Test 2, you cannot rule out that the prior measurements happened to
be unlucky rather than systematically broken.

**Test 3 is the layer the standard test pyramid omits by default.** Unit / integration /
E2E tests verify that components return the right *type*, compose correctly, and produce
expected *outputs*. They do not ask whether *this specific call* did what the system
claimed. Per-call trace capture is the only known way to assert construct validity on
agentic decomposition pipelines.

## Results (N=9 clean rerun, post-fix)

Across 3 hybrid math/code tasks (`H-001` train-meeting calculation, `H-002` permutation
formula, `H-003` recurrence relation):

| Task | RLM correct | single-pass correct | RLM mean latency | Direction |
|------|-------------|---------------------|------------------|-----------|
| H-001 | 0/3 | 2/3 | 180s | RLM regresses |
| H-002 | 3/3 | 3/3 | 292s ± 181 | tie, ~2× slower |
| H-003 | 3/3 | 3/3 | 381s ± 23 | tie, ~2.4× slower |
| **Aggregate** | **6/9 (67%)** | **8/9 (89%)** | — | RLM ≤ single-pass on every task |

All 9 RLM runs had verified per-call decomposition (`n_subtasks` ∈ {2, 3, 3, 3, 3, 4, 3, 3, 3})
— the bug is fully out of the data.

## What's defensible

- The compound bug existed (irrefutable, N=9 historical)
- The fix is reliable (N=18 combined audit + rerun, zero failures)
- RLM does real decomposition post-fix (trace-verified per call)
- RLM ≤ single-pass on these 3 hybrid tasks (directional, N=9)
- RLM carries 2–2.4× latency cost on tie cases (new finding)

## What's NOT defensible

- "RLM is significantly worse than single-pass" — Fisher's exact p ≈ 0.58, underpowered
- Generalization beyond hybrid math/code tasks (only 3 task classes tested)
- "RLM never helps" — only tested where decomposition was not structurally aligned to
  task shape; explicit-subtask-structure tasks (planning, multi-step agentic) might
  show different results

## Quickstart

```bash
git clone https://github.com/josephrobertlopez/local-llm-audit.git
cd local-llm-audit
pip install -r requirements.txt

# Point at your hub
export RLM_HUB_URL=http://your-hub:1337
export RLM_TOKEN=your-token

# Run the audit battery
python audit_battery.py --tasks tasks_example.yaml --out-dir ./audit-results
```

Inspect `audit-results/raw.json` for per-call data, console output for summary verdict.

To extend with different benchmarks: write a tasks YAML matching `tasks_example.yaml` format, point at any OpenAI-compatible endpoint with `/v1/rlm` support. Hardware-agnostic — user provides the endpoint.

The battery assumes your decomposition endpoint exposes a `trace.n_subtasks` field
(or equivalent) so Test 3 can verify real decomposition occurred. If your endpoint
doesn't expose traces, **add trace capture before running the battery** — without it,
you cannot answer construct validity.

## Tests

Parser unit tests (the component that silently failed for 24 hours):

```bash
pip install -r requirements.txt
pytest tests/ -v
```

10 test cases cover: clean YAML, prose+YAML hybrid (the bug case), empty input,
malformed YAML, non-list YAML, intent extraction, edge cases.

## Citations

- [cook-campbell]: Cook, T. D., & Campbell, D. T. (1979). *Quasi-Experimentation: Design & Analysis Issues for Field Settings*. The validity quartet (internal, external, construct, statistical-conclusion).
- [gray-failures]: Huang, P. et al. (2017). *Gray Failure: The Achilles' Heel of Cloud-Scale Systems*. HotOS. The naming and analysis of "system appears healthy to monitoring, broken to users."
- Bairavasundaram, L. N. et al. (2008). *An Analysis of Data Errors in the Storage Stack*. FAST. Silent data corruption as a category.
- Reason, J. (1990). *Human Error*. Cambridge University Press. The Swiss-cheese model for compound failures.

## Methodology note

A long-form methodology note with full audit-battery design rationale, evidence logs,
and the meta-insight about Test 2 / Test 3 is in `methodology.md`.

## Cost expectations

A full audit run is 21 LLM calls (9 for Test 1 + 9 for Test 2 + 3 for Test 3) at default
`reps=3`. Rough $-per-audit on common models, using the rate card in
`silent_compound_failures.cost.RATE_CARD_DEFAULT` (current as of **2026-05** — bump when
provider pricing changes):

| Endpoint | Cost per audit (approx) | Notes |
|----------|-------------------------|-------|
| Local Ollama (qwen2.5-coder:14b) | $0.00 | GPU electricity only |
| Anthropic Haiku 4.5 | ~$0.05–0.15 | depends on task length |
| Anthropic Sonnet 4.6 | ~$0.20–0.60 | |
| Anthropic Opus 4.7 | ~$1.00–3.00 | |
| OpenAI gpt-4o | ~$0.30–0.80 | |

Use `CostTracker` to enforce a per-run budget:

```python
from silent_compound_failures.audit_battery import AuditBattery
from silent_compound_failures.cost import CostTracker

tracker = CostTracker(budget_usd=2.00)
verdict = AuditBattery(
    target_endpoint="https://api.anthropic.com",
    target_token=os.environ["ANTHROPIC_API_KEY"],
    tasks_path="tasks_example.yaml",
    cost_tracker=tracker,
).run()
print(f"Spent ${tracker.total_spent():.4f} of ${tracker.budget_usd}")
```

The battery halts before exceeding the budget — the verdict may be marked
`needs-more-data` if fewer than the required samples were collected.

## Audits in the wild

The `audits/` directory holds community-submitted audit results from teams who ran
this battery against their own decomposition pipelines. To submit your own, see
[CONTRIBUTING.md](CONTRIBUTING.md). We accept audits framed in the verdict's
vocabulary (pass / fail / confirmed / no-evidence); we do **not** accept
leaderboard-style claims against named external systems.

## License

MIT. See `LICENSE`.

## Status

This work documents a single instance of the gray-failure pattern in one agentic
decomposition pipeline (qwq-32b-awq decomposer + custom YAML parser, evaluated against
hybrid math/code tasks at N=9). We propose the audit battery as a reusable instrument.
**Validated once.** Apply it to your own pipeline before claiming it generalizes.
