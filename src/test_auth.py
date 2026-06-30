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
