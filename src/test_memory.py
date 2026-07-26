# src/test_memory.py
"""
Tests for the three-tier memory system:
  - Tier 1 (Semantic):   UserMemory facts extraction, persistence
  - Tier 2 (Procedural): UserMemory preferences extraction, persistence
  - Tier 3 (Episodic):   EpisodicMemory store/retrieve with exclude_recent filter

All tests are pure-stdlib unittest (no pytest, no mongomock, no real
ChromaDB or ML models needed).  The JSON-file backend is used for
UserMemory, and chromadb / sentence-transformers are fully mocked for
EpisodicMemory.
"""

import json
import os
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch


# ── Tier 1: Semantic memory (UserMemory — original tests, converted) ──────────

class TestUserMemoryJsonBackend(unittest.TestCase):
    """UserMemory file-backend tests (no MongoDB needed)."""

    def _make_temp(self):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        tmp.close()
        return tmp.name

    def _make_memory(self, path, user_id="test_user"):
        env = os.environ.copy()
        env.pop("MONGODB_URI", None)
        with patch.dict(os.environ, env, clear=True):
            from src.memory import UserMemory
            return UserMemory(filepath=path, user_id=user_id)

    def test_empty_on_fresh_file(self):
        path = self._make_temp()
        try:
            mem = self._make_memory(path)
            self.assertEqual(mem.fact_count, 0)
            self.assertEqual(mem._preferences, [])
        finally:
            os.unlink(path)

    def test_facts_persisted_and_reloaded(self):
        path = self._make_temp()
        try:
            mem = self._make_memory(path)
            mem._facts.append("User likes Python")
            mem._facts.append("User lives in Delhi")
            with mem._lock:
                mem._save_unlocked()

            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("test_user", data)
            self.assertIn("User likes Python", data["test_user"]["facts"])

            mem2 = self._make_memory(path)
            self.assertEqual(mem2.fact_count, 2)
            self.assertIn("User likes Python", mem2._facts)
        finally:
            os.unlink(path)

    def test_preferences_persisted_alongside_facts(self):
        """preferences key is written and reloaded correctly."""
        path = self._make_temp()
        try:
            mem = self._make_memory(path)
            mem._facts.append("User likes hiking")
            mem._preferences.append("Always use bullet points")
            with mem._lock:
                mem._save_unlocked()

            mem2 = self._make_memory(path)
            self.assertIn("User likes hiking", mem2._facts)
            self.assertIn("Always use bullet points", mem2._preferences)
        finally:
            os.unlink(path)

    def test_backward_compat_file_without_preferences_key(self):
        """Old files without 'preferences' key load without error → []."""
        path = self._make_temp()
        old_data = {"old_user": {"facts": ["User likes hiking"], "updated_at": "2025-01-01"}}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(old_data, f)
        try:
            env = os.environ.copy()
            env.pop("MONGODB_URI", None)
            with patch.dict(os.environ, env, clear=True):
                from src.memory import UserMemory
                mem = UserMemory(filepath=path, user_id="old_user")
            self.assertEqual(mem._facts, ["User likes hiking"])
            self.assertEqual(mem._preferences, [])
        finally:
            os.unlink(path)

    def test_get_facts_prompt_empty_string_when_no_facts(self):
        path = self._make_temp()
        try:
            mem = self._make_memory(path)
            self.assertEqual(mem.get_facts_prompt(), "")
        finally:
            os.unlink(path)

    def test_get_facts_prompt_contains_facts(self):
        path = self._make_temp()
        try:
            mem = self._make_memory(path)
            mem._facts = ["User's name is Alex", "User likes Python"]
            prompt = mem.get_facts_prompt()
            self.assertIn("Alex", prompt)
            self.assertIn("Python", prompt)
        finally:
            os.unlink(path)


# ── Tier 2: Procedural memory (UserMemory preferences) ───────────────────────

class TestProceduralMemory(unittest.TestCase):
    """Tests for UserMemory's behavioral preference extraction and storage."""

    def _make_memory(self):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        tmp.close()
        env = os.environ.copy()
        env.pop("MONGODB_URI", None)
        with patch.dict(os.environ, env, clear=True):
            from src.memory import UserMemory
            mem = UserMemory(filepath=tmp.name, user_id="test")
        return mem, tmp.name

    def test_get_preferences_prompt_empty_when_no_preferences(self):
        mem, path = self._make_memory()
        try:
            self.assertEqual(mem.get_preferences_prompt(), "")
        finally:
            os.unlink(path)

    def test_get_preferences_prompt_format(self):
        mem, path = self._make_memory()
        try:
            mem._preferences = ["Keep replies short", "Confirm before sending emails"]
            prompt = mem.get_preferences_prompt()
            self.assertIn("prefers you to behave", prompt)
            self.assertIn("Keep replies short", prompt)
            self.assertIn("Confirm before sending emails", prompt)
        finally:
            os.unlink(path)

    def test_preference_extraction_via_mock_llm(self):
        """extract_and_store_preferences stores preferences returned by mocked LLM."""
        mem, path = self._make_memory()
        try:
            mock_groq = MagicMock()
            mock_groq.chat.completions.create.return_value = MagicMock(
                choices=[MagicMock(
                    message=MagicMock(
                        content='["User prefers short, direct answers"]'
                    )
                )]
            )
            result = mem.extract_and_store_preferences(
                user_msg="Please be brief.",
                assistant_msg="Sure, I will keep it short.",
                groq_client=mock_groq,
            )
            self.assertEqual(result, ["User prefers short, direct answers"])
            self.assertIn("User prefers short, direct answers", mem._preferences)
        finally:
            os.unlink(path)

    def test_preference_does_not_land_in_facts(self):
        """
        Preferences extracted by extract_and_store_preferences must NEVER
        appear in self._facts — the two tiers are strictly separate.
        """
        mem, path = self._make_memory()
        try:
            mock_groq = MagicMock()
            mock_groq.chat.completions.create.return_value = MagicMock(
                choices=[MagicMock(
                    message=MagicMock(content='["Keep replies under 3 sentences"]')
                )]
            )
            mem.extract_and_store_preferences("be concise", "ok", mock_groq)
            self.assertEqual(mem._facts, [],
                             "preferences must never appear in _facts")
        finally:
            os.unlink(path)

    def test_preference_dedup_exact(self):
        """Exact-duplicate preference is rejected."""
        mem, path = self._make_memory()
        try:
            mem._preferences.append("User prefers short answers")
            mock_groq = MagicMock()
            mock_groq.chat.completions.create.return_value = MagicMock(
                choices=[MagicMock(
                    message=MagicMock(content='["User prefers short answers"]')
                )]
            )
            result = mem.extract_and_store_preferences("whatever", "ok", mock_groq)
            self.assertEqual(result, [])
            self.assertEqual(len(mem._preferences), 1)
        finally:
            os.unlink(path)

    def test_preference_llm_returns_empty_array(self):
        """LLM returning [] causes no update to _preferences."""
        mem, path = self._make_memory()
        try:
            mock_groq = MagicMock()
            mock_groq.chat.completions.create.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content="[]"))]
            )
            result = mem.extract_and_store_preferences("hello", "hi", mock_groq)
            self.assertEqual(result, [])
            self.assertEqual(mem._preferences, [])
        finally:
            os.unlink(path)

    def test_preference_fact_distinction_via_prompt_call(self):
        """
        Verify that extract_and_store_preferences uses a DIFFERENT LLM call
        than extract_and_store — the two should make independent groq calls.
        Both can run against the same mock; we just check each is called once
        for its own method.
        """
        mem, path = self._make_memory()
        try:
            mock_groq = MagicMock()
            mock_groq.chat.completions.create.side_effect = [
                # Call 1 — facts extraction
                MagicMock(choices=[MagicMock(message=MagicMock(
                    content='["User is named Alex"]'
                ))]),
                # Call 2 — preference extraction
                MagicMock(choices=[MagicMock(message=MagicMock(
                    content='["Keep answers brief"]'
                ))]),
            ]
            mem.extract_and_store("My name is Alex.", "Hello Alex!", mock_groq)
            mem.extract_and_store_preferences("Keep it short.", "OK.", mock_groq)
            self.assertEqual(mock_groq.chat.completions.create.call_count, 2,
                             "each memory tier should make exactly one LLM call")
            self.assertIn("User is named Alex", mem._facts)
            self.assertIn("Keep answers brief", mem._preferences)
        finally:
            os.unlink(path)


# ── Tier 3: Episodic memory ───────────────────────────────────────────────────

class TestEpisodicMemory(unittest.TestCase):
    """
    Tests for EpisodicMemory.

    All ChromaDB and sentence-transformers interactions are mocked so no
    real ML model or disk storage is required.
    """

    def _make_episodic(self):
        """
        Build an EpisodicMemory with the embedder and ChromaDB collection
        fully replaced by MagicMock objects.

        Uses plain Python lists for the fake embedding (no numpy needed).
        """
        from src.memory_episodic import EpisodicMemory

        mem = EpisodicMemory.__new__(EpisodicMemory)
        mem._lock = threading.Lock()
        mem._available = True
        mem._chroma_client = MagicMock()
        mem._collection = MagicMock()
        mem._collection.count.return_value = 0

        # Embedder returns a list of lists — avoids numpy in test env
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = [[0.0] * 384]
        mem._embedder = mock_embedder

        return mem

    # ── (a) Episodic: empty collection returns "" / [] ────────────────────────

    def test_get_episodic_prompt_empty_when_collection_empty(self):
        mem = self._make_episodic()
        mem._collection.count.return_value = 0
        self.assertEqual(mem.get_episodic_prompt("What is Python?", 5), "")

    def test_retrieve_relevant_empty_when_collection_empty(self):
        mem = self._make_episodic()
        mem._collection.count.return_value = 0
        self.assertEqual(mem.retrieve_relevant("hello", 5), [])

    # ── (b) exclude_recent filter works correctly ─────────────────────────────

    def test_exclude_recent_filter(self):
        """
        Turns within exclude_recent of current_turn_index are filtered out.

        Setup: current_turn_index=15, exclude_recent=10.
        The rolling window covers turns 6–15 (15-turn_idx ≤ 10).
        Mock returns turns [10, 5, 2].
          - turn 10: 15-10=5 ≤ 10  → EXCLUDED (inside rolling window)
          - turn 5:  15-5=10 ≤ 10  → EXCLUDED (boundary, still inside)
          - turn 2:  15-2=13 > 10  → INCLUDED (older than window)
        """
        mem = self._make_episodic()
        mem._collection.count.return_value = 20

        mem._collection.query.return_value = {
            "metadatas": [[
                {"turn_index": 10, "user_id": "default",
                 "user_msg": "msg10", "assistant_msg": "resp10"},
                {"turn_index": 5,  "user_id": "default",
                 "user_msg": "msg5",  "assistant_msg": "resp5"},
                {"turn_index": 2,  "user_id": "default",
                 "user_msg": "msg2",  "assistant_msg": "resp2"},
            ]],
            "distances": [[0.1, 0.2, 0.3]],
        }

        results = mem.retrieve_relevant(
            query="anything",
            current_turn_index=15,
            exclude_recent=10,
            top_k=5,
        )
        returned_indices = [r["turn_index"] for r in results]

        self.assertNotIn(10, returned_indices,
                         "turn 10 is within exclude_recent window → must be excluded")
        self.assertNotIn(5, returned_indices,
                         "turn 5 is at boundary (15-5=10 ≤ 10) → must be excluded")
        self.assertIn(2, returned_indices,
                      "turn 2 is outside window (15-2=13 > 10) → must be included")

    def test_exclude_recent_zero_includes_all(self):
        """
        With exclude_recent=0, no turn is filtered out (all are older than 0).
        """
        mem = self._make_episodic()
        mem._collection.count.return_value = 5

        mem._collection.query.return_value = {
            "metadatas": [[
                {"turn_index": 3, "user_id": "default",
                 "user_msg": "u3", "assistant_msg": "a3"},
                {"turn_index": 1, "user_id": "default",
                 "user_msg": "u1", "assistant_msg": "a1"},
            ]],
            "distances": [[0.1, 0.2]],
        }

        results = mem.retrieve_relevant("q", current_turn_index=5, exclude_recent=0)
        indices = [r["turn_index"] for r in results]
        self.assertIn(3, indices)
        self.assertIn(1, indices)

    # ── (c) get_episodic_prompt format ───────────────────────────────────────

    def test_get_episodic_prompt_format(self):
        mem = self._make_episodic()
        mem._collection.count.return_value = 10

        mem._collection.query.return_value = {
            "metadatas": [[
                {"turn_index": 2, "user_id": "default",
                 "user_msg": "What is Python?",
                 "assistant_msg": "It is a high-level language."},
            ]],
            "distances": [[0.15]],
        }

        prompt = mem.get_episodic_prompt("Python basics?", current_turn_index=20)
        self.assertIn("relevant past conversations", prompt)
        self.assertIn("[turn 2]", prompt)
        self.assertIn("What is Python?", prompt)
        self.assertIn("It is a high-level language.", prompt)

    # ── (d) store_turn calls upsert with correct id ───────────────────────────

    def test_store_turn_calls_upsert(self):
        mem = self._make_episodic()

        with tempfile.TemporaryDirectory() as tmpdir:
            import src.memory_episodic as _me
            original = _me._COUNTER_FILE
            _me._COUNTER_FILE = os.path.join(tmpdir, "turn_counter.json")
            try:
                mem.store_turn(
                    user_msg="Hello",
                    assistant_msg="Hi there!",
                    turn_index=7,
                    user_id="default",
                )
                mem._collection.upsert.assert_called_once()
                call_kwargs = mem._collection.upsert.call_args[1]
                self.assertEqual(call_kwargs["ids"], ["turn_default_7"])
            finally:
                _me._COUNTER_FILE = original

    # ── (e) unavailable degrades gracefully ───────────────────────────────────

    def test_unavailable_returns_empty(self):
        from src.memory_episodic import EpisodicMemory
        mem = EpisodicMemory.__new__(EpisodicMemory)
        mem._available = False
        mem._lock = threading.Lock()
        mem._embedder = None
        mem._collection = MagicMock()

        self.assertEqual(mem.retrieve_relevant("hi", 5), [])
        self.assertEqual(mem.get_episodic_prompt("hi", 5), "")
        mem.store_turn("u", "a", 0)
        mem._collection.upsert.assert_not_called()

    # ── (f) top_k cap respected ───────────────────────────────────────────────

    def test_top_k_cap(self):
        mem = self._make_episodic()
        mem._collection.count.return_value = 20

        # Return 5 old results, top_k=2
        mem._collection.query.return_value = {
            "metadatas": [[
                {"turn_index": i, "user_id": "default",
                 "user_msg": f"u{i}", "assistant_msg": f"a{i}"}
                for i in [1, 2, 3, 4, 5]
            ]],
            "distances": [[0.1, 0.15, 0.2, 0.25, 0.3]],
        }

        results = mem.retrieve_relevant("query", current_turn_index=20, top_k=2)
        self.assertLessEqual(len(results), 2, "top_k cap must be respected")


if __name__ == "__main__":
    unittest.main(verbosity=2)
