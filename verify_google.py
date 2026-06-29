import os
from src.tools.google_auth import get_google_credentials
from googleapiclient.discovery import build

def verify_google_apis():
    print("🔄 Initializing Google Authentication...")
    print("If a browser window opens, please log in and grant permissions!")
    
    try:
        creds = get_google_credentials()
        if creds and creds.valid:
            print("✅ Google Credentials are valid and token.json is saved!")
            
            # Test Calendar
            print("\n📅 Testing Calendar API...")
            cal_service = build('calendar', 'v3', credentials=creds)
            calendars = cal_service.calendarList().list().execute()
            print(f"✅ Found {len(calendars.get('items', []))} calendars attached to your account.")
            
            # Test Gmail
            print("\n📧 Testing Gmail API...")
            mail_service = build('gmail', 'v1', credentials=creds)
            profile = mail_service.users().getProfile(userId='me').execute()
            print(f"✅ Successfully connected to Gmail account: {profile.get('emailAddress')}")
            
            print("\n🎉 Stage 3 Verification Complete! Google APIs are perfectly integrated.")
        else:
            print("❌ Authentication failed or was cancelled.")
    except Exception as e:
        print(f"❌ Error during verification: {e}")

if __name__ == "__main__":
    verify_google_apis()
