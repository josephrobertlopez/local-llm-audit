"""Minimal synthetic reproduction of the parser bug.

Run: python parser_failure_synthetic.py

Demonstrates that the OLD _parse_decomposition implementation (yaml.safe_load
on prose+yaml input) returns 0 subtasks on a realistic thinking-model
decomposer output.
"""

import yaml
import re


# OLD (broken) parser — verbatim from src/orchestrator/decomposer.py
# prior to the 2026-05-12 fix.
def OLD_parse_decomposition(text):
    m = re.search(r"```(?:yaml|yml)?\n?(.*?)```", text, re.DOTALL)
    yaml_text = m.group(1).strip() if m else text.strip()
    try:
        parsed = yaml.safe_load(yaml_text)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    except yaml.YAMLError:
        pass
    return []


# NEW (patched) parser — multi-candidate extraction
def NEW_parse_decomposition(text):
    candidates = []
    m = re.search(r"```(?:yaml|yml)?\n?(.*?)```", text, re.DOTALL)
    if m:
        candidates.append(m.group(1).strip())
    m2 = re.search(r"(?m)^-\s+prompt:", text)
    if m2:
        candidates.append(text[m2.start():].strip())
    candidates.append(text.strip())

    for yaml_text in candidates:
        try:
            parsed = yaml.safe_load(yaml_text)
        except yaml.YAMLError:
            continue
        if isinstance(parsed, list):
            out = [item for item in parsed if isinstance(item, dict)]
            if out:
                return out
    return []


# Realistic qwq-style thinking-model output: prose preamble then YAML
SYNTHETIC_QWQ_OUTPUT = """Okay, let's tackle this problem. The user wants me to decompose the task of writing the Python function meet_time into simpler subtasks.

First, the problem involves two trains moving towards each other. Train A starts at 9:00 AM going east at a_speed mph. Train B starts delay hours later from a position gap miles east of A, going west at b_speed mph. We need to find the time they meet and return it in HH:MM format.

Hmm, so breaking this down, maybe I can split it into parts:

- prompt: Derive the meeting time formula given a_speed, b_speed, gap, delay
  intent: reasoning_hard
- prompt: Write a Python function meet_time(a_speed, b_speed, gap, delay)
  intent: code
- prompt: Call meet_time(60, 40, 200, 1) and report result as HH:MM
  intent: verification
"""


def main():
    print("Testing OLD parser on prose+yaml input...")
    old_result = OLD_parse_decomposition(SYNTHETIC_QWQ_OUTPUT)
    print(f"  OLD parsed {len(old_result)} subtasks")
    print(f"  --> falls back to singleton (intent=reasoning_fast) every time\n")

    print("Testing NEW parser on the same input...")
    new_result = NEW_parse_decomposition(SYNTHETIC_QWQ_OUTPUT)
    print(f"  NEW parsed {len(new_result)} subtasks:")
    for item in new_result:
        print(f"    intent={item.get('intent')}  prompt={item.get('prompt', '')[:60]}")

    assert len(old_result) == 0, "OLD parser unexpectedly succeeded"
    assert len(new_result) == 3, "NEW parser failed to extract 3 subtasks"
    print("\nPASS: OLD=0 subtasks (silent singleton fallback), NEW=3 subtasks (real decomposition)")


if __name__ == "__main__":
    main()
