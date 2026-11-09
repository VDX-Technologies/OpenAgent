"""
Tool · Gmail (IMAP + SMTP)
==========================
Read the inbox with message previews, open a full message, save reply drafts
and send email — all with a Gmail address + App Password (no OAuth flow;
generate one at https://myaccount.google.com/apppasswords).
"""

from __future__ import annotations

import email
import imaplib
import logging
import re
import smtplib
import time
from email.header import decode_header, make_header
from email.message import Message
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid, parseaddr

from config.settings import get_settings

logger = logging.getLogger(__name__)
PREVIEW_BYTES = 60_000


def _creds() -> tuple[str, str] | None:
    cfg = get_settings().gmail
    return (cfg.address, cfg.app_password) if cfg.address and cfg.app_password else None


def _decode(value: str | None) -> str:
    """Decode RFC 2047 encoded headers."""
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:
        return value or ""


def _html_text(html: str) -> str:
    from tools.web import _Text

    p = _Text()
    p.feed(html)
    return p.text()


def _body(msg: Message) -> str:
    """Readable text of a message: its text/plain part, else its HTML as text."""
    plain = html = ""
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_maintype() == "multipart" or part.get_filename():
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            continue
        if part.get_content_type() == "text/plain" and not plain:
            plain = text
        elif part.get_content_type() == "text/html" and not html:
            html = text
    text = plain or (_html_text(html) if html else "")
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _open() -> imaplib.IMAP4_SSL:
    creds = _creds()
    if not creds:
        raise PermissionError("Gmail credentials not configured — set them in Settings → Gmail.")
    imap = imaplib.IMAP4_SSL("imap.gmail.com", timeout=30)
    imap.login(*creds)
    return imap


def _fetch(imap: imaplib.IMAP4_SSL, uid: bytes | str, partial: bool) -> Message | None:
    part = f"BODY.PEEK[]<0.{PREVIEW_BYTES}>" if partial else "BODY.PEEK[]"
    status, data = imap.uid("FETCH", uid, f"({part})")
    if status != "OK" or not data or not isinstance(data[0], tuple):
        return None
    return email.message_from_bytes(data[0][1])


def _guard(fn):
    def wrap(*a, **kw):
        try:
            return fn(*a, **kw)
        except PermissionError as exc:
            return f"Error: {exc}"
        except imaplib.IMAP4.error as exc:
            return f"Error: Gmail IMAP failed ({exc}). Check the App Password and that IMAP is enabled in Gmail."
        except OSError as exc:
            return f"Error: network error: {exc}"
    wrap.__doc__ = fn.__doc__
    return wrap


@_guard
def read_gmail_inbox(limit: int = 10, unread_only: bool = True, query: str = "") -> str:
    """Recent inbox messages with id, sender, subject, date and a short preview."""
    limit = max(1, min(int(limit), 25))
    criteria = (("is:unread " if unread_only else "") + query.strip()).strip()
    with _open() as imap:
        imap.select("INBOX", readonly=True)
        if criteria:
            status, data = imap.uid("SEARCH", None, "X-GM-RAW", '"' + criteria.replace('"', '\\"') + '"')
        else:
            status, data = imap.uid("SEARCH", None, "ALL")
        if status != "OK":
            return "Error: IMAP search failed."
        lines = []
        for uid in data[0].split()[-limit:][::-1]:
            msg = _fetch(imap, uid, partial=True)
            if msg is None:
                continue
            preview = re.sub(r"\s+", " ", _body(msg))[:280]
            lines.append(f"• [id {uid.decode()}] {_decode(msg['From'])} — {_decode(msg['Subject'])} ({msg['Date']})\n  {preview}")
    return "\n".join(lines) or "No matching emails."


@_guard
def read_gmail_message(message_id: str) -> str:
    """Full text of one inbox message (id from read_gmail_inbox)."""
    with _open() as imap:
        imap.select("INBOX", readonly=True)
        msg = _fetch(imap, str(message_id), partial=False)
    if msg is None:
        return f"Error: no message with id {message_id}."
    body = _body(msg)
    return (f"From: {_decode(msg['From'])}\nTo: {_decode(msg['To'])}\nDate: {msg['Date']}\n"
            f"Subject: {_decode(msg['Subject'])}\n\n{body[:10000]}" + ("\n…(truncated)" if len(body) > 10000 else ""))


def _drafts_box(imap: imaplib.IMAP4_SSL) -> str:
    """Gmail's drafts folder (its name depends on the account language)."""
    status, boxes = imap.list()
    for raw in boxes or []:
        line = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
        if "\\Drafts" in line:
            return line.rsplit(' "/" ', 1)[-1].strip()
    return '"[Gmail]/Drafts"'


@_guard
def gmail_create_draft(to: str, subject: str, body: str, reply_to_id: str = "") -> str:
    """Save an email as a Gmail draft (optionally as a reply to an inbox message) for the user to review."""
    creds = _creds()
    assert creds
    msg = MIMEText(body, "plain", "utf-8")
    with _open() as imap:
        if reply_to_id:
            imap.select("INBOX", readonly=True)
            orig = _fetch(imap, str(reply_to_id), partial=True)
            if orig is not None:
                if orig["Message-ID"]:
                    msg["In-Reply-To"] = orig["Message-ID"]
                    msg["References"] = f"{orig.get('References', '')} {orig['Message-ID']}".strip()
                subject = subject or "Re: " + re.sub(r"^(re:\s*)+", "", _decode(orig["Subject"]), flags=re.I)
                to = to or parseaddr(_decode(orig["Reply-To"] or orig["From"]))[1]
        msg["From"], msg["To"], msg["Subject"] = creds[0], to, subject
        msg["Date"], msg["Message-ID"] = formatdate(localtime=True), make_msgid()
        status, _ = imap.append(_drafts_box(imap), "\\Draft", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
    if status != "OK":
        return "Error: Gmail did not accept the draft."
    return f"Draft saved in Gmail: “{subject}” to {to}. The user can review and send it from Gmail."


def send_email(to: str, subject: str, body: str, html: bool = False) -> str:
    """Send an email via Gmail SMTP."""
    creds = _creds()
    if not creds:
        return "Error: Gmail credentials not configured — set them in Settings → Gmail."
    message = MIMEMultipart("alternative")
    message["From"], message["To"], message["Subject"] = creds[0], to, subject
    message.attach(MIMEText(body, "html" if html else "plain", "utf-8"))
    cfg = get_settings().gmail
    try:
        with smtplib.SMTP(cfg.smtp_server, cfg.smtp_port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(*creds)
            server.sendmail(creds[0], to, message.as_string())
        logger.info("Email sent to %s — subject: %s", to, subject)
        return f"Email sent successfully to {to}."
    except smtplib.SMTPAuthenticationError:
        return "Error: Gmail authentication failed. Check your App Password."
    except smtplib.SMTPException as exc:
        return f"Error: SMTP error: {exc}"
    except OSError as exc:
        return f"Error: network error while sending email: {exc}"


TOOL_DESCRIPTORS = [
    {
        "name": "read_gmail_inbox",
        "description": "List recent Gmail messages: id, sender, subject, date and a preview of the text. Supports Gmail search syntax.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max messages (default 10)"},
                "unread_only": {"type": "boolean", "description": "Only unread (default true)"},
                "query": {"type": "string", "description": "Gmail search, e.g. 'from:boss newer_than:2d'"},
            },
        },
    },
    {
        "name": "read_gmail_message",
        "description": "Read the full text of one Gmail message by its id (from read_gmail_inbox).",
        "parameters": {"type": "object", "properties": {"message_id": {"type": "string"}}, "required": ["message_id"]},
    },
    {
        "name": "gmail_create_draft",
        "description": "Save an email as a Gmail draft for the user to review — prefer this over send_email when "
                       "replying. With reply_to_id it replies in the same thread (to/subject can be empty then).",
        "parameters": {
            "type": "object",
            "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"},
                           "reply_to_id": {"type": "string", "description": "id of the message being answered"}},
            "required": ["body"],
        },
    },
    {
        "name": "send_email",
        "description": "Send an email right away via Gmail.",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "html": {"type": "boolean", "description": "Treat body as HTML"},
            },
            "required": ["to", "subject", "body"],
        },
    },
]

TOOLS = {
    "read_gmail_inbox": read_gmail_inbox, "read_gmail_message": read_gmail_message,
    "gmail_create_draft": lambda body, to="", subject="", reply_to_id="": gmail_create_draft(to, subject, body, reply_to_id),
    "send_email": send_email,
}
