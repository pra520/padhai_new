"""Outbound email for the contact form.

Three ways to send, tried in order — configure whichever you can get a key for:

    1. Resend      RESEND_API_KEY    100 emails/day free, 2 minutes to set up
    2. Brevo       BREVO_API_KEY     300 emails/day free
    3. SMTP        SMTP_USER + SMTP_PASS   any mailbox, including Gmail

Sending is best-effort by design. The contact route stores every message in
SQLite *before* attempting delivery, so a missing key or a provider outage
loses nothing — the message is still readable in the database and in the admin
endpoint. That is deliberate: a contact form that silently drops mail because
a key expired is worse than one that never pretended to send.
"""
import logging
import re
import smtplib
import ssl
from email.message import EmailMessage

import requests

from config import Config

log = logging.getLogger("padhai.mail")

TIMEOUT = 20
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]{2,}$")


class MailError(RuntimeError):
    """No configured transport could deliver the message."""


def valid_email(address: str) -> bool:
    return bool(EMAIL_RE.match((address or "").strip()))


def configured() -> list[str]:
    """Which transports are usable right now."""
    out = []
    if Config.RESEND_API_KEY:
        out.append("resend")
    if Config.BREVO_API_KEY:
        out.append("brevo")
    if Config.SMTP_USER and Config.SMTP_PASS:
        out.append("smtp")
    return out


def status() -> dict:
    """Public status. Deliberately does NOT include the destination address —
    that endpoint is unauthenticated, and publishing an inbox invites spam."""
    ready = configured()
    return {
        "ready": bool(ready),
        "transports": ready,
        "configured": bool(Config.CONTACT_TO),
    }


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------

def _resend(subject: str, text: str, html: str, reply_to: str) -> None:
    r = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {Config.RESEND_API_KEY}",
                 "Content-Type": "application/json"},
        json={
            "from": Config.CONTACT_FROM,
            "to": [Config.CONTACT_TO],
            "subject": subject,
            "text": text,
            "html": html,
            **({"reply_to": reply_to} if reply_to else {}),
        },
        timeout=TIMEOUT,
    )
    if r.status_code >= 400:
        raise MailError(f"resend HTTP {r.status_code}: {r.text[:200]}")


def _brevo(subject: str, text: str, html: str, reply_to: str) -> None:
    sender = Config.CONTACT_FROM
    # Brevo wants the bare address, not "Name <addr>"
    m = re.search(r"<([^>]+)>", sender)
    sender_email = m.group(1) if m else sender

    r = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={"api-key": Config.BREVO_API_KEY,
                 "Content-Type": "application/json"},
        json={
            "sender": {"email": sender_email, "name": "Padhai"},
            "to": [{"email": Config.CONTACT_TO}],
            "subject": subject,
            "textContent": text,
            "htmlContent": html,
            **({"replyTo": {"email": reply_to}} if reply_to else {}),
        },
        timeout=TIMEOUT,
    )
    if r.status_code >= 400:
        raise MailError(f"brevo HTTP {r.status_code}: {r.text[:200]}")


def _smtp(subject: str, text: str, html: str, reply_to: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = Config.CONTACT_FROM
    msg["To"] = Config.CONTACT_TO
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    context = ssl.create_default_context()
    try:
        if Config.SMTP_PORT == 465:
            with smtplib.SMTP_SSL(Config.SMTP_HOST, 465, timeout=TIMEOUT,
                                  context=context) as s:
                s.login(Config.SMTP_USER, Config.SMTP_PASS)
                s.send_message(msg)
        else:
            with smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT,
                              timeout=TIMEOUT) as s:
                s.starttls(context=context)
                s.login(Config.SMTP_USER, Config.SMTP_PASS)
                s.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError(
            "SMTP login rejected. With Gmail you must use a 16-character App "
            f"Password, not your normal password. ({exc.smtp_code})"
        ) from exc
    except Exception as exc:
        raise MailError(f"smtp: {exc}") from exc


_TRANSPORTS = {"resend": _resend, "brevo": _brevo, "smtp": _smtp}


# ---------------------------------------------------------------------------

def send_contact(name: str, email: str, subject: str, message: str) -> str:
    """Deliver one contact-form message. Returns the transport that worked.

    Raises MailError when nothing is configured or every transport failed —
    the caller has already stored the message, so this is not data loss.
    """
    ready = configured()
    if not ready:
        raise MailError("No email transport is configured.")
    if not Config.CONTACT_TO:
        raise MailError("CONTACT_TO is not set — nowhere to deliver to.")

    subject_line = f"[Padhai] {subject or 'New message'}"
    text = (
        f"New message from the Padhai contact form\n"
        f"{'-' * 44}\n"
        f"Name    : {name}\n"
        f"Email   : {email}\n"
        f"Subject : {subject or '(none)'}\n\n"
        f"{message}\n"
    )
    html = (
        '<div style="font-family:Segoe UI,system-ui,sans-serif;max-width:600px">'
        '<h2 style="color:#3562f6;margin:0 0 4px">New Padhai message</h2>'
        f'<p style="color:#5c6a89;margin:0 0 18px">from {_esc(name)} '
        f'&lt;{_esc(email)}&gt;</p>'
        f'<p style="margin:0 0 6px"><b>Subject:</b> {_esc(subject) or "(none)"}</p>'
        '<div style="background:#f7f9fe;border:1px solid #dde4f2;border-radius:10px;'
        'padding:14px 16px;white-space:pre-wrap;line-height:1.6">'
        f'{_esc(message)}</div>'
        f'<p style="margin-top:18px"><a href="mailto:{_esc(email)}" '
        'style="color:#3562f6">Reply to sender</a></p></div>'
    )

    errors = []
    for name_ in ready:
        try:
            _TRANSPORTS[name_](subject_line, text, html,
                               email if valid_email(email) else "")
            log.info("Contact message delivered via %s", name_)
            return name_
        except Exception as exc:
            log.warning("Mail transport %s failed: %s", name_, exc)
            errors.append(f"{name_}: {exc}")
    raise MailError(" | ".join(errors))


def _esc(s: str) -> str:
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))
