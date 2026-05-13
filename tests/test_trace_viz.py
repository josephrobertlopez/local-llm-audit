from silent_compound_failures.schemas import AuditResult
from silent_compound_failures.trace_viz import trace_to_mermaid


def test_mermaid_renders_subtasks_and_backends():
    r = AuditResult(
        test="rlm_trace_h001",
        rep=0,
        latency_s=1.0,
        trace_n_subtasks=3,
        trace_subtask_intents=["code", "verification", "synthesis"],
        trace_backends=["qwen-32b"],
    )
    out = trace_to_mermaid(r, prompt_label="H-001 prompt")
    assert out.startswith("flowchart TD")
    assert '"H-001 prompt"' in out
    assert "subtask 1: code" in out
    assert "subtask 2: verification" in out
    assert "subtask 3: synthesis" in out
    assert "backend: qwen-32b" in out
    # Each subtask should connect to a backend
    assert out.count("-->") >= 6  # 3 (P→Si) + 3 (Si→Bi)


def test_mermaid_handles_no_trace():
    r = AuditResult(test="qwen_decomp", rep=0, latency_s=0.5, task_id="H-001")
    out = trace_to_mermaid(r)
    assert "flowchart TD" in out
    assert "no decomposition" in out


def test_mermaid_escapes_special_chars():
    r = AuditResult(
        test="rlm_trace_h001",
        rep=0,
        latency_s=0.5,
        trace_subtask_intents=['need "quoting"'],
        trace_backends=["b/1"],
    )
    out = trace_to_mermaid(r, prompt_label='label with "quotes"')
    # Should not produce literal " inside a "[...]" label that would break mermaid
    assert '\\"quoting\\"' in out
    assert '\\"quotes\\"' in out
