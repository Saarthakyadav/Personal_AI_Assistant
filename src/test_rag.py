import pytest
import os
import tempfile
import shutil
from unittest.mock import MagicMock
from src.rag.retriever import RAGRetriever

def test_sentence_aware_chunking():
    retriever = RAGRetriever()
    
    # 1. Standard text that splits on paragraph and sentence boundaries
    text = (
        "This is paragraph one sentence one. This is paragraph one sentence two!\n\n"
        "This is paragraph two sentence one? This is paragraph two sentence two."
    )
    
    chunks = retriever._chunk_text(text, chunk_size=10, overlap=2)
    assert len(chunks) > 0
    # Ensure paragraphs/sentences are split properly and word-based sizes are kept reasonable
    for chunk in chunks:
        assert len(chunk.split()) <= 10

def test_lazy_embedder_loading():
    retriever = RAGRetriever()
    
    # Verify that the embedder is initially None (Fix #8 lazy load)
    assert retriever._embedder is None
    
    # Run _ensure_embedder
    retriever._ensure_embedder()
    assert retriever._embedder is not None

def test_hybrid_search_fallback():
    # Setup temporary directory for DB to avoid polluting the workspace
    tmp_db_path = tempfile.mkdtemp()
    
    # Patch retriever db paths
    import src.rag.retriever
    old_db_path = src.rag.retriever._DB_PATH
    old_meta_file = src.rag.retriever._META_FILE
    old_bm25_path = src.rag.retriever._BM25_PATH
    
    src.rag.retriever._DB_PATH = tmp_db_path
    src.rag.retriever._META_FILE = os.path.join(tmp_db_path, "documents_meta.json")
    src.rag.retriever._BM25_PATH = os.path.join(tmp_db_path, "bm25_index.pkl")
    
    try:
        retriever = RAGRetriever()
        
        # When no documents are indexed, search should return empty list and not crash
        results = retriever.search("test query")
        assert results == []
        
    finally:
        # Restore paths and clean up
        src.rag.retriever._DB_PATH = old_db_path
        src.rag.retriever._META_FILE = old_meta_file
        src.rag.retriever._BM25_PATH = old_bm25_path
        try:
            shutil.rmtree(tmp_db_path)
        except Exception:
            pass
