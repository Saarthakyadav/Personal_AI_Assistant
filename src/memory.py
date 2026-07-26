# src/memory.py
"""
Persistent user profile memory for Nova.

Stores facts about the user (name, preferences, interests, etc.) in a MongoDB
collection so they survive across sessions.  Facts are extracted from
conversations via a lightweight LLM call and injected into the system prompt
on every query.
"""

import json
import os
import sys
import threading
from datetime import datetime
from typing import List, Optional


def _print_log(msg: str) -> None:
    """Emoji-safe stdout logger (handles Windows cp1252 terminals)."""
    try:
        print(msg)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((msg + "\n").encode("utf-8", errors="replace"))
        sys.stdout.buffer.flush()

# Maximum number of facts / preferences to retain.  Oldest are dropped on overflow.
MAX_FACTS = 50
MAX_PREFERENCES = 20

# ── Extraction prompts ────────────────────────────────────────────────────────
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

# ── Preference extraction prompt ───────────────────────────────────────────────
# Distinct from _EXTRACT_PROMPT: targets HOW to respond, not factual content.
_PREFERENCE_PROMPT = """\
You are a behavioral-preference extraction engine. Given a conversation snippet \
between a user and an assistant, extract **only new behavioral or style \
preferences** about how the assistant should behave with this user.

IMPORTANT DISTINCTION:
- A PREFERENCE is about HOW to respond: tone, format, confirmation habits, \
explanation depth, etc.
- A FACT is personal content: name, job, hobbies, location, family.

Examples (3 contrastive pairs):
  FACT (do NOT extract): "User's name is Saarthak"
  PREFERENCE (extract):   "User prefers short, direct answers without elaboration"

  FACT (do NOT extract): "User studies computer science"
  PREFERENCE (extract):  "User wants code explained line by line with comments"

  FACT (do NOT extract): "User likes hiking"
  PREFERENCE (extract):  "User prefers to be asked for confirmation before sending emails"

Rules:
1. Return a JSON array of short, imperative preference strings.
   Example: ["Always confirm before sending emails", "Keep replies to 2 sentences max"]
2. Only include NEW preferences not already in the list below.
3. If there are no new behavioral preferences, return an empty array: []
4. Return ONLY the JSON array — no commentary, no markdown fences.
5. Do NOT include facts about the user (name, college, hobbies — those go elsewhere).

Already-known preferences:
{existing}

Conversation:
User: {user_msg}
Assistant: {assistant_msg}
"""


class UserMemory:
    """Thread-safe persistent user-profile memory.

    Uses MongoDB when MONGODB_URI is set, otherwise falls back to a local
    JSON file at *filepath*.
    """

    def __init__(self, filepath: str = "user_memory.json", user_id: str = "default"):
        self._user_id = user_id
        self._filepath = filepath
        self._lock = threading.Lock()
        self._facts: List[str] = []
        self._preferences: List[str] = []   # Procedural / behavioral preferences

        # Decide backend: Mongo if MONGODB_URI is configured, else JSON file
        self._use_mongo = bool(os.getenv("MONGODB_URI"))
        if not self._use_mongo:
            _print_log("\u26a0\ufe0f  MONGODB_URI not set \u2014 using local JSON file for memory")

        self._load()

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def fact_count(self) -> int:
        with self._lock:
            return len(self._facts)

    @property
    def preference_count(self) -> int:
        with self._lock:
            return len(self._preferences)

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

    def get_preferences_prompt(self) -> str:
        """
        Return a formatted string of behavioral preferences for the system prompt.

        Mirrors get_facts_prompt()'s empty-string convention so callers can
        use `if block: system_content += "\\n" + block` safely.
        """
        with self._lock:
            if not self._preferences:
                return ""
            items = "\n".join(f"- {p}" for p in self._preferences)
            return (
                "Here is how the user prefers you to behave, based on past interactions:\n"
                + items
            )

    def extract_and_store_preferences(
        self,
        user_msg: str,
        assistant_msg: str,
        groq_client,
        model: Optional[str] = None,
    ) -> List[str]:
        """
        Call the LLM to extract new behavioral preferences, store them, and return them.

        Uses a separate prompt (_PREFERENCE_PROMPT) that specifically targets
        HOW the assistant should respond, not factual user content.
        Safe to call from a background thread.
        """
        target_model = model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        with self._lock:
            existing_text = (
                "\n".join(f"- {p}" for p in self._preferences)
                if self._preferences else "(none)"
            )

        prompt = _PREFERENCE_PROMPT.format(
            existing=existing_text,
            user_msg=user_msg,
            assistant_msg=assistant_msg,
        )

        try:
            resp = groq_client.chat.completions.create(
                model=target_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.0,
            )
            raw = resp.choices[0].message.content.strip()
            new_prefs = self._parse_facts(raw)   # same JSON-array parser
        except Exception as e:
            _print_log(f"   \u26a0\ufe0f Preference extraction failed: {e}")
            return []

        if not new_prefs:
            return []

        with self._lock:
            added = []
            for pref in new_prefs:
                if self._is_duplicate_preference(pref):
                    continue
                self._preferences.append(pref)
                added.append(pref)

            # Trim to MAX_PREFERENCES (drop oldest)
            if len(self._preferences) > MAX_PREFERENCES:
                self._preferences = self._preferences[-MAX_PREFERENCES:]

            if added:
                self._save_unlocked()
                _print_log(f"   \ud83e\udde0 Preference learned ({len(added)}): {added}")

        return added

    def extract_and_store(
        self,
        user_msg: str,
        assistant_msg: str,
        groq_client,
        model: Optional[str] = None,
    ) -> List[str]:
        """Call the LLM to extract new user facts, store them, and return them.

        Safe to call from a background thread.
        """
        target_model = model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        with self._lock:
            existing_text = "\n".join(f"- {f}" for f in self._facts) if self._facts else "(none)"

        prompt = _EXTRACT_PROMPT.format(
            existing=existing_text,
            user_msg=user_msg,
            assistant_msg=assistant_msg,
        )

        try:
            resp = groq_client.chat.completions.create(
                model=target_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.0,  # deterministic extraction
            )
            raw = resp.choices[0].message.content.strip()
            new_facts = self._parse_facts(raw)
        except Exception as e:
            _print_log(f"   \u26a0\ufe0f Memory extraction failed: {e}")
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
                _print_log(f"   \ud83e\udde0 Memorised {len(added)} new fact(s): {added}")

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

    def _is_duplicate_preference(self, new_pref: str) -> bool:
        """Check if a new preference is a near-duplicate of any existing preference.

        Same Jaccard logic as _is_duplicate, operating on self._preferences.
        Caller must hold self._lock.
        """
        new_lower = new_pref.lower()
        new_words = set(new_lower.split())

        for existing in self._preferences:
            existing_lower = existing.lower()
            if new_lower == existing_lower:
                return True
            existing_words = set(existing_lower.split())
            intersection = new_words & existing_words
            union = new_words | existing_words
            if union and len(intersection) / len(union) >= 0.7:
                return True
        return False

    def _load(self):
        """Load facts from the configured backend."""
        if self._use_mongo:
            self._load_mongo()
        else:
            self._load_file()

    def _save_unlocked(self):
        """Persist facts. Caller must hold self._lock."""
        if self._use_mongo:
            self._save_mongo()
        else:
            self._save_file()

    # ── MongoDB backend ───────────────────────────────────────────────────

    def _load_mongo(self):
        from src.database import db_manager
        try:
            col = db_manager.get_collection("memory")
            doc = col.find_one({"user_id": self._user_id})
            if doc:
                self._facts = doc.get("facts", [])
                self._preferences = doc.get("preferences", [])  # backward-compatible
            else:
                self._facts = []
                self._preferences = []
        except Exception as e:
            _print_log(f"   \u26a0\ufe0f Could not load memory from DB: {e}")
            self._facts = []
            self._preferences = []

    def _save_mongo(self):
        from src.database import db_manager
        try:
            col = db_manager.get_collection("memory")
            col.update_one(
                {"user_id": self._user_id},
                {"$set": {
                    "facts": self._facts,
                    "preferences": self._preferences,
                    "updated_at": datetime.now().isoformat(),
                }},
                upsert=True
            )
        except Exception as e:
            _print_log(f"   \u26a0\ufe0f Could not save memory to DB: {e}")

    # ── JSON-file backend ─────────────────────────────────────────────────

    def _load_file(self):
        if not os.path.exists(self._filepath):
            self._facts = []
            self._preferences = []
            return
        try:
            with open(self._filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Support both flat list and {user_id: {facts: [...]}} formats
            if isinstance(data, list):
                self._facts = data
                self._preferences = []
            elif isinstance(data, dict):
                user_data = data.get(self._user_id, {})
                if isinstance(user_data, dict):
                    self._facts = user_data.get("facts", [])
                    self._preferences = user_data.get("preferences", [])  # backward-compatible
                elif isinstance(user_data, list):
                    self._facts = user_data
                    self._preferences = []
                else:
                    self._facts = []
                    self._preferences = []
            else:
                self._facts = []
                self._preferences = []
        except Exception as e:
            _print_log(f"   \u26a0\ufe0f Could not load memory from file: {e}")
            self._facts = []
            self._preferences = []

    def _save_file(self):
        try:
            # Load existing file to preserve other users' data
            existing: dict = {}
            if os.path.exists(self._filepath):
                try:
                    with open(self._filepath, "r", encoding="utf-8") as f:
                        existing = json.load(f)
                    if not isinstance(existing, dict):
                        existing = {}
                except Exception:
                    existing = {}

            existing[self._user_id] = {
                "facts": self._facts,
                "preferences": self._preferences,
                "updated_at": datetime.now().isoformat(),
            }
            with open(self._filepath, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)
        except Exception as e:
            _print_log(f"   \u26a0\ufe0f Could not save memory to file: {e}")

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
