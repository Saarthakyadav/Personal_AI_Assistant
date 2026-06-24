# src/memory.py
"""
Persistent user profile memory for Nova.

Stores facts about the user (name, preferences, interests, etc.) in a local
JSON file so they survive across sessions.  Facts are extracted from
conversations via a lightweight LLM call and injected into the system prompt
on every query.
"""

import json
import os
import threading
from datetime import datetime
from typing import List, Optional

# Maximum number of facts to retain.  Oldest are dropped on overflow.
MAX_FACTS = 50

# ── Extraction prompt ────────────────────────────────────────────────────────
_EXTRACT_PROMPT = """\
You are a fact-extraction engine.  Given a conversation snippet between a user \
and an assistant, extract **only new personal facts about the user**.

Rules:
1. Return a JSON array of short, factual strings.  Example: ["User's name is Alex", "User likes hiking"]
2. Only include facts **about the user** — skip facts about the assistant, the weather, generic knowledge, etc.
3. Do NOT duplicate facts already known (listed below).
4. If there are no new facts, return an empty array: []
5. Return ONLY the JSON array — no commentary, no markdown fences.

Already-known facts:
{existing}

Conversation:
User: {user_msg}
Assistant: {assistant_msg}
"""


class UserMemory:
    """Thread-safe persistent user-profile memory backed by a JSON file."""

    def __init__(self, filepath: str = "user_memory.json"):
        self._filepath = filepath
        self._lock = threading.Lock()
        self._facts: List[str] = []
        self._load()

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def fact_count(self) -> int:
        with self._lock:
            return len(self._facts)

    def get_facts_prompt(self) -> str:
        """Return a formatted string of all facts for injection into the system prompt."""
        with self._lock:
            if not self._facts:
                return ""
            numbered = "\n".join(f"- {f}" for f in self._facts)
            return (
                "Here is what you already know about the user from previous "
                "conversations. Use this information naturally — don't repeat "
                "it back unless asked:\n" + numbered
            )

    def extract_and_store(
        self,
        user_msg: str,
        assistant_msg: str,
        groq_client,
        model: str = "llama-3.3-70b-versatile",
    ) -> List[str]:
        """Call the LLM to extract new user facts, store them, and return them.

        Safe to call from a background thread.
        """
        with self._lock:
            existing_text = "\n".join(f"- {f}" for f in self._facts) if self._facts else "(none)"

        prompt = _EXTRACT_PROMPT.format(
            existing=existing_text,
            user_msg=user_msg,
            assistant_msg=assistant_msg,
        )

        try:
            resp = groq_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.0,  # deterministic extraction
            )
            raw = resp.choices[0].message.content.strip()
            new_facts = self._parse_facts(raw)
        except Exception as e:
            print(f"   ⚠️ Memory extraction failed: {e}")
            return []

        if not new_facts:
            return []

        with self._lock:
            added = []
            for fact in new_facts:
                # FIX #11: improved dedup — exact match OR word-overlap similarity
                if self._is_duplicate(fact):
                    continue
                self._facts.append(fact)
                added.append(fact)

            # Trim to MAX_FACTS (drop oldest)
            if len(self._facts) > MAX_FACTS:
                self._facts = self._facts[-MAX_FACTS:]

            if added:
                self._save_unlocked()
                print(f"   🧠 Memorised {len(added)} new fact(s): {added}")

        return added

    # ── Private helpers ───────────────────────────────────────────────────

    def _is_duplicate(self, new_fact: str) -> bool:
        """Check if a new fact is a near-duplicate of any existing fact.

        Uses exact case-insensitive match first, then Jaccard word similarity
        (threshold 0.7) to catch paraphrases like "User's name is Saarthak"
        vs "The user is named Saarthak".

        Caller must hold self._lock.
        """
        new_lower = new_fact.lower()
        new_words = set(new_lower.split())

        for existing in self._facts:
            existing_lower = existing.lower()
            # Exact match
            if new_lower == existing_lower:
                return True
            # Word-overlap (Jaccard) similarity
            existing_words = set(existing_lower.split())
            intersection = new_words & existing_words
            union = new_words | existing_words
            if union and len(intersection) / len(union) >= 0.7:
                return True
        return False

    def _load(self):
        """Load facts from disk.  Missing / corrupt file → start fresh."""
        if not os.path.exists(self._filepath):
            self._facts = []
            return

        try:
            with open(self._filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._facts = data.get("facts", [])
        except Exception as e:
            print(f"   ⚠️ Could not load memory file: {e}")
            self._facts = []

    def _save_unlocked(self):
        """Persist facts to disk.  Caller must hold self._lock."""
        try:
            data = {
                "facts": self._facts,
                "updated_at": datetime.now().isoformat(),
            }
            with open(self._filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"   ⚠️ Could not save memory file: {e}")

    @staticmethod
    def _parse_facts(raw: str) -> List[str]:
        """Best-effort parse of the LLM's JSON array output."""
        raw = raw.strip()

        # Strip markdown code fences if the model wrapped the output
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(
                l for l in lines if not l.strip().startswith("```")
            ).strip()

        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(f).strip() for f in parsed if str(f).strip()]
        except json.JSONDecodeError:
            pass

        # Fallback: try to find a JSON array anywhere in the string
        start = raw.find("[")
        end = raw.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                parsed = json.loads(raw[start : end + 1])
                if isinstance(parsed, list):
                    return [str(f).strip() for f in parsed if str(f).strip()]
            except json.JSONDecodeError:
                pass

        return []
