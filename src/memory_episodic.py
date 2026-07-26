# src/memory_episodic.py
"""
Episodic Memory for Nova — retrieves relevant past conversation turns.

Stores and retrieves specific conversation exchanges (user/assistant pairs)
using ChromaDB + sentence-transformers embeddings, completely independent
of the RAG pipeline (nova_rag_db).

Design choices:
  - Separate ChromaDB path: ./nova_episodic_db  (sibling to ./nova_rag_db)
  - Collection: "nova_episodic"
  - Lazy SentenceTransformer load (mirroring RAGRetriever pattern) so the
    ~80 MB model is only pulled on first actual store/retrieve call.
  - Turn counter persisted in ./nova_episodic_db/turn_counter.json so it
    survives restarts (ChromaDB count() is unreliable after deletes).
  - exclude_recent filter: retrieve_relevant deliberately skips turns whose
    index is within exclude_recent of current_turn_index, because those turns
    are already present in the rolling conversation_history window passed to
    the agent — we only want OLDER relevant turns.
  - Thread-safe: all ChromaDB mutations are serialised via self._lock.
  - Graceful degradation: all methods return "" / [] when the collection is
    empty or chromadb/sentence-transformers are unavailable.
"""

import json
import os
import sys
import threading
from datetime import datetime, timezone
from typing import List, Optional


# ── Paths ─────────────────────────────────────────────────────────────────────
# Resolve relative to this file: src/memory_episodic.py → project root is ../../
_BASE_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_DB_PATH = os.path.join(_BASE_DIR, "nova_episodic_db")
_COUNTER_FILE = os.path.join(_DB_PATH, "turn_counter.json")


def _print_log(msg: str) -> None:
    """Emoji-safe stdout logger (mirrors tools/__init__.py helper)."""
    try:
        print(msg)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((msg + "\n").encode("utf-8", errors="replace"))
        sys.stdout.buffer.flush()


class EpisodicMemory:
    """
    Stores and retrieves relevant past conversation turns using ChromaDB
    + sentence-transformers (all-MiniLM-L6-v2).

    This class is fully independent of src/rag/retriever.py — it mirrors
    the same lazy-init pattern but operates on its own ./nova_episodic_db
    directory and "nova_episodic" collection.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._chroma_client = None
        self._collection = None
        self._embedder = None
        self._available = False   # False until _initialize() succeeds
        self._initialize()

    # ── Initialization ────────────────────────────────────────────────────────

    def _initialize(self) -> None:
        """Lazy-initialize ChromaDB (mirrors RAGRetriever._initialize)."""
        try:
            import chromadb
            os.makedirs(_DB_PATH, exist_ok=True)
            self._chroma_client = chromadb.PersistentClient(path=_DB_PATH)
            self._collection = self._chroma_client.get_or_create_collection(
                name="nova_episodic",
                metadata={"hnsw:space": "cosine"},
            )
            self._available = True
            _print_log("✅ Episodic memory (ChromaDB) ready")
        except ImportError:
            _print_log("⚠️  Episodic memory unavailable: chromadb not installed")
        except Exception as e:
            _print_log(f"⚠️  Episodic memory init failed: {e}")

    def _ensure_embedder(self) -> bool:
        """
        Load the SentenceTransformer model on first use.
        Returns True if the embedder is ready, False otherwise.
        Double-checked locking to avoid redundant loads under concurrency.
        """
        if self._embedder is not None:
            return True
        with self._lock:
            if self._embedder is not None:
                return True
            try:
                from sentence_transformers import SentenceTransformer
                self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
                _print_log("✅ Episodic embedder ready (all-MiniLM-L6-v2)")
                return True
            except ImportError:
                _print_log("⚠️  Episodic memory: sentence-transformers not installed")
                return False
            except Exception as e:
                _print_log(f"⚠️  Episodic embedder load failed: {e}")
                return False

    # ── Turn counter (persisted to JSON sidecar) ──────────────────────────────

    def _load_turn_counter(self) -> int:
        """Read persisted turn counter; returns 0 if file absent or corrupt."""
        try:
            if os.path.exists(_COUNTER_FILE):
                with open(_COUNTER_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return int(data.get("turn_index", 0))
        except Exception:
            pass
        return 0

    def _save_turn_counter(self, value: int) -> None:
        """Persist turn counter; must be called while holding self._lock."""
        try:
            os.makedirs(_DB_PATH, exist_ok=True)
            with open(_COUNTER_FILE, "w", encoding="utf-8") as f:
                json.dump({"turn_index": value}, f)
        except Exception as e:
            _print_log(f"⚠️  Could not save episodic turn counter: {e}")

    @property
    def next_turn_index(self) -> int:
        """
        Return the next available turn index (loaded from disk + 1 relative
        to the last stored turn).  Does NOT increment the counter — call
        store_turn() to do that.
        """
        with self._lock:
            return self._load_turn_counter()

    # ── Public API ─────────────────────────────────────────────────────────────

    def store_turn(
        self,
        user_msg: str,
        assistant_msg: str,
        turn_index: int,
        user_id: str = "default",
    ) -> None:
        """
        Embed and store a conversation exchange.

        Safe to call from a background thread (fire-and-forget).
        Does nothing gracefully if ChromaDB or the embedder are unavailable.

        Args:
            user_msg:       The user's message text.
            assistant_msg:  The assistant's response text.
            turn_index:     Monotonically increasing turn counter for this user.
            user_id:        Identifies the user (for future multi-user support).
        """
        if not self._available:
            return
        if not self._ensure_embedder():
            return

        combined = f"User: {user_msg}\nAssistant: {assistant_msg}"
        try:
            raw = self._embedder.encode([combined], show_progress_bar=False)
            # Handle both numpy ndarray (production) and plain list (tests/mocks)
            embedding = raw[0].tolist() if hasattr(raw[0], "tolist") else list(raw[0])
        except Exception as e:
            _print_log(f"⚠️  Episodic embed failed: {e}")
            return

        doc_id = f"turn_{user_id}_{turn_index}"
        metadata = {
            "turn_index": turn_index,
            "user_id": user_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_msg": user_msg[:500],       # cap stored metadata length
            "assistant_msg": assistant_msg[:500],
        }

        try:
            with self._lock:
                self._collection.upsert(
                    ids=[doc_id],
                    embeddings=[embedding],
                    documents=[combined],
                    metadatas=[metadata],
                )
                # Persist the latest turn_index so the counter survives restarts
                self._save_turn_counter(turn_index + 1)
            _print_log(f"   🧠 Episodic turn {turn_index} stored")
        except Exception as e:
            _print_log(f"⚠️  Episodic store failed: {e}")

    def retrieve_relevant(
        self,
        query: str,
        current_turn_index: int,
        exclude_recent: int = 10,
        top_k: int = 3,
        user_id: str = "default",
    ) -> List[dict]:
        """
        Retrieve the most semantically relevant past conversation turns.

        Turns whose index is within *exclude_recent* of *current_turn_index*
        are filtered out, because the rolling conversation_history window
        already covers those.

        Args:
            query:               Embedding query (usually the current user message).
            current_turn_index:  The agent's current turn counter.
            exclude_recent:      Skip turns within this many steps of the current turn.
            top_k:               Max results to return after filtering.
            user_id:             Filter to this user's turns.

        Returns:
            List of dicts: {user_msg, assistant_msg, turn_index, score}
        """
        if not self._available:
            return []
        if not self._ensure_embedder():
            return []

        try:
            with self._lock:
                count = self._collection.count()
            if count == 0:
                return []
        except Exception:
            return []

        try:
            raw = self._embedder.encode([query], show_progress_bar=False)
            # Handle both numpy ndarray (production) and plain list (tests/mocks)
            query_embedding = raw.tolist() if hasattr(raw, "tolist") else list(raw)
        except Exception as e:
            _print_log(f"⚠️  Episodic query embed failed: {e}")
            return []

        # Fetch more than top_k to have headroom after filtering recent turns
        fetch_n = min(count, top_k + exclude_recent + 5)

        try:
            with self._lock:
                results = self._collection.query(
                    query_embeddings=query_embedding,
                    n_results=fetch_n,
                    where={"user_id": user_id},
                    include=["metadatas", "distances"],
                )
        except Exception as e:
            _print_log(f"⚠️  Episodic query failed: {e}")
            return []

        if not results or not results.get("metadatas") or not results["metadatas"][0]:
            return []

        output = []
        for meta, dist in zip(results["metadatas"][0], results["distances"][0]):
            t_idx = meta.get("turn_index", 0)
            # exclude_recent filter: skip turns inside the rolling window
            if current_turn_index - t_idx <= exclude_recent:
                continue
            output.append({
                "user_msg":     meta.get("user_msg", ""),
                "assistant_msg": meta.get("assistant_msg", ""),
                "turn_index":   t_idx,
                "score":        round(1.0 - dist, 4),   # cosine distance → similarity
            })
            if len(output) >= top_k:
                break

        return output

    def get_episodic_prompt(
        self,
        query: str,
        current_turn_index: int,
    ) -> str:
        """
        Return a formatted prompt block of relevant past turns, or "" if none.

        Mirrors get_facts_prompt()'s empty-string convention so callers can
        use `if block: system_content += "\\n" + block` safely.

        Args:
            query:               The current user message to find similar past turns.
            current_turn_index:  The agent's current turn counter.
        """
        results = self.retrieve_relevant(query, current_turn_index)
        if not results:
            return ""

        lines = [
            "Here are relevant past conversations that may help "
            "(not the current conversation, but earlier ones):"
        ]
        for r in results:
            u = r["user_msg"].strip().replace("\n", " ")
            a = r["assistant_msg"].strip().replace("\n", " ")
            lines.append(f"- [turn {r['turn_index']}] User asked: {u}\n  You responded: {a}")

        return "\n".join(lines)
