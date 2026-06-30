import os
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from typing import Optional

class DatabaseManager:
    """
    Manages the connection to the MongoDB database.
    We use a single client instance for the application.
    """
    def __init__(self, uri: Optional[str] = None, db_name: str = "nova_assistant"):
        self.uri = uri or os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        self.db_name = db_name
        self._client: Optional[MongoClient] = None
        self._db: Optional[Database] = None

    def connect(self) -> None:
        if self._client is None:
            import certifi
            self._client = MongoClient(self.uri, tlsCAFile=certifi.where())
            self._db = self._client[self.db_name]

    def disconnect(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
            self._db = None

    def get_collection(self, collection_name: str) -> Collection:
        if self._db is None:
            self.connect()
        return self._db[collection_name]

# Global instance for easy importing
db_manager = DatabaseManager()
