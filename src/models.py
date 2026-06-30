from pydantic import BaseModel
from typing import Optional

class UserInDB(BaseModel):
    """Represents a user stored in MongoDB."""
    username: str
    hashed_password: str

class UserCreate(BaseModel):
    """Payload for creating a new user."""
    username: str
    password: str

class Token(BaseModel):
    """JWT Token response."""
    access_token: str
    token_type: str
