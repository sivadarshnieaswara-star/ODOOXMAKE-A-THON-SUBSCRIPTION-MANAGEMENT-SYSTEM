import logging
import smtplib
from email.message import EmailMessage

from sqlalchemy.orm import Session

from .. import config
from ..models import Counter, EmailLog

log = logging.getLogger("brightloop")

PREFIXES = {"subscription": "SUB", "invoice": "INV", "payment": "PAY"}


def next_number(db: Session, kind: str) -> str:
    """Sequential, gap-free document numbers (SUB-00001, INV-00001, PAY-00001)."""
    counter = db.get(Counter, kind)
    if counter is None:
        counter = Counter(name=kind, value=0)
        db.add(counter)
    counter.value += 1
    db.flush()
    return f"{PREFIXES[kind]}-{counter.value:05d}"


def send_email(db: Session, to: str, subject: str, body: str) -> EmailLog:
    """Record the email in the outbox and deliver it over SMTP when configured."""
    entry = EmailLog(to_email=to, subject=subject, body=body, delivered=False)
    if config.SMTP_HOST:
        try:
            msg = EmailMessage()
            msg["From"], msg["To"], msg["Subject"] = config.SMTP_FROM, to, subject
            msg.set_content(body)
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as smtp:
                smtp.starttls()
                if config.SMTP_USER:
                    smtp.login(config.SMTP_USER, config.SMTP_PASSWORD or "")
                smtp.send_message(msg)
            entry.delivered = True
        except Exception:  # delivery failure must not break the business action
            log.exception("SMTP delivery to %s failed", to)
    log.info("EMAIL to=%s subject=%s\n%s", to, subject, body)
    db.add(entry)
    return entry
