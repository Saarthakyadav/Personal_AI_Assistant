"""
One-shot script: visually confirm all three memory tiers appear
as distinct, clearly-labeled sections in the assembled system prompt.
Run from project root: python show_system_prompt_demo.py
"""
import os, sys, io, tempfile
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.environ.pop("MONGODB_URI", None)

from unittest.mock import MagicMock
from src.memory import UserMemory
from src.tools import ToolRegistry
from src.agent import AgentCore

# ── Tier 1: Semantic facts ──────────────────────────────────────────────
tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
tmp.close()
mem = UserMemory(filepath=tmp.name, user_id="demo")
mem._facts = ["User's name is Saarthak", "User studies CS at BITS Pilani"]

# ── Tier 2: Procedural preferences ─────────────────────────────────────
mem._preferences = [
    "Keep replies concise — 2 sentences max",
    "Always ask for confirmation before sending emails",
]

# ── Tier 3: Episodic context (mocked — no real ChromaDB needed) ─────────
episodic_ctx = (
    "Here are relevant past conversations that may help "
    "(not the current conversation, but earlier ones):\n"
    "- [turn 2] User asked: What is Python?  "
    "You responded: Python is a high-level interpreted language."
)

prefs_block = mem.get_preferences_prompt()

# ── Build AgentCore + extract system prompt ─────────────────────────────
registry = ToolRegistry()
agent = AgentCore(
    groq_client=MagicMock(),
    memory=mem,
    tool_registry=registry,
)

msgs = agent._build_initial_messages(
    user_message="Tell me about Python",
    conversation_history=[],
    mode="chat",
    episodic_context=episodic_ctx,
    prefs_block=prefs_block,
)

system_content = msgs[0]["content"]

print("=" * 70)
print("ASSEMBLED SYSTEM PROMPT — all three memory tiers visible below")
print("=" * 70)
print(system_content)
print("=" * 70)

os.unlink(tmp.name)
print("\nDone. Confirm you can see:")
print("  [Tier 1] 'Here is what you already know about the user...'")
print("  [Tier 2] 'Here is how the user prefers you to behave...'")
print("  [Tier 3] 'Here are relevant past conversations...'")
