# src/tools/email_tool.py
import json
import base64
from email.message import EmailMessage
from typing import Optional
from googleapiclient.discovery import build

from src.tools import Tool
from src.tools.google_auth import get_google_credentials

# ── 1. draft_email ────────────────────────────────────────────────────────────

def _draft_email(to: str, subject: str, body: str, cc: Optional[str] = None) -> str:
    """Create a draft directly in Gmail."""
    try:
        creds = get_google_credentials()
        service = build('gmail', 'v1', credentials=creds)
    except Exception as e:
        return json.dumps({"error": f"Failed to authenticate with Google: {e}"})

    message = EmailMessage()
    message.set_content(body)
    message['To'] = to
    message['Subject'] = subject
    if cc:
        message['Cc'] = cc

    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    create_message = {'message': {'raw': encoded_message}}

    try:
        draft = service.users().drafts().create(userId='me', body=create_message).execute()
        draft_id = draft.get('id')
        return json.dumps({
            "draft_id": draft_id,
            "preview": {
                "to": to,
                "cc": cc or "(none)",
                "subject": subject,
                "body_preview": body[:300] + ("..." if len(body) > 300 else ""),
            },
            "status": "draft_created",
            "note": "Draft saved securely to your Gmail drafts folder.",
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Failed to create Gmail draft: {e}"})

DRAFT_EMAIL = Tool(
    name="draft_email",
    description=(
        "Create an email draft in the user's real Gmail account. Returns a draft_id. "
        "Use this first so the user can see what will be sent before confirming. "
        "To actually send, call send_email with the draft_id."
    ),
    parameters={
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Recipient email address."},
            "subject": {"type": "string", "description": "Email subject line."},
            "body": {"type": "string", "description": "Email body text (plain text or simple HTML)."},
            "cc": {"type": "string", "description": "Optional CC email address."},
        },
        "required": ["to", "subject", "body"],
    },
    handler=_draft_email,
    requires_confirmation=False,
)

# ── 2. send_email ─────────────────────────────────────────────────────────────

def _send_email(draft_id: Optional[str] = None, to: Optional[str] = None,
                subject: Optional[str] = None, body: Optional[str] = None) -> str:
    """Send an email via Gmail API."""
    try:
        creds = get_google_credentials()
        service = build('gmail', 'v1', credentials=creds)
    except Exception as e:
        return json.dumps({"error": f"Failed to authenticate with Google: {e}"})

    try:
        if draft_id:
            sent_message = service.users().drafts().send(userId='me', body={'id': draft_id}).execute()
            return json.dumps({
                "status": "sent",
                "message_id": sent_message.get('id'),
                "note": f"Draft {draft_id} sent successfully."
            })
        else:
            if not to or not subject or not body:
                return json.dumps({"error": "Missing required fields (to, subject, body)."})
            
            message = EmailMessage()
            message.set_content(body)
            message['To'] = to
            message['Subject'] = subject

            encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
            create_message = {'raw': encoded_message}

            sent_message = service.users().messages().send(userId='me', body=create_message).execute()
            
            return json.dumps({
                "status": "sent",
                "to": to,
                "subject": subject,
                "message_id": sent_message.get('id')
            })
    except Exception as e:
        return json.dumps({"error": f"Failed to send email: {e}"})

SEND_EMAIL = Tool(
    name="send_email",
    description=(
        "Send an email via Gmail API. ALWAYS call draft_email first to show the user a preview. "
        "Then call this with the draft_id to actually send."
    ),
    parameters={
        "type": "object",
        "properties": {
            "draft_id": {"type": "string", "description": "The draft ID returned by draft_email. Preferred approach."},
            "to": {"type": "string", "description": "Recipient email (only if not using draft_id)."},
            "subject": {"type": "string", "description": "Subject (only if not using draft_id)."},
            "body": {"type": "string", "description": "Body (only if not using draft_id)."},
        },
        "required": [],
    },
    handler=_send_email,
    requires_confirmation=True,
)

# ── 3. list_emails ────────────────────────────────────────────────────

def _list_emails(count: int = 10, label_ids: str = "INBOX") -> str:
    """Fetch recent emails from Gmail via API."""
    try:
        creds = get_google_credentials()
        service = build('gmail', 'v1', credentials=creds)
    except Exception as e:
        return json.dumps({"error": f"Failed to authenticate with Google: {e}"})

    try:
        labels = [label.strip() for label in label_ids.split(',')]
        results = service.users().messages().list(userId='me', labelIds=labels, maxResults=count).execute()
        messages = results.get('messages', [])

        emails = []
        for msg in messages:
            msg_data = service.users().messages().get(userId='me', id=msg['id'], format='metadata', metadataHeaders=['From', 'Subject', 'Date']).execute()
            headers = msg_data.get('payload', {}).get('headers', [])
            
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '(No Subject)')
            sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Unknown')
            date = next((h['value'] for h in headers if h['name'].lower() == 'date'), 'Unknown')
            
            emails.append({
                "id": msg['id'],
                "from": sender,
                "subject": subject,
                "date": date,
                "snippet": msg_data.get('snippet', '')
            })

        return json.dumps({
            "emails": emails,
            "count": len(emails),
            "labels": label_ids
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch emails via Gmail API: {e}"})

LIST_EMAILS = Tool(
    name="list_emails",
    description="Fetch and list recent emails from the user's Gmail using the official API.",
    parameters={
        "type": "object",
        "properties": {
            "count": {"type": "integer", "description": "Number of recent emails to fetch (default: 10)."},
            "label_ids": {"type": "string", "description": "Comma separated labels e.g. INBOX, UNREAD (default: 'INBOX')."},
        },
        "required": [],
    },
    handler=_list_emails,
    requires_confirmation=False,
)

# ── Exported list ─────────────────────────────────────────────────────────────
EMAIL_TOOLS = [DRAFT_EMAIL, SEND_EMAIL, LIST_EMAILS]
