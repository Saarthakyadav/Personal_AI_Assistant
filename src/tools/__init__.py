# src/tools/__init__.py
"""
Tool registration framework for the Nova agent.

Provides the `Tool` dataclass and `ToolRegistry` class that converts
our tool definitions to the OpenAI-compatible format expected by Groq's
function-calling API.

Phase 2 additions (src/tools/__init__.py only):
  - Tool.retryable field: per-tool opt-out of retry (default True; False for
    any tool whose requires_confirmation=True, i.e. irreversible/side-effecting).
  - ToolRegistry.execute(): bounded retry loop (max 3 attempts, exponential
    backoff 0.5s → 1s) on transient network exceptions; no retry on TypeError
    or for retryable=False tools.
  - ToolMetrics / ToolRegistry._metrics: in-memory circular buffer (max 500)
    recording per-call telemetry (tool_name, duration_ms, success, retry_count,
    timestamp, error).
  - ToolRegistry.get_metrics() / get_metrics_summary(): public read API.
"""

import json
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional


def _print_log(msg: str) -> None:
    """Print *msg* to stdout, falling back to UTF-8 byte-write on encodings
    (e.g. Windows cp1252) that cannot represent emoji characters."""
    try:
        print(msg)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((msg + "\n").encode("utf-8", errors="replace"))
        sys.stdout.buffer.flush()


# ── Transient exception types we are willing to retry ────────────────────────
# Try to import httpx/requests equivalents; fall back gracefully if not installed.

_RETRYABLE_EXC_TYPES: tuple = (ConnectionError, TimeoutError, OSError)

try:
    import requests
    _RETRYABLE_EXC_TYPES = _RETRYABLE_EXC_TYPES + (requests.exceptions.RequestException,)
except ImportError:
    pass

try:
    import httpx
    _RETRYABLE_EXC_TYPES = _RETRYABLE_EXC_TYPES + (httpx.HTTPError,)
except ImportError:
    pass


# ── ToolMetrics ───────────────────────────────────────────────────────────────

class ToolMetrics:
    """
    In-memory circular buffer recording one entry per ToolRegistry.execute() call.

    Each entry is a dict with keys:
      tool_name    str   – the tool that was invoked
      timestamp    str   – ISO-8601 UTC timestamp of the call start
      duration_ms  float – wall-clock time for the full call (all attempts)
      success      bool  – True if any attempt returned without exception
      retry_count  int   – number of *extra* attempts beyond the first (0 = no retries)
      error        str|None – error message of the last exception if success=False
    """

    _MAX_ENTRIES = 500

    def __init__(self):
        self._buf: deque = deque(maxlen=self._MAX_ENTRIES)

    def record(
        self,
        tool_name: str,
        duration_ms: float,
        success: bool,
        retry_count: int,
        error: Optional[str] = None,
    ) -> None:
        self._buf.append({
            "tool_name":   tool_name,
            "timestamp":   datetime.now(timezone.utc).isoformat(),
            "duration_ms": round(duration_ms, 2),
            "success":     success,
            "retry_count": retry_count,
            "error":       error,
        })

    def recent(
        self,
        tool_name: Optional[str] = None,
        last_n: int = 50,
    ) -> List[dict]:
        """Return up to *last_n* entries, most-recent first, optionally filtered."""
        entries = list(self._buf)
        if tool_name is not None:
            entries = [e for e in entries if e["tool_name"] == tool_name]
        # Reverse so most-recent is first, then cap
        return list(reversed(entries))[:last_n]

    def summary(self) -> dict:
        """Aggregate stats: overall + per-tool breakdown."""
        all_entries = list(self._buf)
        if not all_entries:
            return {
                "total_calls": 0,
                "overall_success_rate": None,
                "average_latency_ms": None,
                "per_tool": {},
            }

        total = len(all_entries)
        successes = sum(1 for e in all_entries if e["success"])
        avg_lat = sum(e["duration_ms"] for e in all_entries) / total

        # Per-tool aggregation
        per_tool: Dict[str, dict] = {}
        for entry in all_entries:
            tn = entry["tool_name"]
            if tn not in per_tool:
                per_tool[tn] = {
                    "call_count": 0,
                    "_successes": 0,
                    "_total_ms": 0.0,
                    "_total_retries": 0,
                }
            bucket = per_tool[tn]
            bucket["call_count"] += 1
            if entry["success"]:
                bucket["_successes"] += 1
            bucket["_total_ms"] += entry["duration_ms"]
            bucket["_total_retries"] += entry["retry_count"]

        # Compute derived stats and clean up private accumulators
        for tn, bucket in per_tool.items():
            n = bucket["call_count"]
            bucket["success_rate"] = round(bucket["_successes"] / n, 4)
            bucket["avg_latency_ms"] = round(bucket["_total_ms"] / n, 2)
            bucket["avg_retries"] = round(bucket["_total_retries"] / n, 4)
            del bucket["_successes"], bucket["_total_ms"], bucket["_total_retries"]

        return {
            "total_calls": total,
            "overall_success_rate": round(successes / total, 4),
            "average_latency_ms": round(avg_lat, 2),
            "per_tool": per_tool,
        }


# ── Tool dataclass ────────────────────────────────────────────────────────────

@dataclass
class Tool:
    """A single tool that the agent can invoke."""

    name: str
    description: str
    parameters: dict                     # JSON Schema for the tool's arguments
    handler: Callable                    # The actual Python function to run
    requires_confirmation: bool = False  # If True, ask user before executing
    retryable: bool = True               # If False, never retry on failure
                                         # (auto-defaulted to False for any tool
                                         #  registered with requires_confirmation=True
                                         #  — see ToolRegistry.register())


# ── ToolRegistry ──────────────────────────────────────────────────────────────

class ToolRegistry:
    """Registry that holds all available tools and provides them to the LLM."""

    # Retry configuration (kept short for voice-response latency budget)
    _MAX_ATTEMPTS = 3
    _BACKOFF_SECONDS = [0.5, 1.0]  # sleep durations between attempts 1→2 and 2→3

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._metrics = ToolMetrics()

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self, tool: Tool):
        """
        Register a tool.  Overwrites if the name already exists.

        Auto-policy: any tool with requires_confirmation=True is implicitly
        treated as non-retryable (irreversible/side-effecting) unless the
        caller has explicitly set retryable=False themselves already.
        The dataclass default for retryable is True, so we flip it here only
        when the caller left it at the default *and* requires_confirmation=True.
        """
        if tool.requires_confirmation and tool.retryable:
            # Use object.__setattr__ to mutate a frozen-safe dataclass field;
            # our dataclass is not frozen so direct assignment is fine.
            tool.retryable = False
        self._tools[tool.name] = tool

    # ── Lookup ────────────────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    @property
    def tool_names(self) -> List[str]:
        return list(self._tools.keys())

    @property
    def count(self) -> int:
        return len(self._tools)

    # ── Groq / OpenAI format ──────────────────────────────────────────────────

    def get_tool_definitions(self) -> List[dict]:
        """Return tool definitions in the OpenAI-compatible format for Groq."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]

    # ── Execution ─────────────────────────────────────────────────────────────

    def execute(self, tool_name: str, arguments: dict) -> str:
        """
        Execute a tool by name.  Returns a JSON string (result or error).

        Retry behaviour (for retryable tools only):
          - Up to _MAX_ATTEMPTS total attempts.
          - Retries only on transient network exceptions
            (ConnectionError, TimeoutError, OSError, requests/httpx errors).
          - Never retries on TypeError (malformed LLM arguments) or when
            tool.retryable is False.
          - Exponential backoff: 0.5 s → 1.0 s between attempts.
          - Logs each failed attempt to stdout with an emoji prefix matching
            the rest of the codebase style.

        Metrics are recorded once per call (not per attempt) via self._metrics.
        """
        # ── Unknown tool — fail fast, no retry needed ─────────────────────────
        tool = self._tools.get(tool_name)
        if tool is None:
            return json.dumps({
                "error": f"Unknown tool '{tool_name}'. Available tools: "
                         f"{', '.join(self._tools.keys())}"
            })

        if not isinstance(arguments, dict):
            arguments = {}

        max_attempts = self._MAX_ATTEMPTS if tool.retryable else 1
        last_exception: Optional[Exception] = None
        retry_count = 0
        t_start = time.monotonic()

        for attempt in range(1, max_attempts + 1):
            try:
                result = tool.handler(**arguments)
                # Ensure we always return a string
                if not isinstance(result, str):
                    result = json.dumps(result)

                # ── Record success metric ──────────────────────────────────────
                duration_ms = (time.monotonic() - t_start) * 1000
                self._metrics.record(
                    tool_name=tool_name,
                    duration_ms=duration_ms,
                    success=True,
                    retry_count=retry_count,
                )
                return result

            except TypeError as e:
                # Malformed arguments from the LLM — retrying won't fix this.
                duration_ms = (time.monotonic() - t_start) * 1000
                self._metrics.record(
                    tool_name=tool_name,
                    duration_ms=duration_ms,
                    success=False,
                    retry_count=retry_count,
                    error=str(e),
                )
                return json.dumps({"error": f"Tool '{tool_name}' failed: {str(e)}"})

            except _RETRYABLE_EXC_TYPES as e:
                last_exception = e
                if attempt < max_attempts:
                    retry_count += 1
                    backoff = self._BACKOFF_SECONDS[attempt - 1]
                    _print_log(
                        f"   \u26a0\ufe0f Tool '{tool_name}' failed (attempt {attempt}/{max_attempts}), "
                        f"retrying in {backoff}s... [{type(e).__name__}: {e}]"
                    )
                    time.sleep(backoff)
                # else: fall through to the exhausted-retries path below

            except Exception as e:
                # Non-retryable application-level exception (ValueError, etc.)
                duration_ms = (time.monotonic() - t_start) * 1000
                self._metrics.record(
                    tool_name=tool_name,
                    duration_ms=duration_ms,
                    success=False,
                    retry_count=retry_count,
                    error=str(e),
                )
                return json.dumps({"error": f"Tool '{tool_name}' failed: {str(e)}"})

        # ── All retries exhausted ─────────────────────────────────────────────
        duration_ms = (time.monotonic() - t_start) * 1000
        error_msg = str(last_exception) if last_exception else "unknown error"
        _print_log(
            f"   \u274c Tool '{tool_name}' failed after {max_attempts} attempt(s): {error_msg}"
        )
        self._metrics.record(
            tool_name=tool_name,
            duration_ms=duration_ms,
            success=False,
            retry_count=retry_count,
            error=error_msg,
        )
        return json.dumps({"error": f"Tool '{tool_name}' failed: {error_msg}"})

    # ── Metrics API ───────────────────────────────────────────────────────────

    def get_metrics(
        self,
        tool_name: Optional[str] = None,
        last_n: int = 50,
    ) -> List[dict]:
        """
        Return recent metric entries, most-recent first.

        Args:
            tool_name: If provided, filter to entries for this tool only.
            last_n:    Maximum number of entries to return (default 50).

        Returns:
            List of metric dicts (see ToolMetrics.record() for field docs).
        """
        return self._metrics.recent(tool_name=tool_name, last_n=last_n)

    def get_metrics_summary(self) -> dict:
        """
        Return aggregate stats across all recorded calls.

        Returns a dict with:
          total_calls          int
          overall_success_rate float (0.0–1.0) or None if no calls yet
          average_latency_ms   float or None
          per_tool             dict[tool_name → {call_count, success_rate,
                                                  avg_latency_ms, avg_retries}]
        """
        return self._metrics.summary()
