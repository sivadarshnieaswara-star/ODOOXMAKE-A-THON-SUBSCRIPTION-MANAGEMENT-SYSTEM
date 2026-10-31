"""Shared utilities for Brightloop services."""

import logging
from typing import Any, Sequence

from sqlalchemy.orm import Session

from ..models import Counter, EmailLog
from .mail_service import send_email as _mail_service_send_email

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


def send_email(
    db: Session,
    to: str,
    subject: str,
    body: str,
    html_body: str | None = None,
    attachments: Sequence[dict[str, Any]] | None = None,
) -> EmailLog:
    """Delegate to the central Brightloop mail service with outbox recording and SMTP delivery."""
    return _mail_service_send_email(
        db=db,
        to=to,
        subject=subject,
        body=body,
        html_body=html_body,
        attachments=attachments,
    )
