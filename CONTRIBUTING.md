# Contributing to silent-compound-failures

This repo is methodology, not a benchmark. Contributions should keep that shape.
See `methodology.md` and `README.md` for the broader framing.

## What this repo IS

- A reusable audit harness for finding silent compound failures in LLM
  decomposition pipelines.
- A small set of tasks (`tasks_example.yaml`) designed so that single-pass
  prompts and decomposed pipelines diverge in detectable ways.
- A statistical test battery (`AuditBattery`) that reports a structured
  verdict you can drop into a methodology section, not a leaderboard cell.

## What this repo IS NOT

- A benchmark. We do not maintain a ranking of "best" pipelines.
- A claim that any single tool beats any other. Anti-attribution: write
  results as "pipeline showed pattern X under audit," not "pipeline beat
  baseline by N%."
- A black-box scorer. Every verdict has a breakdown; reviewers can inspect
  the raw_results before accepting any conclusion.

## How to add a new task type to a tasks YAML

Tasks live in YAML and validate against `silent_compound_failures.schemas.TaskSuite`:

```yaml
tasks:
  - id: H-005                      # unique short id
    name: short_descriptive_name   # optional, helps log scanning
    description: |
      Multi-line problem statement. Include any constraints, expected
      outputs, and verification criteria inline so the task is reproducible.
    expected_decomposition:        # optional — for human review of "what good looks like"
      - prompt: First subtask text
        intent: code               # one of: code | reasoning_hard | reasoning_fast | verification | synthesis
      - prompt: Second subtask
        intent: verification
    success_check_regex: '\bexpected_answer\b'   # regex run on the assembled output
```

Tasks should be designed so that a naive single-pass prompt is likely to fail
but a properly decomposed multi-step pipeline succeeds. If both succeed
trivially, the task does not discriminate and adds noise.

## How to add a new LLM adapter

Adapters live in `src/silent_compound_failures/llm_adapter.py` and follow the
`LLMAdapter` Protocol:

```python
class LLMAdapter(Protocol):
    def chat(self, model: str, messages: list[dict], max_tokens: int, timeout: int) -> LLMResult: ...
    def rlm_decompose(self, prompt: str, timeout: int) -> tuple[Optional[str], float, Optional[dict]]: ...
```

To add support for a new provider:

1. Subclass nothing — just write a class that implements both methods. (`Protocol`
   does structural matching.)
2. Make sure `chat()` returns a `LLMResult` with `latency_s`, `completion_tokens`,
   and either `content` or `error` populated.
3. Make sure `rlm_decompose()` returns `(content, latency_s, trace_or_None)`.
   If your provider has no trace endpoint, return `None` for the trace and the
   battery's test 3 will surface `trace_verification: fail` (a feature, not a bug —
   it tells reviewers your pipeline cannot be audited for real decomposition).
4. Add a unit test under `tests/test_llm_adapter.py` using `unittest.mock` to
   patch `requests.post`. Do not hit the network in tests.

## How to submit an audit result against your own pipeline

If you run the audit against your own deployment and want to share results:

1. Place a directory under `audits/<your-org>/` (no PR review of your raw
   evidence — that's your audit, not ours).
2. Include the `raw.json` produced by `audit_battery.py`, plus the YAML tasks
   file you used (so reviewers can reproduce).
3. Include a one-page summary using the verdict structure: overall, breakdown
   per test, sample sizes, and any caveats. Do NOT claim your pipeline "wins"
   or "beats" anything — describe what pattern the audit surfaced.
4. Open a PR that adds only the directory. Do not modify the harness itself
   in the same PR — separate concerns.

We will merge audits that:
- include the raw evidence (not just the summary)
- describe pattern in the verdict's vocabulary (pass/fail/confirmed/etc.)
- avoid comparative claims against named external systems

We will not merge audits that:
- omit raw_results
- frame results as a leaderboard entry
- attack a named external system without prior consent

## Diagnose-before-fix discipline

When you find a failure in your pipeline via this audit:

1. Reproduce it with the smallest possible task set first. The audit's
   `--task-ids` flag (on `rerun_arm.py`) and `--reps` flag (on
   `audit_battery.py`) help here.
2. Inspect the raw `AuditResult` for the failing test — not just the
   breakdown. The breakdown is a summary; the raw entries are the evidence.
3. Form a hypothesis BEFORE patching. Write it down.
4. Patch the minimum to test the hypothesis. Re-run the audit.
5. Only after the audit confirms the fix should you generalize to other
   tasks or change the harness.

Resist the temptation to "fix" the audit when the audit surfaces something
inconvenient. The audit is right unless you can show, with evidence, that
its mechanism is wrong.

## Running the test suite

```bash
pip install -r requirements.txt
pip install ruff mypy types-PyYAML types-requests
pytest tests/ -v
ruff check .
mypy src/ --ignore-missing-imports
```

CI runs on Python 3.11 and 3.12; please run locally on at least 3.11 before
opening a PR. The integration test (`tests/test_audit_battery_integration.py`)
must continue to surface `bug-confirmed` under the canned-mocks pattern — it
is our regression net for dead-code wiring.

## Style

- No emojis in code, tests, or docs unless explicitly requested.
- No comments that restate the code.
- No "improved" or "fixed" suffixes on function names — git history records changes.
- One change per PR. Refactors and feature adds go in separate PRs.
