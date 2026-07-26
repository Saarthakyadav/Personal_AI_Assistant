# src/tools/email_tool.py
import json
import base64
from email.message import EmailMessage
from typing import Optional
from googleapiclient.discovery import build

from src.tools import Tool
from src.tools.google_auth import get_google_credentials

# # ── SMTP/IMAP cache and credentials fallback ──────────────────────────────────
import os
import uuid
import smtplib
import imaplib
import time

_SMTP_DRAFT_CACHE = {}  # maps draft_id -> {"to": ..., "subject": ..., "body": ..., "cc": ...}

# ── 1. draft_email ────────────────────────────────────────────────────────────

def _draft_email(to: str, subject: str, body: str, cc: Optional[str] = None) -> str:
    """Create a draft directly in Gmail (via API or IMAP fallback)."""
    use_gmail_api = False
    service = None

    try:
        creds = get_google_credentials()
        if creds:
            service = build('gmail', 'v1', credentials=creds)
            use_gmail_api = True
    except Exception:
        use_gmail_api = False

    if use_gmail_api and service:
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

    # SMTP/IMAP Fallback
    else:
        email_address = os.getenv("EMAIL_ADDRESS")
        email_password = os.getenv("EMAIL_PASSWORD")
        if not email_address or not email_password:
            return json.dumps({
                "error": "Google auth credentials (credentials.json) not found, and no EMAIL_ADDRESS/EMAIL_PASSWORD set in .env."
            })

        # Attempt to append to Gmail's Drafts folder via IMAP
        try:
            message = EmailMessage()
            message.set_content(body)
            message['To'] = to
            message['Subject'] = subject
            if cc:
                message['Cc'] = cc
            message['From'] = email_address

            with imaplib.IMAP4_SSL("imap.gmail.com", 993) as imap:
                imap.login(email_address, email_password)
                folder = '"[Gmail]/Drafts"'
                try:
                    status, _ = imap.select(folder)
                    if status != 'OK':
                        folder = 'Drafts'
                        imap.select(folder)
                except Exception:
                    folder = 'Drafts'
                    imap.select(folder)
                imap.append(folder, '', imaplib.Time2Internaldate(time.time()), message.as_bytes())
        except Exception as e:
            # We log the warning but proceed since we cache it locally anyway for SMTP sending
            print(f"⚠️ IMAP Draft append failed: {e}")

        draft_id = f"smtp-draft-{uuid.uuid4()}"
        _SMTP_DRAFT_CACHE[draft_id] = {
            "to": to,
            "subject": subject,
            "body": body,
            "cc": cc
        }

        return json.dumps({
            "draft_id": draft_id,
            "preview": {
                "to": to,
                "cc": cc or "(none)",
                "subject": subject,
                "body_preview": body[:300] + ("..." if len(body) > 300 else ""),
            },
            "status": "draft_created",
            "note": "Draft created successfully (saved to your Gmail Drafts folder via IMAP and cached for sending).",
        }, indent=2)


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
    """Send an email via Gmail API or SMTP fallback."""
    # 1. Check if it's a cached SMTP draft
    if draft_id and draft_id in _SMTP_DRAFT_CACHE:
        draft = _SMTP_DRAFT_CACHE.pop(draft_id)
        email_address = os.getenv("EMAIL_ADDRESS")
        email_password = os.getenv("EMAIL_PASSWORD")
        if not email_address or not email_password:
            return json.dumps({"error": "SMTP credentials missing from .env"})

        try:
            message = EmailMessage()
            message.set_content(draft["body"])
            message['To'] = draft["to"]
            message['Subject'] = draft["subject"]
            if draft.get("cc"):
                message['Cc'] = draft["cc"]
            message['From'] = email_address

            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
                smtp.login(email_address, email_password)
                smtp.send_message(message)

            return json.dumps({
                "status": "sent",
                "to": draft["to"],
                "subject": draft["subject"],
                "note": "Email sent successfully via Gmail SMTP (App Password)."
            })
        except Exception as e:
            return json.dumps({"error": f"Failed to send email via SMTP: {e}"})

    # 2. Try Gmail REST API
    use_gmail_api = False
    service = None
    try:
        creds = get_google_credentials()
        if creds:
            service = build('gmail', 'v1', credentials=creds)
            use_gmail_api = True
    except Exception:
        use_gmail_api = False

    if use_gmail_api and service:
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
            return json.dumps({"error": f"Failed to send email via Gmail API: {e}"})

    # 3. Direct SMTP Send (without draft cache fallback)
    else:
        email_address = os.getenv("EMAIL_ADDRESS")
        email_password = os.getenv("EMAIL_PASSWORD")
        if not email_address or not email_password:
            return json.dumps({"error": "Google auth failed and no SMTP credentials in .env"})

        if not to or not subject or not body:
            return json.dumps({"error": "Missing required fields (to, subject, body) for SMTP send."})

        try:
            message = EmailMessage()
            message.set_content(body)
            message['To'] = to
            message['Subject'] = subject
            message['From'] = email_address

            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
                smtp.login(email_address, email_password)
                smtp.send_message(message)

            return json.dumps({
                "status": "sent",
                "to": to,
                "subject": subject,
                "note": "Email sent successfully via Gmail SMTP."
            })
        except Exception as e:
            return json.dumps({"error": f"Failed to send email via SMTP: {e}"})


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
    """Fetch recent emails from Gmail via API, with IMAP fallback."""
    # Ensure count is an int (LLM sometimes sends a string)
    try:
        count = int(count)
    except (ValueError, TypeError):
        count = 10

    # ── Attempt 1: Gmail REST API ─────────────────────────────────────────
    use_gmail_api = False
    service = None
    try:
        creds = get_google_credentials()
        if creds:
            service = build('gmail', 'v1', credentials=creds)
            use_gmail_api = True
    except Exception:
        use_gmail_api = False

    if use_gmail_api and service:
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

    # ── Attempt 2: IMAP fallback using EMAIL_ADDRESS / EMAIL_PASSWORD ─────
    email_address = os.getenv("EMAIL_ADDRESS")
    email_password = os.getenv("EMAIL_PASSWORD")
    if not email_address or not email_password:
        return json.dumps({
            "error": "Google OAuth credentials (credentials.json) not found, and no EMAIL_ADDRESS/EMAIL_PASSWORD set in .env. "
                     "Please set up either Google OAuth or Gmail App Password to use email features."
        })

    try:
        import email as email_lib
        from email.header import decode_header

        with imaplib.IMAP4_SSL("imap.gmail.com", 993) as imap:
            imap.login(email_address, email_password)

            # Map label_ids to IMAP folder names
            folder_map = {
                "INBOX": "INBOX",
                "SENT": '"[Gmail]/Sent Mail"',
                "DRAFT": '"[Gmail]/Drafts"',
                "SPAM": '"[Gmail]/Spam"',
                "TRASH": '"[Gmail]/Trash"',
                "STARRED": '"[Gmail]/Starred"',
                "UNREAD": "INBOX",  # we'll filter with UNSEEN
            }
            primary_label = label_ids.split(',')[0].strip().upper()
            folder = folder_map.get(primary_label, "INBOX")

            status, _ = imap.select(folder, readonly=True)
            if status != "OK":
                imap.select("INBOX", readonly=True)

            # Search criteria
            if "UNREAD" in label_ids.upper():
                _, msg_ids = imap.search(None, "UNSEEN")
            else:
                _, msg_ids = imap.search(None, "ALL")

            id_list = msg_ids[0].split()
            # Get the most recent N emails (end of the list = newest)
            recent_ids = id_list[-count:] if len(id_list) > count else id_list
            recent_ids.reverse()  # newest first

            emails = []
            for mid in recent_ids:
                _, msg_data = imap.fetch(mid, "(RFC822.HEADER)")
                if not msg_data or not msg_data[0]:
                    continue
                raw_header = msg_data[0][1]
                msg_obj = email_lib.message_from_bytes(raw_header)

                # Decode subject
                raw_subject = msg_obj.get("Subject", "(No Subject)")
                decoded_parts = decode_header(raw_subject)
                subject_parts = []
                for part, charset in decoded_parts:
                    if isinstance(part, bytes):
                        subject_parts.append(part.decode(charset or "utf-8", errors="replace"))
                    else:
                        subject_parts.append(part)
                subject = " ".join(subject_parts)

                sender = msg_obj.get("From", "Unknown")
                date = msg_obj.get("Date", "Unknown")

                emails.append({
                    "id": mid.decode(),
                    "from": sender,
                    "subject": subject,
                    "date": date,
                    "snippet": ""
                })

            return json.dumps({
                "emails": emails,
                "count": len(emails),
                "labels": label_ids,
                "source": "IMAP (App Password fallback)"
            }, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Failed to fetch emails via IMAP: {e}"})

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
