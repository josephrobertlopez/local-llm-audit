#!/usr/bin/env python3
import json
import sys
import re
import os
import argparse
from pathlib import Path
from statistics import mean, stdev

import yaml

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

DECOMPOSE_SYSTEM = "You decompose a complex task into 2-4 simpler subtasks, each tagged with an intent category. Allowed intents: code, reasoning_hard, reasoning_fast, verification, synthesis. Output a YAML list with fields prompt (the subtask text) and intent (the category). Do not execute the subtasks; only decompose."

DECOMPOSE_TEMPLATE = """TASK TO DECOMPOSE:
{task}

Decompose this into 2-4 simpler subtasks. Output a YAML list. Each item must have:
  - `prompt`: the subtask text the specialist will execute
  - `intent`: one of [code, reasoning_hard, reasoning_fast, verification, synthesis]
  - `recurse` (optional, default false)

Do NOT solve the subtasks. Output ONLY the YAML list, no preamble.

Example:
- prompt: Write a Python function add(a, b)
  intent: code
- prompt: Explain commutativity
  intent: reasoning_fast
"""


def load_config():
    token = os.environ.get("RLM_TOKEN")
    if not token:
        raise RuntimeError("Set RLM_TOKEN env var")
    hub_url = os.environ.get("RLM_HUB_URL", "http://localhost:1337")
    return token, hub_url


def load_tasks(yaml_path):
    with open(yaml_path) as f:
        tasks_data = yaml.safe_load(f)
    if isinstance(tasks_data, dict) and 'tasks' in tasks_data:
        tasks_data = tasks_data['tasks']
    return [t for t in tasks_data if t.get('id') in ['H-001', 'H-002', 'H-003']]


def parse_decomposition(content):
    try:
        match = re.search(r'(?m)^-\s+prompt:', content)
        if not match:
            return None, 0, []
        yaml_str = content[match.start():]
        parsed = yaml.safe_load(yaml_str)
        if not isinstance(parsed, list):
            return parsed, len(parsed) if parsed else 0, []
        intents = [item.get('intent', 'unknown') for item in parsed if isinstance(item, dict)]
        return parsed, len(parsed), intents
    except Exception:
        return None, 0, []


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
    """Backwards-compatible thin wrapper around RLMHubAdapter.rlm_decompose.

    Returns (content, latency, trace_dict_or_empty) to match prior signature.
    """
    adapter = RLMHubAdapter(base_url=hub_url, token=token)
    content, latency, trace = adapter.rlm_decompose(prompt, timeout)
    if content is None:
        # preserve prior behavior of logging hub failures
        print(f"[ERROR] RLM request failed", file=sys.stderr)
    return content, latency, (trace or {})


def main():
    parser = argparse.ArgumentParser(description="Audit LLM decomposition reliability")
    parser.add_argument("--tasks", required=True, help="Path to tasks YAML file")
    parser.add_argument("--out-dir", default="./audit-results", help="Output directory (default: ./audit-results)")
    args = parser.parse_args()

    token, hub_url = load_config()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    REPS = 3

    print("Loading tasks...")
    tasks = load_tasks(args.tasks)
    print(f"Found {len(tasks)} target tasks: {[t['id'] for t in tasks]}\n")

    print("=" * 70)
    print("TEST 1: Qwen-decomposer reliability (9 calls)")
    print("=" * 70)
    for task in tasks:
        for rep in range(REPS):
            result_obj = call_llm(
                "qwen2.5-32b-instruct-awq",
                [
                    {"role": "system", "content": DECOMPOSE_SYSTEM},
                    {"role": "user", "content": DECOMPOSE_TEMPLATE.format(task=task['description'])}
                ],
                2000,
                120,
                token,
                hub_url
            )
            content = result_obj.content
            latency = result_obj.latency_s
            if content:
                parsed, n_subtasks, intents = parse_decomposition(content)
                parse_success = parsed is not None
            else:
                parsed, n_subtasks, intents, parse_success = None, 0, [], False

            result = {
                "test": "qwen_decomp",
                "task_id": task['id'],
                "rep": rep,
                "latency_s": latency,
                "content_chars": len(content) if content else 0,
                "parsed_n_subtasks": n_subtasks,
                "parsed_intents": intents,
                "parse_success": parse_success
            }
            results.append(result)
            status = "PASS" if parse_success else "FAIL"
            print(f"[qwen_decomp] {task['id']} rep{rep}: parse={status} subtasks={n_subtasks} latency={latency:.1f}s")

    print("\n" + "=" * 70)
    print("TEST 2: Prior-bug historical proof (9 calls, qwq at 1500 tokens)")
    print("=" * 70)
    for task in tasks:
        for rep in range(REPS):
            result_obj = call_llm(
                "qwq-32b-awq",
                [
                    {"role": "system", "content": DECOMPOSE_SYSTEM},
                    {"role": "user", "content": DECOMPOSE_TEMPLATE.format(task=task['description'])}
                ],
                1500,
                300,
                token,
                hub_url
            )
            content = result_obj.content
            latency = result_obj.latency_s
            comp_tokens = result_obj.completion_tokens
            finish = result_obj.finish_reason
            if content:
                parsed, n_subtasks, intents = parse_decomposition(content)
                parse_success = parsed is not None
            else:
                parsed, n_subtasks, intents, parse_success = None, 0, [], False

            result = {
                "test": "qwq_1500_repro",
                "task_id": task['id'],
                "rep": rep,
                "latency_s": latency,
                "content_chars": len(content) if content else 0,
                "completion_tokens": comp_tokens if comp_tokens else 0,
                "parsed_n_subtasks": n_subtasks,
                "parse_success": parse_success,
                "finish_reason": finish
            }
            results.append(result)
            status = "PASS" if parse_success else "FAIL"
            print(f"[qwq_1500_repro] {task['id']} rep{rep}: parse={status} subtasks={n_subtasks} latency={latency:.1f}s tokens={comp_tokens}")

    print("\n" + "=" * 70)
    print("TEST 3: Per-call trace re-verification on H-001 (3 calls)")
    print("=" * 70)
    h001 = [t for t in tasks if t['id'] == 'H-001'][0] if tasks else None
    if h001:
        for rep in range(REPS):
            content, latency, trace = call_rlm(h001['description'], 900, token, hub_url)
            if content:
                parsed, n_subtasks, intents = parse_decomposition(content)
                trace_subtasks = trace.get('n_subtasks', 0) if isinstance(trace, dict) else 0
                trace_intents = trace.get('intents', []) if isinstance(trace, dict) else []
                trace_backends = trace.get('backends', []) if isinstance(trace, dict) else []
                success_regex = h001.get('success_check_regex', '')
                h001_score = 1 if success_regex and re.search(success_regex, content) else 0
            else:
                parsed, n_subtasks, intents, trace_subtasks, trace_intents, trace_backends, h001_score = None, 0, [], 0, [], [], 0

            result = {
                "test": "rlm_trace_h001",
                "rep": rep,
                "latency_s": latency,
                "content_chars": len(content) if content else 0,
                "trace_n_subtasks": trace_subtasks,
                "trace_subtask_intents": trace_intents,
                "trace_backends": trace_backends,
                "h001_score_match": bool(h001_score)
            }
            results.append(result)
            print(f"[rlm_trace_h001] rep{rep}: subtasks={trace_subtasks} latency={latency:.1f}s score_match={bool(h001_score)}")

    out_file = out_dir / "raw.json"
    with open(out_file, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {out_file}")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    test1_results = [r for r in results if r['test'] == 'qwen_decomp']
    test2_results = [r for r in results if r['test'] == 'qwq_1500_repro']
    test3_results = [r for r in results if r['test'] == 'rlm_trace_h001']

    print("\nTEST 1 (Qwen-decomposer):")
    for task_id in ['H-001', 'H-002', 'H-003']:
        task_results = [r for r in test1_results if r['task_id'] == task_id]
        if task_results:
            success_rate = sum(1 for r in task_results if r['parse_success']) / len(task_results)
            latencies = [r['latency_s'] for r in task_results]
            lat_mean = mean(latencies)
            lat_std = stdev(latencies) if len(latencies) > 1 else 0
            print(f"  {task_id}: parse_success={success_rate:.1%} latency={lat_mean:.1f}±{lat_std:.1f}s")

    print("\nTEST 2 (QWQ-1500-repro):")
    for task_id in ['H-001', 'H-002', 'H-003']:
        task_results = [r for r in test2_results if r['task_id'] == task_id]
        if task_results:
            success_rate = sum(1 for r in task_results if r['parse_success']) / len(task_results)
            content_chars = mean([r['content_chars'] for r in task_results])
            comp_tokens = mean([r['completion_tokens'] for r in task_results if r['completion_tokens']])
            finish_reasons = [r['finish_reason'] for r in task_results]
            print(f"  {task_id}: parse_success={success_rate:.1%} content_chars={content_chars:.0f} tokens={comp_tokens:.0f}")
            print(f"           finish_reasons: {finish_reasons}")

    print("\nTEST 3 (RLM-trace-H-001):")
    if test3_results:
        n_subtasks_vals = [r['trace_n_subtasks'] for r in test3_results]
        score_matches = [r['h001_score_match'] for r in test3_results]
        real_decomp = max(n_subtasks_vals) > 1 if n_subtasks_vals else False
        print(f"  n_subtasks per rep: {n_subtasks_vals}")
        print(f"  score_match: {score_matches}")
        print(f"  real_decomposition: {real_decomp}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
