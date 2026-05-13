# INVALIDATED — prior measurements built on broken decomposer

The following measurement files were produced while the decomposer was silently failing. They are preserved as artifacts but should not be cited as evidence:

```
2026-05-12_rlm-hybrid/
  arm_B_rlm_hub__H-001.txt
  arm_B_rlm_hub__H-002.txt
  arm_B_rlm_hub__H-003.txt
  depth2_trace__H-003.txt
  depth2_trace__H-004.txt
  free-results.json (arm_B portion)
  depth2-validation-results.json
  ablation-6k-results.json

2026-05-13_rlm-endpoint/
  iter1-results.json
  iter2-results.json
  iter2-summary.md
  iter2-http__H-001.txt
  iter2-http__H-002.txt
  iter2-http__H-003.txt
```

## What was broken

Compound bug — both required to produce the singleton-fallback artifact:

1. **qwq decomposer empty-output (stochastic):** qwq is a thinking model. With `max_tokens=1500`, qwq exhausted its budget on internal `<think>` reasoning ~33-67% of the time, producing 0 chars of post-think output. Verified empirically 2026-05-12: 5/9 parse success across H-001/002/003 at N=3 reps each.

2. **Parser failure on prose+yaml (deterministic, 100%):** Even when qwq did emit YAML, it was preceded by thinking-prose. `_parse_decomposition` called `yaml.safe_load` on the whole response. `safe_load` fails on prose followed by YAML. 100% failure rate on this input pattern. Verified empirically via synthetic reproduction.

Combined effect: every prior "RLM" call fell through to:
```python
return [Subtask(prompt=task, category="reasoning_fast")]
```
which means: 1 wasted qwq call + 1 specialist call with `reasoning_fast` system prompt. Not RLM.

## Affected claims (now invalid)

- "Arm-B RLM beats single-pass 3/3 vs 1/3" (free-results.json 2026-05-12) — the RLM arm was actually single qwq with reasoning_fast system prompt.
- "Depth-2 dormant: decomposer rejected recurse=true" (depth2-validation-results.json) — decomposer produced 0 chars; never given a real chance to evaluate recurse.
- "/v1/rlm iter-2 SHIP as opt-in" verdict (iter2-summary.md) — comparison was singleton-vs-singleton; both arms broken.
- "Iter-1 → iter-2 latency reduction 25-32% endpoint improvement" — the reduction is real but reflects "we dropped one wasted call" not "we improved RLM."
- "RLM is architectural win at $0/token" (ablation-6k-results.json) — was comparing broken-RLM vs single-pass; the architectural framing was wrong.

## Fix applied 2026-05-12

1. `src/orchestrator/decomposer.py` `_parse_decomposition` patched: tries multi-candidate extraction (fenced YAML; from first `^- prompt:` to end; whole text) before declaring parse failure.
2. `src/hub.py` `/v1/rlm` `decomposer_call`: switched from `qwq-32b-awq` (thinking, slow, structured-output-unreliable) to `qwen2.5-32b-instruct-awq` (non-thinking, ~15s vs 240s, structured-output-reliable).

Both fixes verified: 9/9 parse success across H-001/002/003 with N=3 reps after fix (audit battery test 1, 2026-05-12).

## Honest measurement after fix

See `2026-05-12_rlm-honest-results/` for:
- N=3 per arm × 3 tasks (matched-pair design)
- Per-call trace verification (every arm_C call confirmed real multi-subtask decomposition)
- Statistical analysis (McNemar's exact, Fisher's exact, both underpowered at N=3)
- Aggregate: arm_A 8/9 vs arm_C 6/9. Direction: single-pass ≥ RLM on every task. Not significant; honest only as directional/exploratory finding.
