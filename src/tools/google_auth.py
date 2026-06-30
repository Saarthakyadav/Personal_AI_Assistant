import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Combine scopes for both Calendar and Gmail
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.send'
]

_CREDENTIALS_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "credentials.json"))
_TOKEN_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "token.json"))

def get_google_credentials():
    """Gets valid user credentials from storage, or triggers the browser login flow."""
    creds = None
    
    # The file token.json stores the user's access and refresh tokens
    if os.path.exists(_TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(_TOKEN_FILE, SCOPES)
        except Exception:
            pass
            
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = _run_flow()
        else:
            creds = _run_flow()
            
        # Save the credentials for the next run
        if creds:
            with open(_TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())
                
    return creds

def _run_flow():
    if not os.path.exists(_CREDENTIALS_FILE):
        raise FileNotFoundError(
            f"Could not find {_CREDENTIALS_FILE}. "
            "Please download your OAuth client ID JSON from Google Cloud Console and save it as credentials.json in the root folder."
        )
    # This will spin up a local server and open the browser
    flow = InstalledAppFlow.from_client_secrets_file(_CREDENTIALS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)
    return creds
