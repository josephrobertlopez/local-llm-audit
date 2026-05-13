#!/usr/bin/env python3
"""CLI wrapper around silent_compound_failures.audit_battery.AuditBattery.

Behavior preserved from the pre-class script: writes raw.json + prints summary.
Adds --target-endpoint / --target-token / --reps flags (env vars still work as defaults).
"""
import json
import sys
import os
import argparse
from pathlib import Path
from statistics import mean, stdev

# Ensure src/ is importable when the script is run from repo root.
_REPO = Path(__file__).resolve().parent
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from silent_compound_failures.llm_adapter import (  # noqa: E402
    LLMResult,
    OpenAICompatAdapter,
    RLMHubAdapter,
)
from silent_compound_failures.schemas import TaskSuite  # noqa: E402

# Re-exported so `from audit_battery import parse_decomposition` (test_parser) still works.
from silent_compound_failures.audit_battery import (  # noqa: E402
    AuditBattery,
    DECOMPOSE_SYSTEM,
    DECOMPOSE_TEMPLATE,
    parse_decomposition,
)

__all__ = [
    "AuditBattery",
    "DECOMPOSE_SYSTEM",
    "DECOMPOSE_TEMPLATE",
    "LLMResult",
    "OpenAICompatAdapter",
    "RLMHubAdapter",
    "TaskSuite",
    "call_llm",
    "call_rlm",
    "load_config",
    "load_tasks",
    "main",
    "parse_decomposition",
]


def load_config():
    token = os.environ.get("RLM_TOKEN")
    if not token:
        raise RuntimeError("Set RLM_TOKEN env var or pass --target-token")
    hub_url = os.environ.get("RLM_HUB_URL", "http://localhost:1337")
    return token, hub_url


def load_tasks(yaml_path):
    """Legacy helper preserved for any callers. Use AuditBattery internally."""
    import yaml
    with open(yaml_path) as f:
        raw = yaml.safe_load(f)
    if isinstance(raw, list):
        raw = {"tasks": raw}
    suite = TaskSuite(**raw)
    keep = {"H-001", "H-002", "H-003"}
    return [t.model_dump() for t in suite.tasks if t.id in keep]


def call_llm(model, messages, max_tokens, timeout, token, hub_url):
    """Backwards-compatible thin wrapper around OpenAICompatAdapter.chat."""
    adapter = OpenAICompatAdapter(base_url=hub_url, token=token)
    result = adapter.chat(model, messages, max_tokens, timeout)
    if result.error and result.http_status is None:
        print(f"[ERROR] {model} request failed: {result.error}", file=sys.stderr)
    elif result.http_status and result.http_status != 200:
        print(f"[ERROR] {model} returned {result.http_status}", file=sys.stderr)
    return result


def call_rlm(prompt, timeout, token, hub_url):
    """Backwards-compatible thin wrapper around RLMHubAdapter.rlm_decompose."""
    adapter = RLMHubAdapter(base_url=hub_url, token=token)
    content, latency, trace = adapter.rlm_decompose(prompt, timeout)
    if content is None:
        print("[ERROR] RLM request failed", file=sys.stderr)
    return content, latency, (trace or {})


def _print_summary(raw_results, breakdown, overall):
    test1 = [r for r in raw_results if r.test == "qwen_decomp"]
    test2 = [r for r in raw_results if r.test == "qwq_1500_repro"]
    test3 = [r for r in raw_results if r.test == "rlm_trace_h001"]

    print("\nTEST 1 (Qwen-decomposer):")
    for task_id in ['H-001', 'H-002', 'H-003']:
        task_results = [r for r in test1 if r.task_id == task_id]
        if task_results:
            success_rate = sum(1 for r in task_results if r.parse_success) / len(task_results)
            latencies = [r.latency_s for r in task_results]
            lat_mean = mean(latencies)
            lat_std = stdev(latencies) if len(latencies) > 1 else 0
            print(f"  {task_id}: parse_success={success_rate:.1%} latency={lat_mean:.1f}±{lat_std:.1f}s")

    print("\nTEST 2 (QWQ-1500-repro):")
    for task_id in ['H-001', 'H-002', 'H-003']:
        task_results = [r for r in test2 if r.task_id == task_id]
        if task_results:
            success_rate = sum(1 for r in task_results if r.parse_success) / len(task_results)
            content_chars = mean([(r.content_chars or 0) for r in task_results])
            tok_vals = [r.completion_tokens for r in task_results if r.completion_tokens]
            comp_tokens = mean(tok_vals) if tok_vals else 0
            finish_reasons = [r.finish_reason for r in task_results]
            print(f"  {task_id}: parse_success={success_rate:.1%} content_chars={content_chars:.0f} tokens={comp_tokens:.0f}")
            print(f"           finish_reasons: {finish_reasons}")

    print("\nTEST 3 (RLM-trace-H-001):")
    if test3:
        dumps = [r.model_dump() for r in test3]
        n_subtasks_vals = [d.get('trace_n_subtasks', 0) for d in dumps]
        score_matches = [d.get('h001_score_match', False) for d in dumps]
        real_decomp = max(n_subtasks_vals) > 1 if n_subtasks_vals else False
        print(f"  n_subtasks per rep: {n_subtasks_vals}")
        print(f"  score_match: {score_matches}")
        print(f"  real_decomposition: {real_decomp}")

    print("\nVERDICT:")
    print(f"  overall: {overall}")
    print(f"  test1_fix_reliability: {breakdown.test1_fix_reliability}")
    print(f"  test2_historical_bug_proof: {breakdown.test2_historical_bug_proof}")
    print(f"  test3_trace_verification: {breakdown.test3_trace_verification}")
    print(f"  test4_statistical_significance: {breakdown.test4_statistical_significance}")


def main():
    parser = argparse.ArgumentParser(description="Audit LLM decomposition reliability")
    parser.add_argument("--tasks", required=True, help="Path to tasks YAML file")
    parser.add_argument("--out-dir", default="./audit-results", help="Output directory (default: ./audit-results)")
    parser.add_argument(
        "--target-endpoint",
        default=os.environ.get("RLM_HUB_URL", "http://localhost:1337"),
        help="LLM endpoint base URL (default: $RLM_HUB_URL or http://localhost:1337)",
    )
    parser.add_argument(
        "--target-token",
        default=os.environ.get("RLM_TOKEN"),
        help="Bearer token for the LLM endpoint (default: $RLM_TOKEN)",
    )
    parser.add_argument("--reps", type=int, default=3, help="Reps per task (default: 3)")
    args = parser.parse_args()

    if not args.target_token:
        raise RuntimeError("--target-token or $RLM_TOKEN must be set")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading tasks...")
    print(f"Endpoint: {args.target_endpoint}, reps={args.reps}\n")

    print("=" * 70)
    print("Running 4-test audit battery")
    print("=" * 70)

    battery = AuditBattery(
        target_endpoint=args.target_endpoint,
        target_token=args.target_token,
        tasks_path=args.tasks,
        reps=args.reps,
    )
    verdict = battery.run()

    out_file = out_dir / "raw.json"
    with open(out_file, "w") as f:
        json.dump([r.model_dump() for r in verdict.raw_results], f, indent=2)
    print(f"\nResults saved to {out_file}")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    _print_summary(verdict.raw_results, verdict.breakdown, verdict.overall)
    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
