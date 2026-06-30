import pytest
import mongomock
from src.database import DatabaseManager

def test_database_manager_connects():
    """
    Test that the DatabaseManager can connect and insert/read from a collection.
    """
    mock_client = mongomock.MongoClient()
    manager = DatabaseManager(db_name="test_db")
    
    manager._client = mock_client
    manager._db = mock_client["test_db"]
    
    users_collection = manager.get_collection("users")
    users_collection.insert_one({"name": "Test User", "role": "admin"})
    
    user = users_collection.find_one({"name": "Test User"})
    assert user is not None
    assert user["name"] == "Test User"
    assert user["role"] == "admin"

def test_database_manager_singleton():
    """
    Test that the db_manager exported by database.py behaves correctly.
    """
    from src.database import db_manager
    assert db_manager.db_name == "nova_assistant"
