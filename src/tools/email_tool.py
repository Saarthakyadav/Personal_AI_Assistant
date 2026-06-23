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


# ── Draft store (in-memory, keyed by draft_id) ───────────────────────────────
_drafts: dict = {}
_draft_lock = threading.Lock()


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
            return json.dumps({"error": "Provide either draft_id or all of: to, subject, body."})
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


# ── Exported list ─────────────────────────────────────────────────────────────

EMAIL_TOOLS = [DRAFT_EMAIL, SEND_EMAIL, GET_DRAFTS]
