import pytest
from src.auth import get_password_hash, verify_password, create_access_token, verify_access_token
from datetime import timedelta

def test_password_hashing():
    """Test that passwords hash correctly and can be verified."""
    password = "supersecretpassword123"
    hashed = get_password_hash(password)
    
    # The hash should not be the plain text password
    assert hashed != password
    
    # Verification should succeed with the correct password
    assert verify_password(password, hashed) is True
    
    # Verification should fail with the wrong password
    assert verify_password("wrongpassword", hashed) is False

def test_jwt_token_creation_and_verification():
    """Test that JWT tokens encode data and can be decoded."""
    data = {"sub": "test_user"}
    
    # Create token with a 5 minute expiration
    token = create_access_token(data=data, expires_delta=timedelta(minutes=5))
    assert isinstance(token, str)
    
    # Verify the token
    payload = verify_access_token(token)
    assert payload is not None
    assert payload.get("sub") == "test_user"
    assert "exp" in payload  # Ensure expiration is set


from fastapi.testclient import TestClient
from server import app
from unittest.mock import patch
import os
import mongomock
from src.database import DatabaseManager

def test_auth_endpoints_and_gating():
    # Setup mock database
    mock_client = mongomock.MongoClient()
    import src.database
    import server
    
    # Save original database references
    original_db = src.database.db_manager
    original_server_db = server.db_manager
    
    # Instantiate test db manager
    test_db_manager = DatabaseManager(db_name="test_db")
    test_db_manager._client = mock_client
    test_db_manager._db = mock_client["test_db"]
    
    # Patch globally
    src.database.db_manager = test_db_manager
    server.db_manager = test_db_manager
    
    try:
        client = TestClient(app)
        
        # 1. Test registration
        resp = client.post("/api/auth/register", json={"username": "alice", "password": "password123"})
        assert resp.status_code == 200
        assert resp.json()["username"] == "alice"
        
        # Registering duplicate should fail
        resp = client.post("/api/auth/register", json={"username": "alice", "password": "password123"})
        assert resp.status_code == 400
        
        # 2. Test login
        resp = client.post("/api/auth/login", json={"username": "alice", "password": "password123"})
        assert resp.status_code == 200
        token = resp.json()["access_token"]
        assert token is not None
        
        # Login with wrong password should fail
        resp = client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
        assert resp.status_code == 401
        
        # 3. Test GET /api/auth/me
        # Missing token -> 401
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401
        
        # Valid token -> 200
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["username"] == "alice"
        
        # 4. Test Chat endpoint gating
        # When AUTH_ENABLED is "true"
        with patch.dict(os.environ, {"AUTH_ENABLED": "true"}):
            # Without token -> 401
            resp = client.post("/api/chat", json={"message": "hello"})
            assert resp.status_code == 401
            
            # With token -> 200 (Mock the agent.run to bypass actual Groq/LLM call)
            with patch("server.agent.run", return_value="Mock response"):
                resp = client.post("/api/chat", json={"message": "hello"}, headers={"Authorization": f"Bearer {token}"})
                assert resp.status_code == 200
                assert resp.json()["response"] == "Mock response"
                
        # When AUTH_ENABLED is not "true" (unset/false)
        with patch.dict(os.environ, {"AUTH_ENABLED": "false"}):
            with patch("server.agent.run", return_value="Mock response"):
                resp = client.post("/api/chat", json={"message": "hello"})
                assert resp.status_code == 200
                assert resp.json()["response"] == "Mock response"
    finally:
        src.database.db_manager = original_db
        server.db_manager = original_server_db
