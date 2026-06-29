from dotenv import load_dotenv
load_dotenv()

from src.database import db_manager

try:
    print("Testing connection to MongoDB Atlas...")
    col = db_manager.get_collection("test_connection")
    
    # Try inserting a document
    col.insert_one({"status": "Success!", "message": "Stage 1 DB is connected!"})
    
    # Try reading it back
    result = col.find_one({"status": "Success!"})
    print("✅ Connection successful! Database returned:", result["message"])
    
    # Clean up the test document
    col.delete_one({"status": "Success!"})
    print("✅ Test document cleaned up. Stage 1 is fully complete.")
    
except Exception as e:
    print("❌ Connection failed:", e)
