"""Mermaid flowchart generator for AuditResult trace data."""

from __future__ import annotations

import re

from .schemas import AuditResult


def _sanitize(node_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", node_id)


def _escape_label(text: str) -> str:
    return text.replace('"', '\\"').replace("\n", " ")


def trace_to_mermaid(audit_result: AuditResult, prompt_label: str = "prompt") -> str:
    """Render a single AuditResult's trace data as a mermaid flowchart.

    Top node = prompt label, children = subtask intents, leaves = backends.
    Works whether the AuditResult has flat trace_* fields (from AuditBattery
    test 3 results) or only the documented schemas.TraceData-style fields.
    """
    d = audit_result.model_dump()
    intents = d.get("trace_subtask_intents") or d.get("parsed_intents") or []
    backends = d.get("trace_backends") or []

    label = _escape_label(prompt_label)
    lines = ["flowchart TD", f'    P["{label}"]']

    if not intents:
        return "\n".join(lines + ['    P --> N["no decomposition"]'])

    subtask_ids = []
    for i, intent in enumerate(intents, start=1):
        sid = f"S{i}"
        subtask_ids.append(sid)
        lines.append(f'    {sid}["subtask {i}: {_escape_label(str(intent))}"]')
        lines.append(f"    P --> {sid}")

    if backends:
        for i, sid in enumerate(subtask_ids):
            backend = backends[i] if i < len(backends) else backends[-1]
            bid = f"B{i+1}_{_sanitize(str(backend))}"
            lines.append(f'    {bid}["backend: {_escape_label(str(backend))}"]')
            lines.append(f"    {sid} --> {bid}")

    return "\n".join(lines)
