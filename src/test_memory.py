import pytest
import mongomock
from src.memory import UserMemory
from src.database import DatabaseManager

def test_user_memory_load_and_save():
    """
    Test that UserMemory properly loads and saves to MongoDB using mongomock.
    """
    # 1. Setup mock database
    mock_client = mongomock.MongoClient()
    import src.database
    src.database.db_manager = DatabaseManager(db_name="test_db")
    src.database.db_manager._client = mock_client
    src.database.db_manager._db = mock_client["test_db"]
    
    # 2. Test saving (extract_and_store will implicitly save)
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
    memory2 = UserMemory(user_id="test_user")
    assert memory2.fact_count == 1
    assert "Test User likes pytest" in memory2._facts
