from dotenv import load_dotenv
load_dotenv()

import os
from groq import Groq
from src.memory import UserMemory
from src.database import db_manager

def test_memory_extraction():
    print("🧠 Starting Memory Integration Test...")
    
    # 1. Setup Groq Client
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("❌ Error: GROQ_API_KEY is missing from your .env file!")
        print("Please add it so the AI can extract facts.")
        return
        
    client = Groq(api_key=api_key)
    print("✅ Groq client initialized.")
    
    # 2. Setup Memory with a test user
    test_user_id = "test_user_123"
    memory = UserMemory(user_id=test_user_id)
    print(f"✅ UserMemory initialized. Current facts for test user: {memory.fact_count}")
    
    # 3. Simulate a conversation
    user_msg = "Hey Nova, just wanted to let you know I finally adopted a dog today. It's a Golden Retriever named Max!"
    assistant_msg = "That is wonderful news! Max is a great name for a Golden Retriever. How old is he?"
    
    print("\n🗣️ Simulating Conversation:")
    print(f"User: {user_msg}")
    print(f"Assistant: {assistant_msg}")
    
    # 4. Trigger extraction
    print("\n⏳ Asking Groq LLM to extract facts (this takes a few seconds)...")
    new_facts = memory.extract_and_store(user_msg, assistant_msg, client)
    
    if new_facts:
        print(f"\n🎉 Success! The AI found and saved {len(new_facts)} new fact(s):")
        for fact in new_facts:
            print(f"  - {fact}")
    else:
        print("\n⚠️ The AI didn't find any facts, or the extraction failed.")
        
    # 5. Verify it made it to MongoDB
    col = db_manager.get_collection("memory")
    doc = col.find_one({"user_id": test_user_id})
    if doc:
        print("\n📂 Database Check: Successfully read facts back from MongoDB Atlas!")
    
    # 6. Cleanup
    print("\n🧹 Cleaning up test data...")
    col.delete_one({"user_id": test_user_id})
    print("✅ Test complete!")

if __name__ == "__main__":
    test_memory_extraction()
