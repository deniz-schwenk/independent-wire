"""Test Agent._parse_json repair logic (QF-05)."""

from src.agent import Agent


def test_valid_json():
    result = Agent._parse_json('{"key": "value"}')
    assert result == {"key": "value"}


def test_valid_json_array():
    result = Agent._parse_json('[1, 2, 3]')
    assert result == [1, 2, 3]


def test_markdown_fences():
    text = '```json\n{"key": "value"}\n```'
    result = Agent._parse_json(text)
    assert result == {"key": "value"}


def test_trailing_commas():
    text = '{"a": 1, "b": [2, 3,],}'
    result = Agent._parse_json(text)
    assert result == {"a": 1, "b": [2, 3]}


def test_prose_before_after():
    text = 'Here is the result:\n{"key": "value"}\nDone.'
    result = Agent._parse_json(text)
    assert result == {"key": "value"}


def test_truncated_missing_brace():
    text = '{"a": {"b": 1}'
    result = Agent._parse_json(text)
    assert result == {"a": {"b": 1}}


def test_truncated_missing_bracket_and_brace():
    text = '{"a": [1, 2, 3'
    result = Agent._parse_json(text)
    assert result == {"a": [1, 2, 3]}


def test_completely_invalid():
    result = Agent._parse_json("not json at all")
    assert result is None
