"""Tests for the Brightloop mail module and SMTP email dispatch."""

import unittest.mock as mock
from datetime import date
from fastapi.testclient import TestClient

from backend.app import config
from backend.app.models import EmailLog
from backend.app.services import mail_service
from backend.app.services.common import send_email as common_send_email


def test_send_email_outbox_record(db_session):
    """Calling send_email records to EmailLog even when SMTP is unconfigured."""
    with db_session() as s:
        with mock.patch.object(config, "SMTP_HOST", None):
            entry = mail_service.send_email(
                db=s,
                to="test.customer@example.com",
                subject="Welcome to Brightloop",
                body="Hello customer, welcome to Brightloop!",
            )
            s.commit()

        assert entry is not None
        assert entry.to_email == "test.customer@example.com"
        assert entry.subject == "Welcome to Brightloop"
        assert "Hello customer" in entry.body
        assert entry.delivered is False

        # Check persistence in database
        saved = s.get(EmailLog, entry.id)
        assert saved is not None
        assert saved.to_email == "test.customer@example.com"


def test_common_send_email_delegation(db_session):
    """common.send_email seamlessly delegates to mail_service."""
    with db_session() as s:
        with mock.patch.object(config, "SMTP_HOST", None):
            entry = common_send_email(
                db=s,
                to="delegation@example.com",
                subject="Test Delegation",
                body="Delegation body text",
            )
            s.commit()
        assert entry.to_email == "delegation@example.com"
        assert entry.delivered is False


def test_send_email_smtp_starttls_success(db_session):
    """Verify SMTP STARTTLS flow on port 587."""
    mock_smtp_inst = mock.MagicMock()
    mock_smtp_cls = mock.MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = mock_smtp_inst

    with db_session() as s:
        with mock.patch.object(config, "SMTP_HOST", "smtp.example.com"), \
             mock.patch.object(config, "SMTP_PORT", 587), \
             mock.patch.object(config, "SMTP_USER", "billing@brightloop.com"), \
             mock.patch.object(config, "SMTP_PASSWORD", "secret app pass"), \
             mock.patch.object(config, "SMTP_FROM", "billing@brightloop.com"), \
             mock.patch.object(config, "SMTP_TLS", True), \
             mock.patch("smtplib.SMTP", mock_smtp_cls):

            entry = mail_service.send_email(
                db=s,
                to="customer@domain.com",
                subject="Account Activated",
                body="Your subscription is active.",
                html_body="<p>Your subscription is <strong>active</strong>.</p>",
            )

        assert entry.delivered is True
        mock_smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=10)
        mock_smtp_inst.starttls.assert_called_once()
        mock_smtp_inst.login.assert_called_once_with("billing@brightloop.com", "secretapppass")
        mock_smtp_inst.send_message.assert_called_once()


def test_send_email_smtp_ssl_port_465(db_session):
    """Verify SMTP SSL flow on port 465."""
    mock_ssl_inst = mock.MagicMock()
    mock_ssl_cls = mock.MagicMock()
    mock_ssl_cls.return_value.__enter__.return_value = mock_ssl_inst

    with db_session() as s:
        with mock.patch.object(config, "SMTP_HOST", "smtp.gmail.com"), \
             mock.patch.object(config, "SMTP_PORT", 465), \
             mock.patch.object(config, "SMTP_USER", "mailer@gmail.com"), \
             mock.patch.object(config, "SMTP_PASSWORD", "app pass 1234"), \
             mock.patch.object(config, "SMTP_FROM", "mailer@gmail.com"), \
             mock.patch("smtplib.SMTP_SSL", mock_ssl_cls):

            entry = mail_service.send_email(
                db=s,
                to="vip@client.com",
                subject="Invoice Paid",
                body="Thank you for your payment.",
            )

        assert entry.delivered is True
        mock_ssl_cls.assert_called_once_with("smtp.gmail.com", 465, timeout=10)
        mock_ssl_inst.login.assert_called_once_with("mailer@gmail.com", "apppass1234")
        mock_ssl_inst.send_message.assert_called_once()


def test_send_email_attachments(db_session):
    """Verify sending emails with file attachments."""
    mock_smtp_inst = mock.MagicMock()
    mock_smtp_cls = mock.MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = mock_smtp_inst

    with db_session() as s:
        with mock.patch.object(config, "SMTP_HOST", "smtp.example.com"), \
             mock.patch.object(config, "SMTP_PORT", 587), \
             mock.patch.object(config, "SMTP_USER", "user@test.com"), \
             mock.patch.object(config, "SMTP_PASSWORD", "pwd"), \
             mock.patch("smtplib.SMTP", mock_smtp_cls):

            attachments = [
                {
                    "filename": "invoice_INV-00001.pdf",
                    "content": b"%PDF-1.4 mock pdf data",
                    "mime_type": "application/pdf",
                }
            ]

            entry = mail_service.send_email(
                db=s,
                to="accountant@client.com",
                subject="Invoice Attached",
                body="Please see invoice attached.",
                html_body="<p>Please see invoice attached.</p>",
                attachments=attachments,
            )

        assert entry.delivered is True
        sent_msg = mock_smtp_inst.send_message.call_args[0][0]
        assert sent_msg["Subject"] == "Invoice Attached"
        payloads = sent_msg.get_payload()
        assert len(payloads) == 2


def test_smtp_failure_does_not_raise(db_session):
    """When SMTP delivery fails, exception is suppressed and recorded in outbox with delivered=False."""
    mock_smtp_cls = mock.MagicMock(side_effect=Exception("Connection refused / network down"))

    with db_session() as s:
        with mock.patch.object(config, "SMTP_HOST", "smtp.downserver.com"), \
             mock.patch.object(config, "SMTP_PORT", 587), \
             mock.patch.object(config, "SMTP_USER", "user@down.com"), \
             mock.patch.object(config, "SMTP_PASSWORD", "pass"), \
             mock.patch("smtplib.SMTP", mock_smtp_cls):

            entry = mail_service.send_email(
                db=s,
                to="user@example.com",
                subject="Network Failure Test",
                body="Body text",
            )

        assert entry is not None
        assert entry.delivered is False


def test_send_invoice_email_helper(db_session):
    """send_invoice_email formats invoice numbers, balances, and portal link."""
    with db_session() as s:
        customer = mock.MagicMock()
        customer.name = "Alice Corp"
        customer.billing_to = "accounts@corp.com"

        invoice = mock.MagicMock()
        invoice.invoice_number = "INV-99999"
        invoice.period_start = date(2026, 1, 1)
        invoice.period_end = date(2026, 1, 31)
        invoice.due_date = date(2026, 2, 10)
        invoice.subtotal = 1000.0
        invoice.discount_amount = 100.0
        invoice.tax_amount = 90.0
        invoice.total_amount = 990.0
        invoice.balance_due = 990.0

        with mock.patch.object(config, "SMTP_HOST", None):
            entry = mail_service.send_invoice_email(s, invoice, customer)

        assert entry.to_email == "accounts@corp.com"
        assert "INV-99999" in entry.subject
        assert "990.00" in entry.body


def test_staff_test_email_api(client: TestClient, admin: dict):
    """Admin can dispatch a test email via POST /api/emails/test."""
    res = client.post(
        "/api/emails/test",
        headers=admin,
        json={
            "to_email": "admin.verify@brightloop.com",
            "subject": "Diagnostic Verification",
            "body": "System health is optimal.",
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["to_email"] == "admin.verify@brightloop.com"
    assert data["subject"] == "Diagnostic Verification"
    assert "id" in data
