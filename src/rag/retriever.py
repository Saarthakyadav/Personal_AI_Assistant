# src/rag/retriever.py
"""
RAG Retriever for Nova — PDF indexing and semantic search.

Dependencies:
  pip install chromadb sentence-transformers pymupdf

Uses:
  - PyMuPDF (fitz)              : PDF text extraction
  - sentence-transformers       : Local embedding model (all-MiniLM-L6-v2, ~80MB)
  - ChromaDB                    : Vector store (local, no server needed)

The ChromaDB collection is stored in ./nova_rag_db/ next to server.py.
"""

import json
import os
import hashlib
import re
from datetime import datetime
from typing import List, Tuple, Optional
import threading


# ── Paths ─────────────────────────────────────────────────────────────────────
_BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
_DB_PATH = os.path.join(_BASE_DIR, "nova_rag_db")
_META_FILE = os.path.join(_DB_PATH, "documents_meta.json")
_CHUNK_SIZE = 400      # words per chunk
_CHUNK_OVERLAP = 50   # word overlap between chunks


class RAGRetriever:
    """Manages PDF indexing and semantic search for Nova's RAG pipeline."""

    def __init__(self):
        self._lock = threading.Lock()
        self._client = None
        self._collection = None
        self._embedder = None
        self._meta: dict = {}  # doc_id → {filename, chunk_count, indexed_at}
        self._initialize()

    def _initialize(self):
        """Lazy-initialize ChromaDB and the embedding model."""
        try:
            import chromadb
            from chromadb.config import Settings
            os.makedirs(_DB_PATH, exist_ok=True)
            self._client = chromadb.PersistentClient(path=_DB_PATH)
            self._collection = self._client.get_or_create_collection(
                name="nova_documents",
                metadata={"hnsw:space": "cosine"},
            )
            print("✅ ChromaDB collection ready")
        except ImportError:
            raise ImportError("chromadb not installed. Run: pip install chromadb")

        try:
            from sentence_transformers import SentenceTransformer
            self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
            print("✅ Embedding model ready (all-MiniLM-L6-v2)")
        except ImportError:
            raise ImportError("sentence-transformers not installed. Run: pip install sentence-transformers")

        self._load_meta()

    def _load_meta(self):
        if os.path.exists(_META_FILE):
            try:
                with open(_META_FILE, "r", encoding="utf-8") as f:
                    self._meta = json.load(f)
            except Exception:
                self._meta = {}

    def _save_meta(self):
        os.makedirs(_DB_PATH, exist_ok=True)
        with open(_META_FILE, "w", encoding="utf-8") as f:
            json.dump(self._meta, f, indent=2, ensure_ascii=False)

    # ── PDF Processing ────────────────────────────────────────────────────────

    def _extract_pdf_text(self, pdf_path: str) -> str:
        """Extract all text from a PDF using PyMuPDF."""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ImportError("PyMuPDF not installed. Run: pip install pymupdf")

        text_parts = []
        with fitz.open(pdf_path) as doc:
            for page_num, page in enumerate(doc, 1):
                page_text = page.get_text("text")
                if page_text.strip():
                    text_parts.append(f"[Page {page_num}]\n{page_text}")
        return "\n\n".join(text_parts)

    def _chunk_text(self, text: str, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> List[str]:
        """Split text into overlapping word-based chunks."""
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        words = text.split()

        chunks = []
        start = 0
        while start < len(words):
            end = min(start + chunk_size, len(words))
            chunk = " ".join(words[start:end])
            if chunk.strip():
                chunks.append(chunk)
            if end >= len(words):
                break
            start += chunk_size - overlap

        return chunks

    # ── Public API ────────────────────────────────────────────────────────────

    def index_pdf(self, pdf_path: str, filename: str) -> Tuple[str, int]:
        """
        Extract text from a PDF, chunk it, embed it, and store in ChromaDB.

        Returns:
            (doc_id, chunk_count)
        """
        # Generate a stable doc ID from filename + file hash (chunked to avoid
        # loading entire file into memory for large PDFs — FIX #14)
        h = hashlib.md5()
        with open(pdf_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        file_hash = h.hexdigest()[:8]
        doc_id = f"doc_{file_hash}"

        # Extract and chunk
        raw_text = self._extract_pdf_text(pdf_path)
        chunks = self._chunk_text(raw_text)

        if not chunks:
            raise ValueError("No text could be extracted from the PDF.")

        # Embed all chunks at once (batch is faster)
        embeddings = self._embedder.encode(chunks, show_progress_bar=False).tolist()

        # Store in ChromaDB (upsert so re-uploading the same file is safe)
        with self._lock:
            # Delete existing chunks for this doc if re-indexing
            try:
                existing = self._collection.get(where={"doc_id": doc_id})
                if existing["ids"]:
                    self._collection.delete(ids=existing["ids"])
            except Exception:
                pass

            chunk_ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
            self._collection.add(
                ids=chunk_ids,
                embeddings=embeddings,
                documents=chunks,
                metadatas=[
                    {"doc_id": doc_id, "filename": filename, "chunk_index": i}
                    for i in range(len(chunks))
                ],
            )

            self._meta[doc_id] = {
                "doc_id": doc_id,
                "filename": filename,
                "chunk_count": len(chunks),
                "indexed_at": datetime.now().isoformat(),
                "size_chars": len(raw_text),
            }
            self._save_meta()

        print(f"✅ Indexed '{filename}': {len(chunks)} chunks")
        return doc_id, len(chunks)

    def search(self, query: str, top_k: int = 4, doc_id: Optional[str] = None) -> List[dict]:
        """
        Semantic search over indexed documents.

        Args:
            query:   Natural language query.
            top_k:   Number of top chunks to return.
            doc_id:  Optional: restrict search to a specific document.

        Returns:
            List of dicts with 'text', 'filename', 'score', 'doc_id'.
        """
        if not self._meta:
            return []

        query_embedding = self._embedder.encode([query], show_progress_bar=False).tolist()

        where_filter = {"doc_id": doc_id} if doc_id else None

        with self._lock:
            # FIX #3: guard against empty collection — ChromaDB raises if n_results=0
            collection_count = self._collection.count()
            if collection_count == 0:
                return []

            # Ensure top_k is an integer
            try:
                top_k = int(top_k)
            except (ValueError, TypeError):
                top_k = 4

            results = self._collection.query(
                query_embeddings=query_embedding,
                n_results=min(top_k, collection_count),
                where=where_filter,
                include=["documents", "metadatas", "distances"],
            )

        output = []
        if results and results["documents"] and results["documents"][0]:
            for text, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                output.append({
                    "text": text,
                    "filename": meta.get("filename", "unknown"),
                    "doc_id": meta.get("doc_id", ""),
                    "chunk_index": meta.get("chunk_index", 0),
                    "score": round(1 - dist, 3),  # cosine similarity
                })
        return output

    def list_documents(self) -> List[dict]:
        """Return metadata for all indexed documents."""
        return list(self._meta.values())

    def delete_document(self, doc_id: str):
        """Remove all chunks of a document from ChromaDB."""
        with self._lock:
            existing = self._collection.get(where={"doc_id": doc_id})
            if existing["ids"]:
                self._collection.delete(ids=existing["ids"])
            self._meta.pop(doc_id, None)
            self._save_meta()
        print(f"✅ Deleted document {doc_id}")
