# src/tools/email_tool.py
"""
Email tools for Nova — Gmail via SMTP with App Password.

Setup:
  1. Enable 2-Step Verification on your Google account.
  2. Go to https://myaccount.google.com/apppasswords
  3. Create an App Password for "Mail".
  4. Add to .env:
       EMAIL_ADDRESS=your@gmail.com
       EMAIL_PASSWORD=xxxx-xxxx-xxxx-xxxx  (16-char app password, no spaces)

Tools:
  - draft_email   : Create a draft (preview only, safe — no confirmation needed)
  - send_email    : Send an email (REQUIRES CONFIRMATION)
  - list_emails   : List recent emails (read-only, requires IMAP)
"""

import json
import os
import smtplib
import threading
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, List

from src.tools import Tool


# ── Draft store (file-backed, persists across restarts) ───────────────────────
_DRAFTS_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "email_drafts.json"))
_drafts: dict = {}
_draft_lock = threading.Lock()


def _load_drafts():
    """Load drafts from disk."""
    global _drafts
    if not os.path.exists(_DRAFTS_FILE):
        _drafts = {}
        return
    try:
        with open(_DRAFTS_FILE, "r", encoding="utf-8") as f:
            _drafts = json.load(f).get("drafts", {})
    except Exception:
        _drafts = {}


def _save_drafts_unlocked():
    """Persist drafts to disk. Caller must hold _draft_lock."""
    try:
        data = {"drafts": _drafts, "updated_at": datetime.now().isoformat()}
        parent = os.path.dirname(_DRAFTS_FILE)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(_DRAFTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"   ⚠️ Could not save drafts: {e}")


# Load persisted drafts on import
_load_drafts()


# ── 1. draft_email ────────────────────────────────────────────────────────────

def _draft_email(to: str, subject: str, body: str, cc: Optional[str] = None) -> str:
    """Create an email draft and return a preview. Does NOT send."""
    import uuid
    draft_id = str(uuid.uuid4())[:8]
    draft = {
        "id": draft_id,
        "to": to,
        "cc": cc or "",
        "subject": subject,
        "body": body,
        "created_at": datetime.now().isoformat(),
    }
    with _draft_lock:
        _drafts[draft_id] = draft
        _save_drafts_unlocked()

    return json.dumps({
        "draft_id": draft_id,
        "preview": {
            "to": to,
            "cc": cc or "(none)",
            "subject": subject,
            "body_preview": body[:300] + ("..." if len(body) > 300 else ""),
        },
        "status": "draft_created",
        "note": "Draft created. Call send_email with this draft_id to send it (requires confirmation).",
    }, indent=2)


DRAFT_EMAIL = Tool(
    name="draft_email",
    description=(
        "Create an email draft without sending it. Returns a draft_id and preview. "
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
    """
    Send an email. Either pass draft_id (from draft_email) or all of to/subject/body.
    Uses Gmail SMTP with App Password from environment variables.
    """
    email_address = os.getenv("EMAIL_ADDRESS", "")
    email_password = os.getenv("EMAIL_PASSWORD", "")

    if not email_address or not email_password:
        return json.dumps({
            "error": "Email not configured. Add EMAIL_ADDRESS and EMAIL_PASSWORD to .env file.",
            "setup_instructions": (
                "1. Enable 2-Step Verification on Google. "
                "2. Go to myaccount.google.com/apppasswords. "
                "3. Create an App Password for Mail. "
                "4. Add EMAIL_ADDRESS=your@gmail.com and EMAIL_PASSWORD=xxxx to .env."
            )
        })

    # Resolve draft or direct fields
    if draft_id:
        with _draft_lock:
            draft = _drafts.get(draft_id)
        if not draft:
            return json.dumps({"error": f"Draft '{draft_id}' not found. Create one with draft_email first."})
        to = draft["to"]
        subject = draft["subject"]
        body = draft["body"]
        cc = draft.get("cc", "")
    else:
        if not to or not subject or not body:
            return json.dumps({
                "error": "Missing required fields. You MUST provide either: "
                         "(1) a draft_id from a previous draft_email call, OR "
                         "(2) all three fields: to, subject, and body.",
                "action_required": "Call draft_email first to create a draft, then use the returned draft_id.",
            })
        cc = ""

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = email_address
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc

        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(email_address, email_password)
            recipients = [to] + ([cc] if cc else [])
            server.sendmail(email_address, recipients, msg.as_string())

        # Remove draft after send
        if draft_id:
            with _draft_lock:
                _drafts.pop(draft_id, None)
                _save_drafts_unlocked()

        return json.dumps({
            "status": "sent",
            "to": to,
            "subject": subject,
            "sent_at": datetime.now().isoformat(),
        })
    except smtplib.SMTPAuthenticationError:
        return json.dumps({
            "error": "Gmail authentication failed. Check your EMAIL_ADDRESS and EMAIL_PASSWORD in .env.",
            "hint": "Make sure you are using an App Password, not your regular Gmail password.",
        })
    except Exception as e:
        return json.dumps({"error": f"Failed to send email: {str(e)}"})


SEND_EMAIL = Tool(
    name="send_email",
    description=(
        "Send an email via Gmail. ALWAYS call draft_email first to show the user a preview. "
        "Then call this with the draft_id to actually send. Requires EMAIL_ADDRESS and "
        "EMAIL_PASSWORD (Gmail App Password) in .env."
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
    requires_confirmation=True,  # always ask before sending
)


# ── 3. get_drafts ─────────────────────────────────────────────────────────────

def _get_drafts() -> str:
    """List all pending email drafts."""
    with _draft_lock:
        if not _drafts:
            return json.dumps({"drafts": [], "count": 0})
        drafts = [
            {
                "draft_id": d["id"],
                "to": d["to"],
                "subject": d["subject"],
                "created_at": d["created_at"],
            }
            for d in _drafts.values()
        ]
    return json.dumps({"drafts": drafts, "count": len(drafts)})


GET_DRAFTS = Tool(
    name="get_drafts",
    description="List all pending email drafts that have been created but not yet sent.",
    parameters={"type": "object", "properties": {}, "required": []},
    handler=_get_drafts,
    requires_confirmation=False,
)


# ── 4. list_emails (IMAP) ────────────────────────────────────────────────────

def _list_emails(count: int = 10, folder: str = "INBOX") -> str:
    """
    Fetch the most recent emails from the user's Gmail inbox via IMAP.
    Returns sender, subject, date, and a body snippet for each email.
    """
    import imaplib
    import email as email_lib
    from email.header import decode_header

    email_address = os.getenv("EMAIL_ADDRESS", "")
    email_password = os.getenv("EMAIL_PASSWORD", "")

    if not email_address or not email_password:
        return json.dumps({
            "error": "Email not configured. Add EMAIL_ADDRESS and EMAIL_PASSWORD to .env file.",
            "setup_instructions": (
                "1. Enable 2-Step Verification on Google. "
                "2. Go to myaccount.google.com/apppasswords. "
                "3. Create an App Password for Mail. "
                "4. Add EMAIL_ADDRESS=your@gmail.com and EMAIL_PASSWORD=xxxx to .env."
            )
        })

    try:
        # Connect to Gmail IMAP
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(email_address, email_password)
        mail.select(folder, readonly=True)

        # Search for all emails in the folder
        status, message_ids = mail.search(None, "ALL")
        if status != "OK" or not message_ids[0]:
            mail.logout()
            return json.dumps({"emails": [], "count": 0, "folder": folder})

        # Get the latest N email IDs
        id_list = message_ids[0].split()
        latest_ids = id_list[-count:]  # last N emails (most recent)
        latest_ids.reverse()           # newest first

        emails = []
        for eid in latest_ids:
            try:
                status, msg_data = mail.fetch(eid, "(RFC822)")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue

                raw_email = msg_data[0][1]
                msg = email_lib.message_from_bytes(raw_email)

                # Decode subject
                subject_raw = msg.get("Subject", "(No Subject)")
                decoded_parts = decode_header(subject_raw)
                subject = ""
                for part, charset in decoded_parts:
                    if isinstance(part, bytes):
                        subject += part.decode(charset or "utf-8", errors="replace")
                    else:
                        subject += part

                # Decode sender
                from_raw = msg.get("From", "Unknown")
                decoded_from = decode_header(from_raw)
                sender = ""
                for part, charset in decoded_from:
                    if isinstance(part, bytes):
                        sender += part.decode(charset or "utf-8", errors="replace")
                    else:
                        sender += part

                # Date
                date_str = msg.get("Date", "Unknown")

                # Extract body snippet
                body_snippet = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        content_disp = str(part.get("Content-Disposition", ""))
                        if content_type == "text/plain" and "attachment" not in content_disp:
                            try:
                                payload = part.get_payload(decode=True)
                                if payload:
                                    charset = part.get_content_charset() or "utf-8"
                                    body_snippet = payload.decode(charset, errors="replace")
                            except Exception:
                                pass
                            break
                else:
                    try:
                        payload = msg.get_payload(decode=True)
                        if payload:
                            charset = msg.get_content_charset() or "utf-8"
                            body_snippet = payload.decode(charset, errors="replace")
                    except Exception:
                        pass

                # Truncate body snippet
                body_snippet = body_snippet.strip()
                if len(body_snippet) > 300:
                    body_snippet = body_snippet[:300] + "..."

                emails.append({
                    "from": sender,
                    "subject": subject,
                    "date": date_str,
                    "snippet": body_snippet,
                })
            except Exception:
                continue

        mail.logout()

        return json.dumps({
            "emails": emails,
            "count": len(emails),
            "folder": folder,
            "total_in_folder": len(id_list),
        }, indent=2)

    except imaplib.IMAP4.error as e:
        error_msg = str(e)
        if "AUTHENTICATIONFAILED" in error_msg.upper() or "Invalid credentials" in error_msg:
            return json.dumps({
                "error": "Gmail IMAP authentication failed.",
                "hint": (
                    "Make sure: (1) IMAP is enabled in Gmail settings (Settings > Forwarding and POP/IMAP > Enable IMAP), "
                    "(2) You are using an App Password (not your regular password), "
                    "(3) EMAIL_ADDRESS and EMAIL_PASSWORD in .env are correct."
                )
            })
        return json.dumps({"error": f"IMAP error: {error_msg}"})
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch emails: {str(e)}"})


LIST_EMAILS = Tool(
    name="list_emails",
    description=(
        "Fetch and list recent emails from the user's Gmail inbox. "
        "Returns sender, subject, date, and a body preview for each email. "
        "Use this when the user asks to check, read, or list their emails. "
        "Requires EMAIL_ADDRESS and EMAIL_PASSWORD (Gmail App Password) in .env, "
        "and IMAP must be enabled in Gmail settings."
    ),
    parameters={
        "type": "object",
        "properties": {
            "count": {
                "type": "integer",
                "description": "Number of recent emails to fetch (default: 10, max: 25).",
            },
            "folder": {
                "type": "string",
                "description": "The mailbox folder to read from (default: 'INBOX'). Other options: '[Gmail]/Sent Mail', '[Gmail]/Starred', etc.",
            },
        },
        "required": [],
    },
    handler=_list_emails,
    requires_confirmation=False,
)


# ── Exported list ─────────────────────────────────────────────────────────────

EMAIL_TOOLS = [DRAFT_EMAIL, SEND_EMAIL, GET_DRAFTS, LIST_EMAILS]
