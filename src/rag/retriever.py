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
_BM25_PATH = os.path.join(_DB_PATH, "bm25_index.pkl")
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
        self._bm25_chunks = None
        self._bm25_model = None
        self._initialize()

    def _initialize(self):
        """Lazy-initialize ChromaDB and load metadata."""
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

        self._load_meta()

    def _ensure_embedder(self):
        """Ensure the SentenceTransformer model is loaded."""
        if self._embedder is not None:
            return
        with self._lock:
            if self._embedder is not None:
                return
            try:
                from sentence_transformers import SentenceTransformer
                self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
                print("✅ Embedding model ready (all-MiniLM-L6-v2)")
            except ImportError:
                raise ImportError("sentence-transformers not installed. Run: pip install sentence-transformers")

    def _ensure_bm25(self):
        """Load BM25 chunks and model from disk if not already cached in memory."""
        if self._bm25_model is not None:
            return True
        with self._lock:
            if self._bm25_model is not None:
                return True
            import pickle
            if os.path.exists(_BM25_PATH):
                try:
                    with open(_BM25_PATH, "rb") as f:
                        data = pickle.load(f)
                    self._bm25_chunks = data.get("chunks", [])
                    if self._bm25_chunks:
                        from rank_bm25 import BM25Okapi
                        tokenized_corpus = [self._tokenize(c["text"]) for c in self._bm25_chunks]
                        self._bm25_model = BM25Okapi(tokenized_corpus)
                        return True
                except Exception as e:
                    print(f"⚠️ Failed to load BM25 index: {e}")
            
            self._bm25_chunks = []
            self._bm25_model = None
            return False

    def _tokenize(self, text: str) -> List[str]:
        return re.findall(r'\w+', text.lower())

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
        """Split text into paragraphs and sentences, falling back to word splitting if necessary."""
        # 1. Split on paragraph breaks first
        paragraphs = text.split("\n\n")
        units = []
        
        # Regex to split on sentence boundaries (. / ? / !)
        sentence_ends = re.compile(r'(?<=[.!?])\s+')
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            # 2. Split on sentence boundaries
            sentences = sentence_ends.split(para)
            for sentence in sentences:
                sentence = re.sub(r'\s+', ' ', sentence).strip()
                if not sentence:
                    continue
                
                words = sentence.split()
                # 3. Fall back to word-level splitting only when a single sentence exceeds the chunk size
                if len(words) > chunk_size:
                    start_idx = 0
                    while start_idx < len(words):
                        end_idx = min(start_idx + chunk_size, len(words))
                        sub_sentence = " ".join(words[start_idx:end_idx])
                        if sub_sentence.strip():
                            units.append(sub_sentence)
                        if end_idx >= len(words):
                            break
                        start_idx += chunk_size - overlap
                else:
                    units.append(sentence)
        
        # Group units into chunks
        chunks = []
        i = 0
        n = len(units)
        while i < n:
            current_chunk_units = []
            current_word_count = 0
            start_i = i
            while i < n:
                unit_words = len(units[i].split())
                if current_word_count + unit_words > chunk_size:
                    break
                current_chunk_units.append(units[i])
                current_word_count += unit_words
                i += 1
            
            if not current_chunk_units:
                # Fallback to make sure we make progress
                current_chunk_units.append(units[i])
                current_word_count += len(units[i].split())
                i += 1
                
            chunks.append(" ".join(current_chunk_units))
            
            if i >= n:
                break
                
            # Overlap logic: go back until we cover overlap words
            overlap_words = 0
            j = i - 1
            while j >= start_i and overlap_words < overlap:
                overlap_words += len(units[j].split())
                j -= 1
            next_start = j + 1
            
            # Prevent infinite loops
            if next_start == start_i:
                next_start = start_i + 1
                
            if next_start < i:
                i = next_start
                
        return chunks

    # ── Public API ────────────────────────────────────────────────────────────

    def index_pdf(self, pdf_path: str, filename: str) -> Tuple[str, int]:
        """
        Extract text from a PDF, chunk it, embed it, and store in ChromaDB.

        Returns:
            (doc_id, chunk_count)
        """
        # Ensure embedding model is loaded
        self._ensure_embedder()

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

            # --- Incremental BM25 Update ---
            self._ensure_bm25()
            # Remove old chunks for this doc_id
            self._bm25_chunks = [c for c in self._bm25_chunks if c["doc_id"] != doc_id]
            # Add new chunks
            for i, chunk_text in enumerate(chunks):
                self._bm25_chunks.append({
                    "text": chunk_text,
                    "doc_id": doc_id,
                    "filename": filename,
                    "chunk_index": i
                })
            
            # Rebuild BM25 model
            import pickle
            if self._bm25_chunks:
                from rank_bm25 import BM25Okapi
                tokenized_corpus = [self._tokenize(c["text"]) for c in self._bm25_chunks]
                self._bm25_model = BM25Okapi(tokenized_corpus)
                try:
                    os.makedirs(os.path.dirname(_BM25_PATH), exist_ok=True)
                    with open(_BM25_PATH, "wb") as f:
                        pickle.dump({"chunks": self._bm25_chunks}, f)
                except Exception as e:
                    print(f"⚠️ Failed to save BM25 index: {e}")
            else:
                self._bm25_model = None
                if os.path.exists(_BM25_PATH):
                    try:
                        os.remove(_BM25_PATH)
                    except Exception:
                        pass

        print(f"✅ Indexed '{filename}': {len(chunks)} chunks")
        return doc_id, len(chunks)

    def search(self, query: str, top_k: int = 4, doc_id: Optional[str] = None) -> List[dict]:
        """
        Semantic search over indexed documents using hybrid dense + BM25 and RRF.
        """
        if not self._meta:
            return []

        # Ensure embedding model is loaded
        self._ensure_embedder()

        query_embedding = self._embedder.encode([query], show_progress_bar=False).tolist()
        where_filter = {"doc_id": doc_id} if doc_id else None

        with self._lock:
            # guard against empty collection
            collection_count = self._collection.count()
            if collection_count == 0:
                return []

            # Ensure top_k is an integer
            try:
                top_k = int(top_k)
            except (ValueError, TypeError):
                top_k = 4

            # Ensure BM25 is loaded
            self._ensure_bm25()

            # If BM25 index does not exist yet (e.g. no documents indexed), fall back to dense-only
            if self._bm25_model is None:
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

            # 1. Sparse search (BM25)
            tokenized_query = self._tokenize(query)
            bm25_scores = self._bm25_model.get_scores(tokenized_query)
            
            # Filter and rank BM25
            ranked_bm25 = []
            for chunk, score in zip(self._bm25_chunks, bm25_scores):
                if doc_id and chunk["doc_id"] != doc_id:
                    continue
                ranked_bm25.append((chunk, score))
            ranked_bm25.sort(key=lambda x: x[1], reverse=True)

            # 2. Dense search (ChromaDB)
            # Retrieve more results to allow effective fusion
            dense_top_n = min(50, collection_count)
            results = self._collection.query(
                query_embeddings=query_embedding,
                n_results=dense_top_n,
                where=where_filter,
                include=["documents", "metadatas", "distances"],
            )
            
            ranked_dense = []
            if results and results["documents"] and results["documents"][0]:
                for text, meta, dist in zip(
                    results["documents"][0],
                    results["metadatas"][0],
                    results["distances"][0],
                ):
                    ranked_dense.append({
                        "text": text,
                        "doc_id": meta.get("doc_id", ""),
                        "filename": meta.get("filename", "unknown"),
                        "chunk_index": meta.get("chunk_index", 0),
                        "distance": dist
                    })

            # 3. Reciprocal Rank Fusion (RRF)
            rrf_scores = {}
            chunk_info = {}

            # Populate dense ranks
            for rank, item in enumerate(ranked_dense, 1):
                key = (item["doc_id"], item["chunk_index"])
                rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (60.0 + rank)
                chunk_info[key] = item

            # Populate BM25 ranks
            for rank, (item, score) in enumerate(ranked_bm25, 1):
                if rank > 50:
                    break
                key = (item["doc_id"], item["chunk_index"])
                rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (60.0 + rank)
                if key not in chunk_info:
                    chunk_info[key] = {
                        "text": item["text"],
                        "doc_id": item["doc_id"],
                        "filename": item["filename"],
                        "chunk_index": item["chunk_index"],
                        "distance": 1.0
                    }

            # Sort by RRF score descending
            sorted_keys = sorted(rrf_scores.keys(), key=lambda k: rrf_scores[k], reverse=True)
            
            output = []
            for key in sorted_keys[:top_k]:
                info = chunk_info[key]
                output.append({
                    "text": info["text"],
                    "filename": info["filename"],
                    "doc_id": info["doc_id"],
                    "chunk_index": info["chunk_index"],
                    "score": round(rrf_scores[key], 5)
                })

        return output

    def list_documents(self) -> List[dict]:
        """Return metadata for all indexed documents."""
        return list(self._meta.values())

    def delete_document(self, doc_id: str):
        """Remove all chunks of a document from ChromaDB and BM25."""
        with self._lock:
            existing = self._collection.get(where={"doc_id": doc_id})
            if existing["ids"]:
                self._collection.delete(ids=existing["ids"])
            self._meta.pop(doc_id, None)
            self._save_meta()

            # --- Update BM25 ---
            self._ensure_bm25()
            self._bm25_chunks = [c for c in self._bm25_chunks if c["doc_id"] != doc_id]
            import pickle
            if self._bm25_chunks:
                from rank_bm25 import BM25Okapi
                tokenized_corpus = [self._tokenize(c["text"]) for c in self._bm25_chunks]
                self._bm25_model = BM25Okapi(tokenized_corpus)
                try:
                    with open(_BM25_PATH, "wb") as f:
                        pickle.dump({"chunks": self._bm25_chunks}, f)
                except Exception as e:
                    print(f"⚠️ Failed to save BM25 index: {e}")
            else:
                self._bm25_model = None
                if os.path.exists(_BM25_PATH):
                    try:
                        os.remove(_BM25_PATH)
                    except Exception:
                        pass

        print(f"✅ Deleted document {doc_id}")
