"""
Tool · Gmail (SMTP)
====================
Send emails through Gmail's SMTP server using an App Password.
No OAuth flow required — just a Gmail address + App Password
(generated at https://myaccount.google.com/apppasswords).
"""

from __future__ import annotations

import logging
import email
import imaplib
import smtplib
from email.header import decode_header, make_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config.settings import get_settings

logger = logging.getLogger(__name__)


def send_email(
    to: str,
    subject: str,
    body: str,
    html: bool = False,
) -> str:
    """Send an email via Gmail SMTP.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Plain-text (or HTML) body of the email.
        html: If True, the body is treated as HTML.

    Returns:
        A human-readable confirmation or error message.
    """
    cfg = get_settings().gmail

    if not cfg.address or not cfg.app_password:
        msg = (
            "Gmail credentials not configured. "
            "Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in your .env file."
        )
        logger.error(msg)
        return f"Error: {msg}"

    message = MIMEMultipart("alternative")
    message["From"] = cfg.address
    message["To"] = to
    message["Subject"] = subject

    content_type = "html" if html else "plain"
    message.attach(MIMEText(body, content_type, "utf-8"))

    try:
        with smtplib.SMTP(cfg.smtp_server, cfg.smtp_port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(cfg.address, cfg.app_password)
            server.sendmail(cfg.address, to, message.as_string())

        logger.info("Email sent to %s — subject: %s", to, subject)
        return f"Email sent successfully to {to}."

    except smtplib.SMTPAuthenticationError:
        msg = "Gmail authentication failed. Check your App Password."
        logger.error(msg)
        return f"Error: {msg}"
    except smtplib.SMTPException as exc:
        msg = f"SMTP error: {exc}"
        logger.error(msg)
        return f"Error: {msg}"
    except OSError as exc:
        msg = f"Network error while sending email: {exc}"
        logger.error(msg)
        return f"Error: {msg}"


def _decode(value: str | None) -> str:
    """Decode RFC 2047 encoded headers."""
    return str(make_header(decode_header(value or "")))


def read_gmail_inbox(limit: int = 10, unread_only: bool = True, query: str = "") -> str:
    """List recent Gmail messages via IMAP (same App Password as SMTP).

    Args:
        limit: Max messages to return.
        unread_only: Only return unread messages.
        query: Optional Gmail search syntax (e.g. ``from:amazon``).
    """
    cfg = get_settings().gmail
    if not cfg.address or not cfg.app_password:
        return "Error: Gmail credentials not configured."
    limit = max(1, min(int(limit), 30))
    criteria = query.strip()
    if unread_only:
        criteria = f"is:unread {criteria}".strip()
    try:
        with imaplib.IMAP4_SSL("imap.gmail.com") as imap:
            imap.login(cfg.address, cfg.app_password)
            imap.select("INBOX", readonly=True)
            if criteria:
                status, data = imap.search(None, "X-GM-RAW", f'"{criteria}"')
            else:
                status, data = imap.search(None, "ALL")
            if status != "OK":
                return "Error: IMAP search failed."
            ids = data[0].split()[-limit:][::-1]
            lines = []
            for mid in ids:
                _, msg_data = imap.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                msg = email.message_from_bytes(msg_data[0][1])
                lines.append(f"• {_decode(msg['From'])} — {_decode(msg['Subject'])} ({msg['Date']})")
    except imaplib.IMAP4.error as exc:
        return f"Error: Gmail IMAP login failed ({exc}). Enable IMAP in Gmail settings."
    except OSError as exc:
        return f"Error: network error: {exc}"
    return "\n".join(lines) or "No matching emails."


# ── Tool descriptor ─────────────────────────────────────────────────

TOOL_DESCRIPTORS = [
    {
        "name": "send_email",
        "description": (
            "Send an email via Gmail SMTP. Requires GMAIL_ADDRESS and "
            "GMAIL_APP_PASSWORD to be configured in the .env file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body text"},
                "html": {
                    "type": "boolean",
                    "description": "Treat body as HTML",
                    "default": False,
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
]
TOOL_DESCRIPTORS.append(
    {
        "name": "read_gmail_inbox",
        "description": "List recent Gmail inbox messages (sender, subject, date). Supports Gmail search syntax.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max messages (default 10)"},
                "unread_only": {"type": "boolean", "description": "Only unread (default true)"},
                "query": {"type": "string", "description": "Gmail search, e.g. 'from:boss newer_than:2d'"},
            },
        },
    }
)

TOOLS = {"send_email": send_email, "read_gmail_inbox": read_gmail_inbox}
