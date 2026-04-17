"""Tests for pipeline bugfixes: null sanitizing + rejected topic filter."""

from src.pipeline import _sanitize_null_strings


class TestSanitizeNullStrings:
    def test_string_null_becomes_none(self):
        assert _sanitize_null_strings("null") is None

    def test_string_none_becomes_none(self):
        assert _sanitize_null_strings("None") is None

    def test_string_na_becomes_none(self):
        assert _sanitize_null_strings("N/A") is None

    def test_empty_string_becomes_none(self):
        assert _sanitize_null_strings("") is None

    def test_real_string_preserved(self):
        assert _sanitize_null_strings("Hello world") == "Hello world"

    def test_none_preserved(self):
        assert _sanitize_null_strings(None) is None

    def test_nested_dict(self):
        data = {
            "actor": "Pope Leo XIV",
            "position_quote": "null",
            "region": "Vatican City",
        }
        result = _sanitize_null_strings(data)
        assert result["actor"] == "Pope Leo XIV"
        assert result["position_quote"] is None
        assert result["region"] == "Vatican City"

    def test_nested_list_of_dicts(self):
        data = [
            {"quote": "null", "name": "Alice"},
            {"quote": "A real quote", "name": "Bob"},
            {"quote": "N/A", "name": "Carol"},
        ]
        result = _sanitize_null_strings(data)
        assert result[0]["quote"] is None
        assert result[1]["quote"] == "A real quote"
        assert result[2]["quote"] is None

    def test_case_insensitive(self):
        assert _sanitize_null_strings("NULL") is None
        assert _sanitize_null_strings(" Null ") is None

    def test_number_not_affected(self):
        data = {"count": 5, "label": "null"}
        result = _sanitize_null_strings(data)
        assert result["count"] == 5
        assert result["label"] is None
