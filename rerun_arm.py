#!/usr/bin/env python3
import sys
import json
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

from silent_compound_failures.llm_adapter import RLMHubAdapter  # noqa: E402
from silent_compound_failures.schemas import RunResult, TaskAggregate, TaskSuite  # noqa: E402


def load_config():
    token = os.environ.get("RLM_TOKEN")
    if not token:
        raise RuntimeError("Set RLM_TOKEN env var")
    hub_url = os.environ.get("RLM_HUB_URL", "http://localhost:1337")
    return token, hub_url


def main():
    parser = argparse.ArgumentParser(description="Rerun RLM tasks and verify decomposition")
    parser.add_argument("--tasks", required=True, help="Path to tasks YAML file")
    parser.add_argument("--out-dir", default="./rerun-results", help="Output directory (default: ./rerun-results)")
    parser.add_argument("--task-ids", default="H-001,H-002,H-003", help="Comma-separated task IDs to run (default: H-001,H-002,H-003)")
    args = parser.parse_args()

    token, hub_url = load_config()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(args.tasks) as f:
        raw = yaml.safe_load(f)
    suite = TaskSuite(**raw)
    tasks = {t.id: t.model_dump() for t in suite.tasks}
    task_ids = args.task_ids.split(",")
    results = []

    REPS = 3
    TIMEOUT = 900

    adapter = RLMHubAdapter(base_url=hub_url, token=token)

    for task_id in task_ids:
        if task_id not in tasks:
            print(f"[{task_id}] SKIP: not in yaml")
            continue

        task = tasks[task_id]
        description = task["description"]
        success_regex = task.get("success_check_regex", "")

        for rep in range(REPS):
            content, latency_s, trace = adapter.rlm_decompose(description, TIMEOUT)
            if content is None:
                print(f"[{task_id}] rep{rep}: hub call failed")
                results.append(
                    RunResult(
                        task_id=task_id,
                        rep=rep,
                        latency_s=latency_s,
                        score=0.0,
                        content_chars=0,
                        trace_n_subtasks=0,
                        trace_subtask_intents=[],
                        trace_backends=[],
                        real_decomposition=False,
                        http_status=0,
                    ).model_dump()
                )
                continue

            trace = trace or {}
            n_subtasks = trace.get("n_subtasks", 0)
            subtask_intents = trace.get("subtask_intents", [])
            backends = trace.get("backends", [])

            score = 1.0 if success_regex and re.search(success_regex, content) else 0.0
            real_decomp = n_subtasks > 1

            (out_dir / f"arm_clean__{task_id}__rep{rep}.txt").write_text(content)

            results.append(
                RunResult(
                    task_id=task_id,
                    rep=rep,
                    latency_s=latency_s,
                    score=score,
                    content_chars=len(content),
                    trace_n_subtasks=n_subtasks,
                    trace_subtask_intents=subtask_intents,
                    trace_backends=backends,
                    real_decomposition=real_decomp,
                    http_status=200,
                ).model_dump()
            )

            print(
                f"[{task_id}] rep{rep}: subtasks={n_subtasks} real={real_decomp} score={score} latency={latency_s:.1f}s"
            )

    (out_dir / "raw.json").write_text(json.dumps(results, indent=2))

    agg = {}
    for task_id in task_ids:
        task_results = [r for r in results if r["task_id"] == task_id]
        if not task_results:
            continue

        n_real = sum(1 for r in task_results if r["real_decomposition"])
        n_correct = sum(1 for r in task_results if r["score"] == 1.0)
        latencies = [r["latency_s"] for r in task_results if r["http_status"] == 200]

        agg[task_id] = TaskAggregate(
            n_real_decomp=n_real,
            n_correct=n_correct,
            mean_latency_s=mean(latencies) if latencies else 0.0,
            stddev_latency_s=stdev(latencies) if len(latencies) > 1 else 0.0,
        ).model_dump()

    (out_dir / "aggregate.json").write_text(json.dumps(agg, indent=2))

    print("\n=== SUMMARY ===")
    print("task_id | n_real/3 | n_correct/3 | mean_lat(s) | stddev")
    print("-" * 60)
    for task_id in task_ids:
        if task_id not in agg:
            print(f"{task_id:6} | SKIP")
            continue
        a = agg[task_id]
        print(
            f"{task_id:6} | {a['n_real_decomp']:7}/3 | {a['n_correct']:11}/3 | {a['mean_latency_s']:11.2f} | {a['stddev_latency_s']:6.2f}"
        )


if __name__ == "__main__":
    main()
