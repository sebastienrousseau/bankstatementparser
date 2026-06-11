"""Behavioral tests for the shared LLM response-parsing helpers."""

import unittest

from bankstatementparser._llm_common import (
    parse_confidence,
    parse_json_payload,
)


class _StubError(RuntimeError):
    pass


class TestParseJsonPayload(unittest.TestCase):
    def test_bare_object_parses(self):
        self.assertEqual(
            parse_json_payload('prose {"a": 1} more prose'), {"a": 1}
        )

    def test_fenced_object_parses(self):
        raw = 'Sure!\n```json\n{"a": 1}\n```\nDone.'
        self.assertEqual(parse_json_payload(raw), {"a": 1})

    def test_fenced_invalid_json_raises(self):
        raw = "```json\n{not valid json}\n```"
        with self.assertRaisesRegex(_StubError, "valid JSON"):
            parse_json_payload(raw, error_cls=_StubError)

    def test_bare_invalid_json_raises(self):
        with self.assertRaisesRegex(_StubError, "valid JSON"):
            parse_json_payload("prefix {broken", error_cls=_StubError)

    def test_no_object_raises(self):
        with self.assertRaisesRegex(_StubError, "no object found"):
            parse_json_payload("no braces here", error_cls=_StubError)


class TestParseConfidence(unittest.TestCase):
    def test_none_passes_through(self):
        self.assertIsNone(parse_confidence(None))

    def test_valid_value_coerced_to_float(self):
        self.assertEqual(parse_confidence("0.75"), 0.75)

    def test_non_numeric_raises(self):
        with self.assertRaisesRegex(_StubError, "Invalid confidence"):
            parse_confidence("high", error_cls=_StubError)

    def test_above_one_raises(self):
        with self.assertRaisesRegex(_StubError, "out of range"):
            parse_confidence(1.5, error_cls=_StubError)

    def test_negative_raises(self):
        with self.assertRaisesRegex(_StubError, "out of range"):
            parse_confidence(-0.1, error_cls=_StubError)


if __name__ == "__main__":
    unittest.main()
