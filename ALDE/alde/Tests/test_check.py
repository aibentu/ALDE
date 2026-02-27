"""Unit tests for production module alde.check.

These tests target the real implementation in
ALDE/ALDE/alde/check.py.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch


try:
    # When run as a module from repo root (common in this repo)
    from ALDE.ALDE.alde.check import _key_values, check
except Exception:
    # Fallback for alternative PYTHONPATH layouts
    from alde.check import _key_values, check  # type: ignore


class Dummy:
    _value_name = None


class TestKeyValues(unittest.TestCase):
    def test_non_list_data_returns_empty(self):
        self.assertEqual(_key_values(["name"], data=None), [])

    def test_filters_empty_and_none_values(self):
        data = [
            {"name": "Alice", "age": 30, "city": "Berlin"},
            {"name": "", "age": 28, "city": ""},
            {"name": "David", "age": None, "city": "Cologne"},
        ]
        bundles = _key_values(["name", "age", "city"], data)

        # 1st entry has all requested keys
        self.assertIn({"name": "Alice", "age": 30, "city": "Berlin"}, bundles)

        # 2nd entry: name/city are empty, so only age remains
        self.assertIn({"age": 28}, bundles)

        # 3rd entry: age is None, so name/city remain
        self.assertIn({"name": "David", "city": "Cologne"}, bundles)

    def test_missing_keys_are_skipped(self):
        data = [{"name": "Alice"}, {"age": 30}, {"name": "Bob", "age": 25}]
        bundles = _key_values(["name", "age"], data)
        self.assertEqual(bundles, [{"name": "Alice"}, {"age": 30}, {"name": "Bob", "age": 25}])


class TestCheck(unittest.TestCase):
    def setUp(self):
        Dummy._value_name = None

    def test_returns_first_matching_bundle(self):
        data = [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
        ]
        result = check(Dummy, "Bob", ["name", "age"], data=data)
        self.assertEqual(result, {"name": "Bob", "age": 25})
        self.assertEqual(Dummy._value_name, {"name": "Bob", "age": 25})

    @patch("builtins.print")
    def test_missing_value_returns_none_and_clears_value_name(self, mock_print):
        data = [{"name": "Alice", "age": 30}]
        Dummy._value_name = {"name": "Alice"}
        result = check(Dummy, "NOPE", ["name", "age"], data=data)
        self.assertIsNone(result)
        self.assertIsNone(Dummy._value_name)
        mock_print.assert_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
