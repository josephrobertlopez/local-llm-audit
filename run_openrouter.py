#!/usr/bin/env python3
"""Run the full 4-test audit battery using OpenRouter for compute.

Tests 1 & 2 hit OpenRouter's /v1/chat/completions directly.
Test 3 hits a local rlm-hub instance (localhost:8000/v1/rlm) which
routes its orchestrator calls through OpenRouter via $KRONOS_HUB_URL.

Usage:
    # Start the hub first (in another terminal):
    #   cd ~/code/rlm-hub
    #   KRONOS_HUB_URL=https://openrouter.ai/api \
    #   LLAMA_API_KEY=<token> \
    #   HUB_MODEL_QWEN=qwen/qwen-2.5-32b-instruct \
    #   HUB_MODEL_QWQ=qwen/qwq-32b \
    #   python3 -m uvicorn src.hub:app --host 0.0.0.0 --port 8000

    OR_TOKEN=<token> python3 run_openrouter.py [--reps N] [--hub-url URL]
"""
import argparse
import json
import os
import sys
from pathlib import Path
from statistics import mean, stdev

# Set OpenRouter model IDs BEFORE importing audit_battery so module-level constants resolve correctly.
os.environ.setdefault("AUDIT_TEST1_MODEL", "qwen/qwen-2.5-72b-instruct")
os.environ.setdefault("AUDIT_TEST2_MODEL", "qwen/qwq-32b-preview")

_REPO = Path(__file__).resolve().parent
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from silent_compound_failures.llm_adapter import OpenAICompatAdapter, RLMHubAdapter
from silent_compound_failures.audit_battery import AuditBattery, TEST1_MODEL, TEST2_MODEL

OPENROUTER_BASE = "https://openrouter.ai/api"
OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://github.com/josephrobertlopez/local-llm-audit",
    "X-Title": "local-llm-audit",
}


class OpenRouterAdapter(OpenAICompatAdapter):
    """OpenAICompatAdapter with OpenRouter-required extra headers."""

    def __init__(self, token: str):
        super().__init__(base_url=OPENROUTER_BASE, token=token)
        self._extra_headers = OPENROUTER_HEADERS

    def chat(self, model, messages, max_tokens, timeout):
        import requests, time as _time
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": self.temperature,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
            **self._extra_headers,
        }
        start = _time.monotonic()
        try:
            resp = requests.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=timeout,
            )
        except Exception as exc:
            print(f"[OR EXC] {type(exc).__name__}: {exc}", file=sys.stderr)
            from silent_compound_failures.llm_adapter import LLMResult
            return LLMResult(None, _time.monotonic() - start, 0, None, None, str(exc))

        latency = _time.monotonic() - start
        from silent_compound_failures.llm_adapter import LLMResult
        if resp.status_code != 200:
            print(f"[OR ERR] HTTP {resp.status_code}: {resp.text[:300]}", file=sys.stderr)
            return LLMResult(None, latency, 0, None, resp.status_code, f"HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            completion_tokens = data.get("usage", {}).get("completion_tokens", 0) or 0
            finish_reason = data["choices"][0].get("finish_reason")
        except Exception as exc:
            return LLMResult(None, latency, 0, None, resp.status_code, f"parse error: {exc}")
        return LLMResult(content, latency, completion_tokens, finish_reason, 200, None)


def _print_summary(verdict):
    raw = verdict.raw_results
    b = verdict.breakdown
    test1 = [r for r in raw if r.test == "qwen_decomp"]
    test2 = [r for r in raw if r.test == "qwq_1500_repro"]
    test3 = [r for r in raw if r.test == "rlm_trace_h001"]

    print("\nTEST 1 (Qwen-decomposer via OpenRouter):")
    for tid in ["H-001", "H-002", "H-003"]:
        rows = [r for r in test1 if r.task_id == tid]
        if rows:
            rate = sum(1 for r in rows if r.parse_success) / len(rows)
            lats = [r.latency_s for r in rows]
            print(f"  {tid}: parse={rate:.0%}  lat={mean(lats):.1f}±{stdev(lats) if len(lats)>1 else 0:.1f}s")

    print("\nTEST 2 (QWQ-repro via OpenRouter):")
    for tid in ["H-001", "H-002", "H-003"]:
        rows = [r for r in test2 if r.task_id == tid]
        if rows:
            rate = sum(1 for r in rows if r.parse_success) / len(rows)
            toks = [r.completion_tokens for r in rows if r.completion_tokens]
            tok_mean = mean(toks) if toks else 0.0
            print(f"  {tid}: parse={rate:.0%}  tokens={tok_mean:.0f}  finish={[r.finish_reason for r in rows]}")

    print("\nTEST 3 (RLM trace via local hub → OpenRouter):")
    if test3:
        dumps = [r.model_dump() for r in test3]
        nsubs = [d.get("trace_n_subtasks", 0) for d in dumps]
        print(f"  n_subtasks per rep: {nsubs}")
        print(f"  real_decomposition: {max(nsubs) > 1 if nsubs else False}")
    else:
        print("  SKIPPED (hub not running — test3_trace_verification=fail is expected)")

    print(f"\nVERDICT: {verdict.overall}")
    print(f"  test1_fix_reliability:      {b.test1_fix_reliability}")
    print(f"  test2_historical_bug_proof: {b.test2_historical_bug_proof}")
    print(f"  test3_trace_verification:   {b.test3_trace_verification}")
    print(f"  test4_statistical_significance: {b.test4_statistical_significance}")
    if verdict.fisher_p is not None:
        print(f"  fisher_p: {verdict.fisher_p:.4f}")


def main():
    parser = argparse.ArgumentParser(description="Audit battery via OpenRouter")
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--hub-url", default="http://localhost:8000",
                        help="Local rlm-hub URL for test3 (default: http://localhost:8000)")
    parser.add_argument("--hub-token", default="test",
                        help="Auth token for local hub (default: 'test')")
    parser.add_argument("--tasks", default="tasks_example.yaml")
    parser.add_argument("--out-dir", default="./audit-openrouter")
    args = parser.parse_args()

    token = os.environ.get("OR_TOKEN") or os.environ.get("OPENROUTER_TOKEN")
    if not token:
        token_path = Path("~/.claude/secrets/openrouter-token").expanduser()
        if token_path.exists():
            token = token_path.read_text().strip()
    if not token:
        print("ERROR: set OR_TOKEN env var or place key at ~/.claude/secrets/openrouter-token", file=sys.stderr)
        sys.exit(1)

    or_model_qwen = os.environ.get("AUDIT_TEST1_MODEL", TEST1_MODEL)
    or_model_qwq = os.environ.get("AUDIT_TEST2_MODEL", TEST2_MODEL)
    # Discover available models before running
    try:
        import requests as _r
        _resp = _r.get(f"{OPENROUTER_BASE}/v1/models",
                       headers={"Authorization": f"Bearer {token}"}, timeout=10)
        if _resp.status_code == 200:
            _ids = [m["id"] for m in _resp.json().get("data", [])
                    if any(k in m["id"].lower() for k in ("qwen", "qwq", "deepseek-r"))]
            _ids.sort()
            print(f"Available Qwen/QwQ models on OpenRouter: {_ids[:20]}")
    except Exception as _e:
        print(f"Model list fetch failed: {_e}")

    print(f"OpenRouter endpoint: {OPENROUTER_BASE}")
    print(f"  test1 model: {or_model_qwen}")
    print(f"  test2 model: {or_model_qwq}")
    print(f"  test3 rlm hub: {args.hub_url} (trace=None if hub not running)")

    chat_adapter = OpenRouterAdapter(token=token)

    # Try to reach local hub for test3; fall back to OpenAICompatAdapter (no trace)
    try:
        import requests as _req
        resp = _req.get(f"{args.hub_url}/", timeout=3)
        hub_alive = resp.status_code == 200
    except Exception:
        hub_alive = False

    if hub_alive:
        print(f"  hub status: ALIVE at {args.hub_url}")
        rlm_adapter = RLMHubAdapter(base_url=args.hub_url, token=args.hub_token)
    else:
        print(f"  hub status: NOT RUNNING — test3 will show trace=None (expected)")
        rlm_adapter = OpenRouterAdapter(token=token)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 60)
    print("Running audit battery")
    print("=" * 60)

    battery = AuditBattery(
        target_endpoint=OPENROUTER_BASE,
        target_token=token,
        tasks_path=args.tasks,
        reps=args.reps,
        adapter=chat_adapter,
        rlm_adapter=rlm_adapter,
    )
    verdict = battery.run()

    out_file = out_dir / "raw.json"
    with open(out_file, "w") as f:
        json.dump([r.model_dump() for r in verdict.raw_results], f, indent=2)
    print(f"\nResults → {out_file}")

    print("\n" + "=" * 60)
    _print_summary(verdict)
    print("=" * 60)


if __name__ == "__main__":
    main()
