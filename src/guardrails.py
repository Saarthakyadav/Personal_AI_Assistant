# src/guardrails.py
"""
Guardrails for Nova — prompt-injection screening and output secret-scrubbing.

Imported by both agent.py and orchestrator.py (single shared module, no duplication).
Also imported by plugin_adapter.py for HIGH_RISK_TOOLS membership checks.

Three public symbols:
    sanitize_input(user_message) -> (str, list[str])
        Regex/heuristic pass over the incoming message.  Returns the original
        message *unchanged* plus a list of matched pattern names for logging.
        Never silently rewrites or strips user text — flag-and-log only.

    scrub_output(text) -> str
        Regex pass replacing common secret shapes with "[redacted]" before a
        response leaves the agent.

    HIGH_RISK_TOOLS: set[str]
        The exact set of tools registered with requires_confirmation=True in this
        repo (verified by grep across src/tools/*.py).  Kept here so plugin_adapter
        and any future callers import from one place.
"""

import os
import re
from typing import Tuple, List


# ── HIGH_RISK_TOOLS ───────────────────────────────────────────────────────────
# Derived from grepping `requires_confirmation=True` across src/tools/*.py:
#   set_reminder          reminders.py:189
#   execute_python        general_tools.py:127
#   read_file             general_tools.py:300
#   send_email            email_tool.py:265
#   create_calendar_event calendar_tool.py:85
#   delete_calendar_event calendar_tool.py:173
#   schedule_task         automation.py:74
#   cancel_task           automation.py:96
#
# browser_search_and_book intentionally excluded — it has no requires_confirmation=True
# flag in browser.py; agent.py guards it separately via `action == "book"`.

HIGH_RISK_TOOLS: set = {
    "set_reminder",
    "execute_python",
    "read_file",
    "send_email",
    "create_calendar_event",
    "delete_calendar_event",
    "schedule_task",
    "cancel_task",
}


# ── sanitize_input ────────────────────────────────────────────────────────────

# Patterns that suggest prompt-injection or instruction-override attempts.
# Each entry is (pattern_name, compiled_regex).  Case-insensitive throughout.
_INJECTION_PATTERNS: List[Tuple[str, re.Pattern]] = [
    (
        "system_prompt_override",
        re.compile(
            r"ignore\s+(all\s+)?(previous|above|prior|earlier)\s+instructions?"
            r"|disregard\s+(the\s+)?(above|previous|prior|earlier)"
            r"|forget\s+everything\s+(above|before|prior)"
            r"|override\s+(your\s+)?(instructions?|system\s+prompt)"
            r"|new\s+instructions?:",
            re.IGNORECASE,
        ),
    ),
    (
        "identity_override",
        re.compile(
            r"you\s+are\s+now\s+(a|an|the)\b"
            r"|pretend\s+(you\s+are|to\s+be)\b"
            r"|act\s+as\s+(if\s+you\s+(are|were)\b|a\b|an\b)"
            r"|your\s+new\s+persona\s+is\b"
            r"|from\s+now\s+on\s+you\s+(are|will\s+be)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "prompt_leakage_request",
        re.compile(
            r"reveal\s+(your\s+)?(system\s+prompt|instructions?|base\s+prompt)"
            r"|show\s+me\s+(your\s+)?(system\s+prompt|instructions?)"
            r"|print\s+(your\s+)?(system\s+prompt|instructions?)"
            r"|what\s+(are\s+your|is\s+your)\s+(system\s+prompt|instructions?|base\s+instructions?)",
            re.IGNORECASE,
        ),
    ),
    (
        "fake_delimiter_injection",
        re.compile(
            r"<\s*system\s*>"         # <system> or < system >
            r"|<\s*/\s*system\s*>"    # </system>
            r"|<\s*\|?\s*INST\s*\|?\s*>"  # [INST] / <|INST|>
            r"|\[INST\]"
            r"|###\s*(system|instruction|prompt|user|assistant)\b",
            re.IGNORECASE,
        ),
    ),
]


def sanitize_input(user_message: str) -> Tuple[str, List[str]]:
    """
    Scan *user_message* for prompt-injection / instruction-override patterns.

    Returns:
        (user_message, flagged_patterns) where:
          - user_message   : the original string, UNCHANGED (no silent rewriting)
          - flagged_patterns: list of matched pattern names (empty if clean)

    Callers should log any non-empty flagged_patterns list but MUST NOT block
    the request on a flag alone — false positives on legitimate messages that
    happen to contain trigger words must not silently fail conversations.
    """
    flagged: List[str] = []
    for name, pattern in _INJECTION_PATTERNS:
        if pattern.search(user_message):
            flagged.append(name)
    return user_message, flagged


# ── scrub_output ──────────────────────────────────────────────────────────────

def _build_secret_patterns() -> List[re.Pattern]:
    """
    Build the list of regex patterns used by scrub_output().

    Called once at module load time.  Includes:
      - Well-known API-key prefixes (sk-, AIza, ghp_)
      - Bearer token pattern
      - The actual values of sensitive env vars used in this repo
        (loaded from os.environ so they're redacted even in verbose debug output)

    Env vars covered (cross-referenced against src/auth.py, src/database.py,
    src/tools/email_tool.py, src/audio/tts.py, server.py):
        SECRET_KEY        — JWT signing key (auth.py:12)
        GROQ_API_KEY      — Groq API key (server.py:68)
        ELEVENLABS_API_KEY — ElevenLabs TTS key (audio/tts.py:36)
        MONGODB_URI       — MongoDB connection string (database.py:13)
        EMAIL_PASSWORD    — SMTP/Gmail app password (email_tool.py:66)
    """
    patterns: List[re.Pattern] = [
        # OpenAI/Groq-style secret keys
        re.compile(r"sk-[A-Za-z0-9]{20,}", re.ASCII),
        # Google API keys
        re.compile(r"AIza[A-Za-z0-9_\-]{35}", re.ASCII),
        # GitHub personal access tokens
        re.compile(r"ghp_[A-Za-z0-9]{36}", re.ASCII),
        # ElevenLabs API keys (prefix sk_ as seen in .env)
        re.compile(r"sk_[A-Za-z0-9]{20,}", re.ASCII),
        # Bearer tokens in Authorization headers / log output
        re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE | re.ASCII),
    ]

    # Add patterns for the actual values of sensitive env vars (if set).
    # Only add if the value is long enough to be worth matching (> 8 chars)
    # to avoid false-positives on short placeholder values.
    _SENSITIVE_ENV_VARS = [
        "SECRET_KEY",
        "GROQ_API_KEY",
        "ELEVENLABS_API_KEY",
        "MONGODB_URI",
        "EMAIL_PASSWORD",
    ]
    for var_name in _SENSITIVE_ENV_VARS:
        val = os.environ.get(var_name, "")
        if len(val) > 8:
            patterns.append(re.compile(re.escape(val)))

    return patterns


_SECRET_PATTERNS: List[re.Pattern] = _build_secret_patterns()


def scrub_output(text: str) -> str:
    """
    Replace common secret shapes in *text* with "[redacted]".

    Patterns covered:
      - sk-<20+ alphanum>        (Groq / OpenAI secret keys)
      - sk_<20+ alphanum>        (ElevenLabs API keys)
      - AIza<35 alphanum>        (Google API keys)
      - ghp_<36 alphanum>        (GitHub PATs)
      - Bearer <token>
      - Actual values of SECRET_KEY, GROQ_API_KEY, ELEVENLABS_API_KEY,
        MONGODB_URI, EMAIL_PASSWORD (loaded from os.environ at import time)

    Returns the scrubbed string.  Safe to call on any string, even empty.
    """
    if not text:
        return text
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text
