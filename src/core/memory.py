"""Free, local memory system using ChromaDB"""

import chromadb
from chromadb.utils import embedding_functions
from datetime import datetime
from typing import List, Dict, Optional
import json
import hashlib

class ConversationMemory:
    """Free, vector-based conversation memory (no API keys needed)"""
    
    def __init__(self, 
                 collection_name: str = "agentic_memory",
                 persist_directory: str = "./memory_db"):
        
        # Initialize ChromaDB (free, local)
        self.client = chromadb.PersistentClient(path=persist_directory)
        
        # Use free sentence transformers (all-MiniLM-L6-v2)
        # This runs 100% locally, no API calls
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        
        # Get or create collection
        try:
            self.collection = self.client.get_collection(
                name=collection_name,
                embedding_function=self.embedding_fn
            )
        except:
            self.collection = self.client.create_collection(
                name=collection_name,
                embedding_function=self.embedding_fn
            )
        
        self.conversation_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.message_count = 0
        
        # In-memory recent conversation
        self.recent_messages: List[Dict] = []
        
        print(f"✅ Memory system initialized")
        print(f"   Collection: {collection_name}")
        print(f"   Embedding: all-MiniLM-L6-v2 (local)")
    
    def add(self, role: str, content: str, metadata: Dict = None):
        """Add a message to memory"""
        self.message_count += 1
        
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "conversation_id": self.conversation_id
        }
        if metadata:
            message.update(metadata)
        
        # Store in recent messages (short-term)
        self.recent_messages.append(message)
        if len(self.recent_messages) > 20:
            self.recent_messages = self.recent_messages[-20:]
        
        # Store in vector database (long-term)
        doc_id = f"{self.conversation_id}_{self.message_count}"
        try:
            self.collection.add(
                documents=[f"{role}: {content}"],
                metadatas=[message],
                ids=[doc_id]
            )
        except Exception as e:
            print(f"Memory storage error: {e}")
    
    def search(self, query: str, n_results: int = 5) -> List[Dict]:
        """Search for semantically similar memories"""
        if not query.strip():
            return []
        
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results
            )
            
            memories = []
            if results['metadatas'] and results['metadatas'][0]:
                for metadata in results['metadatas'][0]:
                    memories.append(metadata)
            
            return memories
        except Exception as e:
            print(f"Memory search error: {e}")
            return []
    
    def get_recent(self, n: int = 10) -> List[Dict]:
        """Get recent conversation history"""
        return self.recent_messages[-n:]
    
    def get_conversation_context(self, max_messages: int = 10) -> str:
        """Get formatted conversation context for LLM"""
        recent = self.get_recent(max_messages)
        if not recent:
            return ""
        
        context = "Previous conversation:\n"
        for msg in recent:
            context += f"{msg['role']}: {msg['content'][:200]}\n"
        
        return context
    
    def add_user_message(self, content: str):
        """Convenience method for user message"""
        self.add("user", content)
    
    def add_assistant_message(self, content: str):
        """Convenience method for assistant message"""
        self.add("assistant", content)
    
    def clear(self):
        """Clear all memories"""
        self.collection.delete(ids=[f"{self.conversation_id}_*"])
        self.recent_messages = []
        self.message_count = 0


class ShortTermMemory:
    """In-memory buffer for current session"""
    
    def __init__(self, max_tokens: int = 4000):
        self.max_tokens = max_tokens
        self.messages: List[Dict] = []
    
    def add(self, role: str, content: str):
        """Add message to short-term memory"""
        self.messages.append({"role": role, "content": content})
        
        # Rough token limit
        total_chars = sum(len(m["content"]) for m in self.messages)
        while total_chars > self.max_tokens * 4 and len(self.messages) > 2:
            self.messages.pop(0)
            total_chars = sum(len(m["content"]) for m in self.messages)
    
    def get_all(self) -> List[Dict]:
        """Get all messages"""
        return self.messages.copy()
    
    def clear(self):
        """Clear memory"""
        self.messages = []