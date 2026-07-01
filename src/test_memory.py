import pytest
import os
import json
import tempfile
import mongomock
from unittest.mock import patch
from src.memory import UserMemory
from src.database import DatabaseManager

def test_user_memory_load_and_save():
    """
    Test that UserMemory properly loads and saves to MongoDB using mongomock.
    """
    # 1. Setup mock database
    mock_client = mongomock.MongoClient()
    import src.database
    original_db = src.database.db_manager
    src.database.db_manager = DatabaseManager(db_name="test_db")
    src.database.db_manager._client = mock_client
    src.database.db_manager._db = mock_client["test_db"]
    
    try:
        # 2. Test saving (extract_and_store will implicitly save)
        with patch.dict(os.environ, {"MONGODB_URI": "mongodb://fake"}):
            memory = UserMemory(user_id="test_user")
        
        # We'll just manually add a fact and call _save_unlocked to bypass the LLM
        memory._facts.append("Test User likes pytest")
        with memory._lock:
            memory._save_unlocked()
            
        # 3. Verify it's in the mock DB
        col = src.database.db_manager.get_collection("memory")
        doc = col.find_one({"user_id": "test_user"})
        assert doc is not None
        assert "Test User likes pytest" in doc["facts"]
        
        # 4. Test loading (create a new instance, it should load from DB)
        with patch.dict(os.environ, {"MONGODB_URI": "mongodb://fake"}):
            memory2 = UserMemory(user_id="test_user")
        assert memory2.fact_count == 1
        assert "Test User likes pytest" in memory2._facts
    finally:
        src.database.db_manager = original_db


def test_user_memory_json_file_fallback():
    """
    Test that UserMemory falls back to a local JSON file when MONGODB_URI
    is not set — no MongoDB or mongomock needed for this path.
    """
    # Create a temp file for the JSON backend
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    tmp.close()
    tmp_path = tmp.name

    try:
        # Ensure MONGODB_URI is NOT set so file backend is used
        env = os.environ.copy()
        env.pop("MONGODB_URI", None)
        with patch.dict(os.environ, env, clear=True):
            # 1. Create a fresh memory instance — should use file backend
            mem = UserMemory(filepath=tmp_path, user_id="file_test_user")
            assert mem._use_mongo is False
            assert mem.fact_count == 0

            # 2. Add facts and save
            mem._facts.append("User likes Python")
            mem._facts.append("User lives in Delhi")
            with mem._lock:
                mem._save_unlocked()

            # 3. Verify the JSON file was written
            with open(tmp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            assert "file_test_user" in data
            assert "User likes Python" in data["file_test_user"]["facts"]
            assert "User lives in Delhi" in data["file_test_user"]["facts"]

            # 4. Create a new instance — should reload from the same file
            mem2 = UserMemory(filepath=tmp_path, user_id="file_test_user")
            assert mem2.fact_count == 2
            assert "User likes Python" in mem2._facts
            assert "User lives in Delhi" in mem2._facts
    finally:
        os.unlink(tmp_path)
