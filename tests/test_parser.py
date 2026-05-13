import pytest
import sys
from pathlib import Path

# Add parent directory to path so we can import audit_battery
sys.path.insert(0, str(Path(__file__).parent.parent))

from audit_battery import parse_decomposition


class TestParseDecomposition:
    """Unit tests for parse_decomposition function."""

    def test_parses_valid_yaml(self):
        """Test parsing clean YAML list input."""
        yaml_input = """- prompt: Write a Python function add(a, b)
  intent: code
- prompt: Explain commutativity
  intent: reasoning_fast
"""
        parsed, n_items, intents = parse_decomposition(yaml_input)
        assert parsed is not None
        assert n_items == 2
        assert intents == ['code', 'reasoning_fast']

    def test_handles_prose_plus_yaml(self):
        """Test parsing YAML that follows prose text (the bug case)."""
        yaml_input = """Let me decompose this task into subtasks:

- prompt: First subtask
  intent: reasoning_hard
- prompt: Second subtask
  intent: verification
"""
        parsed, n_items, intents = parse_decomposition(yaml_input)
        assert parsed is not None
        assert n_items == 2
        assert intents == ['reasoning_hard', 'verification']

    def test_handles_empty_input(self):
        """Test empty string returns None, 0, []."""
        parsed, n_items, intents = parse_decomposition("")
        assert parsed is None
        assert n_items == 0
        assert intents == []

    def test_handles_malformed_yaml(self):
        """Test malformed YAML doesn't raise, returns None, 0, []."""
        yaml_input = """- prompt: foo
  bad: :
  broken: yaml: syntax:
"""
        parsed, n_items, intents = parse_decomposition(yaml_input)
        assert parsed is None
        assert n_items == 0
        assert intents == []

    def test_handles_non_list_yaml(self):
        """Test YAML that parses but isn't a list."""
        yaml_input = """key: value
another: thing
"""
        parsed, n_items, intents = parse_decomposition(yaml_input)
        assert parsed is None
        assert n_items == 0
        assert intents == []

    def test_extracts_intents(self):
        """Test that intents are extracted in order and unknown defaults work."""
        yaml_input = """- prompt: Task one
  intent: code
- prompt: Task two
- prompt: Task three
  intent: synthesis
"""
        parsed, n_items, intents = parse_decomposition(yaml_input)
        assert parsed is not None
        assert n_items == 3
        assert intents == ['code', 'unknown', 'synthesis']

    def test_yaml_without_prompt_marker(self):
        """Test YAML without the prompt: key marker."""
        yaml_input = """- name: something
  intent: code
"""
        parsed, n_items, intents = parse_decomposition(yaml_input)
        assert parsed is None
        assert n_items == 0
        assert intents == []

    def test_handles_list_with_non_dict_items(self):
        """Test YAML list containing non-dict items."""
        yaml_input = """- prompt: Valid item
  intent: code
- simple string item
- prompt: Another valid
  intent: reasoning_fast
"""
        parsed, n_items, intents = parse_decomposition(yaml_input)
        assert parsed is not None
        assert intents == ['code', 'reasoning_fast']

    def test_multiple_intent_categories(self):
        """Test all valid intent categories."""
        yaml_input = """- prompt: One
  intent: code
- prompt: Two
  intent: reasoning_hard
- prompt: Three
  intent: reasoning_fast
- prompt: Four
  intent: verification
- prompt: Five
  intent: synthesis
"""
        parsed, n_items, intents = parse_decomposition(yaml_input)
        assert parsed is not None
        assert n_items == 5
        assert intents == ['code', 'reasoning_hard', 'reasoning_fast', 'verification', 'synthesis']

    def test_large_yaml_input(self):
        """Test parsing larger decomposition."""
        yaml_input = "\n".join([
            f"- prompt: Task {i}"
            f"\n  intent: {'code' if i % 2 == 0 else 'reasoning_fast'}"
            for i in range(10)
        ])
        parsed, n_items, intents = parse_decomposition(yaml_input)
        assert parsed is not None
        assert n_items == 10
        assert len(intents) == 10
