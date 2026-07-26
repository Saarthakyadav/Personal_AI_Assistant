# src/test_tool_registry.py
"""
Unit tests for ToolRegistry retry logic and observability (ToolMetrics).

Covers:
  (a) A tool that fails twice then succeeds on the 3rd attempt is retried
      and returns the success result.
  (b) A tool marked retryable=False fails once and is NOT retried.
  (c) A tool raising TypeError is NOT retried even if retryable=True.
  (d) get_metrics_summary() returns correct aggregate numbers after a mix
      of successful, failed, and retried calls.

All tests are self-contained and require no external services.
"""

import json
import unittest
from unittest.mock import patch

from src.tools import Tool, ToolRegistry


# ── Helper: make a simple tool ────────────────────────────────────────────────

def _make_tool(name: str, handler, requires_confirmation: bool = False, retryable: bool = True) -> Tool:
    return Tool(
        name=name,
        description=f"Test tool: {name}",
        parameters={"type": "object", "properties": {}},
        handler=handler,
        requires_confirmation=requires_confirmation,
        retryable=retryable,
    )


# ── Test cases ────────────────────────────────────────────────────────────────

class TestRetryLogic(unittest.TestCase):
    """Tests for the retry behaviour inside ToolRegistry.execute()."""

    def setUp(self):
        self.registry = ToolRegistry()

    # ── (a) Fails twice, succeeds on 3rd attempt ──────────────────────────────

    def test_retry_succeeds_on_third_attempt(self):
        """
        A tool that raises ConnectionError twice then returns a value should:
          - be retried up to 3 total attempts
          - return the success result (not an error JSON)
          - record retry_count == 2 in metrics
        """
        call_count = {"n": 0}

        def flaky_handler():
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise ConnectionError("Network blip")
            return json.dumps({"status": "ok", "attempt": call_count["n"]})

        tool = _make_tool("flaky_tool", flaky_handler, retryable=True)
        self.registry.register(tool)

        # Patch time.sleep so the test doesn't actually wait
        with patch("time.sleep"):
            result_str = self.registry.execute("flaky_tool", {})

        result = json.loads(result_str)
        self.assertNotIn("error", result, "Expected success but got error: " + result_str)
        self.assertEqual(result["attempt"], 3)
        self.assertEqual(call_count["n"], 3, "Handler should have been called 3 times")

        # Metrics should show retry_count == 2 (two extra attempts)
        metrics = self.registry.get_metrics("flaky_tool", last_n=1)
        self.assertEqual(len(metrics), 1)
        entry = metrics[0]
        self.assertTrue(entry["success"])
        self.assertEqual(entry["retry_count"], 2)
        self.assertIsNone(entry["error"])

    # ── (b) retryable=False: fails once, NOT retried ──────────────────────────

    def test_no_retry_when_retryable_false(self):
        """
        A tool explicitly marked retryable=False should fail immediately on
        the first exception without any retry, even for a transient error.
        """
        call_count = {"n": 0}

        def always_fails():
            call_count["n"] += 1
            raise ConnectionError("always failing")

        # Explicitly set retryable=False (not via requires_confirmation)
        tool = _make_tool("no_retry_tool", always_fails, retryable=False)
        self.registry.register(tool)

        with patch("time.sleep") as mock_sleep:
            result_str = self.registry.execute("no_retry_tool", {})

        result = json.loads(result_str)
        self.assertIn("error", result)
        self.assertEqual(call_count["n"], 1, "Handler should only be called once")
        mock_sleep.assert_not_called()

        metrics = self.registry.get_metrics("no_retry_tool", last_n=1)
        self.assertEqual(metrics[0]["retry_count"], 0)
        self.assertFalse(metrics[0]["success"])

    def test_requires_confirmation_implies_not_retryable(self):
        """
        Any tool registered with requires_confirmation=True should have
        retryable auto-set to False by register(), so it is also not retried.
        """
        call_count = {"n": 0}

        def side_effecting():
            call_count["n"] += 1
            raise ConnectionError("transient but irreversible")

        # requires_confirmation=True, retryable left at default (True)
        tool = _make_tool("send_something", side_effecting, requires_confirmation=True)
        self.registry.register(tool)

        # After register(), retryable should have been flipped to False
        registered = self.registry.get("send_something")
        self.assertFalse(registered.retryable,
                         "requires_confirmation=True tool must be non-retryable after register()")

        with patch("time.sleep") as mock_sleep:
            result_str = self.registry.execute("send_something", {})

        result = json.loads(result_str)
        self.assertIn("error", result)
        self.assertEqual(call_count["n"], 1, "Should only be called once")
        mock_sleep.assert_not_called()

    # ── (c) TypeError is NOT retried even if retryable=True ───────────────────

    def test_type_error_is_not_retried(self):
        """
        A TypeError (e.g. from malformed LLM arguments) must never trigger
        a retry, even when the tool is retryable=True.
        """
        call_count = {"n": 0}

        def bad_args_handler():
            call_count["n"] += 1
            raise TypeError("got unexpected keyword argument 'nonsense'")

        tool = _make_tool("type_error_tool", bad_args_handler, retryable=True)
        self.registry.register(tool)

        with patch("time.sleep") as mock_sleep:
            result_str = self.registry.execute("type_error_tool", {})

        result = json.loads(result_str)
        self.assertIn("error", result)
        self.assertEqual(call_count["n"], 1, "TypeError must not trigger retries")
        mock_sleep.assert_not_called()

        metrics = self.registry.get_metrics("type_error_tool", last_n=1)
        self.assertFalse(metrics[0]["success"])
        self.assertEqual(metrics[0]["retry_count"], 0)

    # ── ValueError / other non-transient errors are not retried ───────────────

    def test_value_error_is_not_retried(self):
        """
        A ValueError (deliberate tool-level error) must not trigger retries.
        """
        call_count = {"n": 0}

        def raises_value_error():
            call_count["n"] += 1
            raise ValueError("bad user input")

        tool = _make_tool("value_err_tool", raises_value_error, retryable=True)
        self.registry.register(tool)

        with patch("time.sleep"):
            result_str = self.registry.execute("value_err_tool", {})

        result = json.loads(result_str)
        self.assertIn("error", result)
        self.assertEqual(call_count["n"], 1)

    # ── All retries exhausted returns JSON error ───────────────────────────────

    def test_all_retries_exhausted_returns_json_error(self):
        """
        When all 3 attempts are exhausted, execute() must return the existing
        JSON error shape {"error": "Tool 'X' failed: ..."}.
        """
        def always_network_error():
            raise ConnectionError("persistent failure")

        tool = _make_tool("always_fails_tool", always_network_error, retryable=True)
        self.registry.register(tool)

        with patch("time.sleep"):
            result_str = self.registry.execute("always_fails_tool", {})

        result = json.loads(result_str)
        self.assertIn("error", result)
        self.assertIn("always_fails_tool", result["error"])
        self.assertIn("persistent failure", result["error"])

        metrics = self.registry.get_metrics("always_fails_tool", last_n=1)
        entry = metrics[0]
        self.assertFalse(entry["success"])
        self.assertEqual(entry["retry_count"], 2)   # 2 extra attempts after the first

    # ── Unknown tool returns error (no crash) ─────────────────────────────────

    def test_unknown_tool_returns_error(self):
        """execute() on an unknown tool must return a JSON error, not raise."""
        result_str = self.registry.execute("nonexistent_tool", {})
        result = json.loads(result_str)
        self.assertIn("error", result)
        self.assertIn("nonexistent_tool", result["error"])


class TestMetrics(unittest.TestCase):
    """Tests for ToolMetrics recording and aggregation."""

    def setUp(self):
        self.registry = ToolRegistry()

    def _register_succeeding(self, name: str) -> None:
        self.registry.register(_make_tool(name, lambda: json.dumps({"ok": True})))

    def _register_failing(self, name: str, exc_type=ValueError) -> None:
        def _fail():
            raise exc_type("boom")
        self.registry.register(_make_tool(name, _fail))

    # ── (d) get_metrics_summary() aggregate correctness ──────────────────────

    def test_metrics_summary_correct_aggregates(self):
        """
        After a mix of:
          - 2 successful calls to tool_a
          - 1 failed call (ValueError, no retry) to tool_b
          - 1 retried-then-succeeded call to tool_c (2 retries → retry_count=2)

        get_metrics_summary() must return:
          total_calls == 4
          overall_success_rate == 3/4 == 0.75
          per_tool[tool_a].call_count == 2
          per_tool[tool_a].success_rate == 1.0
          per_tool[tool_b].call_count == 1
          per_tool[tool_b].success_rate == 0.0
          per_tool[tool_c].avg_retries == 2.0
        """
        # tool_a: always succeeds
        self._register_succeeding("tool_a")

        # tool_b: always fails with ValueError (no retry)
        self._register_failing("tool_b", ValueError)

        # tool_c: fails twice then succeeds
        call_count = {"n": 0}
        def flaky():
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise ConnectionError("blip")
            return json.dumps({"ok": True})
        self.registry.register(_make_tool("tool_c", flaky, retryable=True))

        with patch("time.sleep"):
            self.registry.execute("tool_a", {})
            self.registry.execute("tool_a", {})
            self.registry.execute("tool_b", {})
            self.registry.execute("tool_c", {})

        summary = self.registry.get_metrics_summary()

        self.assertEqual(summary["total_calls"], 4)
        self.assertAlmostEqual(summary["overall_success_rate"], 0.75, places=4)

        per = summary["per_tool"]

        self.assertIn("tool_a", per)
        self.assertEqual(per["tool_a"]["call_count"], 2)
        self.assertAlmostEqual(per["tool_a"]["success_rate"], 1.0, places=4)
        self.assertAlmostEqual(per["tool_a"]["avg_retries"], 0.0, places=4)

        self.assertIn("tool_b", per)
        self.assertEqual(per["tool_b"]["call_count"], 1)
        self.assertAlmostEqual(per["tool_b"]["success_rate"], 0.0, places=4)

        self.assertIn("tool_c", per)
        self.assertEqual(per["tool_c"]["call_count"], 1)
        self.assertAlmostEqual(per["tool_c"]["success_rate"], 1.0, places=4)
        self.assertAlmostEqual(per["tool_c"]["avg_retries"], 2.0, places=4)

    def test_metrics_summary_empty(self):
        """get_metrics_summary() on a fresh registry returns sensible None values."""
        summary = self.registry.get_metrics_summary()
        self.assertEqual(summary["total_calls"], 0)
        self.assertIsNone(summary["overall_success_rate"])
        self.assertIsNone(summary["average_latency_ms"])
        self.assertEqual(summary["per_tool"], {})

    def test_get_metrics_filtered_by_tool_name(self):
        """get_metrics(tool_name=X) returns only entries for tool X."""
        self._register_succeeding("tool_x")
        self._register_succeeding("tool_y")

        self.registry.execute("tool_x", {})
        self.registry.execute("tool_y", {})
        self.registry.execute("tool_x", {})

        x_only = self.registry.get_metrics("tool_x")
        self.assertEqual(len(x_only), 2)
        self.assertTrue(all(e["tool_name"] == "tool_x" for e in x_only))

    def test_get_metrics_most_recent_first(self):
        """get_metrics() returns entries most-recent first."""
        call_order = []

        def handler_a():
            call_order.append("a")
            return "a"

        def handler_b():
            call_order.append("b")
            return "b"

        self.registry.register(_make_tool("tool_ord_a", handler_a))
        self.registry.register(_make_tool("tool_ord_b", handler_b))

        self.registry.execute("tool_ord_a", {})
        self.registry.execute("tool_ord_b", {})

        entries = self.registry.get_metrics(last_n=10)
        # Most recent should be tool_ord_b
        self.assertEqual(entries[0]["tool_name"], "tool_ord_b")
        self.assertEqual(entries[1]["tool_name"], "tool_ord_a")

    def test_get_metrics_last_n_cap(self):
        """get_metrics(last_n=N) returns at most N entries."""
        self._register_succeeding("cap_tool")
        for _ in range(10):
            self.registry.execute("cap_tool", {})

        entries = self.registry.get_metrics("cap_tool", last_n=3)
        self.assertEqual(len(entries), 3)

    def test_duration_ms_is_non_negative(self):
        """duration_ms must be a non-negative float."""
        self._register_succeeding("latency_tool")
        self.registry.execute("latency_tool", {})
        entry = self.registry.get_metrics("latency_tool", last_n=1)[0]
        self.assertGreaterEqual(entry["duration_ms"], 0.0)


class TestRetryBackoffBehaviour(unittest.TestCase):
    """Verify the backoff timing values passed to time.sleep."""

    def test_backoff_schedule(self):
        """
        On a 3-attempt run that always fails with ConnectionError, sleep()
        should be called with 0.5 s then 1.0 s (2 sleeps for 3 attempts).
        """
        registry = ToolRegistry()

        def always_conn_err():
            raise ConnectionError("down")

        registry.register(_make_tool("backoff_tool", always_conn_err, retryable=True))

        sleep_calls = []
        with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            registry.execute("backoff_tool", {})

        self.assertEqual(len(sleep_calls), 2, "Expected 2 sleeps for 3 attempts")
        self.assertAlmostEqual(sleep_calls[0], 0.5, places=5)
        self.assertAlmostEqual(sleep_calls[1], 1.0, places=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
