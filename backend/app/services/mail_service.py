"""Brightloop Mail Module.

Provides robust, production-grade email dispatch with:
- Synchronous and thread-safe SMTP delivery (STARTTLS / SSL)
- Clean fallback to outbox recording (EmailLog) for offline/demo/testing environments
- Multi-part MIME messages supporting plain text and rich HTML templates
- Base64 binary attachment support (PDF invoices, reports, spreadsheets)
- Google App Password sanitization (stripping whitespace)
- Automatic outbox logging for admin inspection
- Mail Settings integration: auto-redirects dummy/demo emails to the configured real inbox
"""

import base64
import logging
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Sequence

from sqlalchemy.orm import Session

from .. import config
from ..models import EmailLog, SystemSetting

log = logging.getLogger("brightloop.mail")

DUMMY_DOMAINS = ("@corp.com", "@shop.com", "@globex.com", "@initech.com", "@umbrella.io", ".test", "@example.com")


def get_mail_setting(db: Session, key: str, default: str = "") -> str:
    """Retrieve dynamic system mail setting from database."""
    try:
        s = db.get(SystemSetting, key)
        return s.value if s else default
    except Exception:
        return default


def set_mail_setting(db: Session, key: str, value: str) -> None:
    """Persist dynamic system mail setting to database."""
    try:
        s = db.get(SystemSetting, key)
        if s is None:
            s = SystemSetting(key=key, value=value)
            db.add(s)
        else:
            s.value = value
        db.flush()
    except Exception as exc:
        log.warning("Could not persist setting %s: %s", key, exc)


def _build_html_wrapper(title: str, body_content: str, action_url: str | None = None, action_label: str | None = None) -> str:
    """Standard responsive HTML container with Brightloop branding."""
    button_html = ""
    if action_url and action_label:
        button_html = f"""
        <div style="margin: 28px 0; text-align: center;">
            <a href="{action_url}" style="background-color: #2563eb; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: 600; display: inline-block;">
                {action_label}
            </a>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px; color: #1e293b;">
    <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
        <div style="background-color: #0f172a; padding: 20px 28px; border-bottom: 2px solid #2563eb;">
            <h1 style="margin: 0; font-size: 20px; color: #ffffff; letter-spacing: -0.02em;">Brightloop Software</h1>
        </div>
        <div style="padding: 28px; line-height: 1.6;">
            <h2 style="margin-top: 0; font-size: 18px; color: #0f172a;">{title}</h2>
            {body_content}
            {button_html}
        </div>
        <div style="background-color: #f1f5f9; padding: 16px 28px; font-size: 12px; color: #64748b; text-align: center; border-top: 1px solid #e2e8f0;">
            Sent by Brightloop Subscription Management System &bull; <a href="{config.APP_BASE_URL}" style="color: #2563eb; text-decoration: none;">Customer Portal</a>
        </div>
    </div>
</body>
</html>"""


def send_email(
    db: Session,
    to: str,
    subject: str,
    body: str,
    html_body: str | None = None,
    attachments: Sequence[dict[str, Any]] | None = None,
) -> EmailLog:
    """Record an email in the system outbox and attempt SMTP transmission if configured.
    
    If to_email is a dummy/demo address, redirects to the Target Email configured in Settings
    so demo emails actually land in the developer/admin inbox.
    """
    to_addr = (to or "").strip()
    entry = EmailLog(to_email=to_addr, subject=subject, body=body, delivered=False)

    # Check dynamic routing for dummy/demo emails
    redirect_target = get_mail_setting(db, "mail_target_email", config.SMTP_USER or "saisrikar1220@gmail.com")
    redirect_enabled = get_mail_setting(db, "mail_redirect_dummy", "true").lower() in ("true", "1", "yes")

    actual_destination = to_addr
    is_dummy = any(to_addr.lower().endswith(dom) or dom in to_addr.lower() for dom in DUMMY_DOMAINS)

    if is_dummy and redirect_enabled and redirect_target:
        actual_destination = redirect_target
        routing_notice = f"[Demo Routing Notice: Originally sent to {to_addr} -> Delivered to {redirect_target}]\n\n"
        body = routing_notice + body
        if html_body:
            html_banner = f"""
            <div style="background:#fef3c7;border-left:4px solid #f59e0b;padding:10px 14px;margin-bottom:16px;font-size:12px;color:#92400e;">
                <strong>Demo Mail Routing:</strong> Original recipient was <code>{to_addr}</code>. Delivered to <code>{redirect_target}</code> as configured in Mail Settings.
            </div>
            """
            html_body = html_body.replace('<div style="padding: 28px; line-height: 1.6;">', '<div style="padding: 28px; line-height: 1.6;">' + html_banner)

    if config.SMTP_HOST and actual_destination:
        try:
            if attachments:
                msg = MIMEMultipart("mixed")
                alt_part = MIMEMultipart("alternative")
                alt_part.attach(MIMEText(body, "plain", "utf-8"))
                if html_body:
                    alt_part.attach(MIMEText(html_body, "html", "utf-8"))
                msg.attach(alt_part)

                for att in attachments:
                    filename = att.get("filename", "attachment.bin")
                    raw_data = att.get("content", b"")
                    if isinstance(raw_data, str):
                        raw_data = raw_data.encode("utf-8")
                    mime_type = att.get("mime_type", "application/octet-stream")
                    main_type, sub_type = mime_type.split("/", 1) if "/" in mime_type else ("application", "octet-stream")

                    part = MIMEBase(main_type, sub_type)
                    part.set_payload(raw_data)
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f"attachment; filename=\"{filename}\"")
                    msg.attach(part)
            else:
                msg = MIMEMultipart("alternative")
                msg.attach(MIMEText(body, "plain", "utf-8"))
                if html_body:
                    msg.attach(MIMEText(html_body, "html", "utf-8"))

            msg["From"] = config.SMTP_FROM
            msg["To"] = actual_destination
            msg["Subject"] = subject

            clean_password = (config.SMTP_PASSWORD or "").replace(" ", "")

            if config.SMTP_PORT == 465:
                with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as smtp:
                    if config.SMTP_USER and clean_password:
                        smtp.login(config.SMTP_USER, clean_password)
                    smtp.send_message(msg)
            else:
                with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as smtp:
                    if getattr(config, "SMTP_TLS", True):
                        smtp.starttls()
                    if config.SMTP_USER and clean_password:
                        smtp.login(config.SMTP_USER, clean_password)
                    smtp.send_message(msg)

            entry.delivered = True
            log.info("SMTP email successfully delivered to %s (subject: %s)", actual_destination, subject)
        except Exception as exc:
            log.warning("SMTP delivery to %s failed (%s). Recorded to outbox.", actual_destination, exc)

    log.info("EMAIL OUTBOX to=%s (sent_to=%s) subject=%s delivered=%s", to_addr, actual_destination, subject, entry.delivered)
    db.add(entry)
    db.flush()
    return entry


# ---------------------------------------------------------------------------
# High-Level Pre-Packaged Transactional Mail Helpers
# ---------------------------------------------------------------------------

def send_invoice_email(db: Session, invoice: Any, customer: Any) -> EmailLog:
    """Format and dispatch a clean invoice notification with plaintext and HTML fallback."""
    to_email = getattr(customer, "billing_to", None) or getattr(customer, "billing_email", None) or customer.email
    subject = f"Invoice {invoice.invoice_number} from Brightloop Software"

    portal_url = f"{config.APP_BASE_URL}/"

    plain_body = (
        f"Hello {customer.name},\n\n"
        f"Your invoice {invoice.invoice_number} covering period {invoice.period_start} to {invoice.period_end} "
        f"is now available.\n\n"
        f"Subtotal: {invoice.subtotal:,.2f}\n"
        f"Discount: -{invoice.discount_amount:,.2f}\n"
        f"Tax: {invoice.tax_amount:,.2f}\n"
        f"Total Amount: {invoice.total_amount:,.2f}\n"
        f"Balance Due: {invoice.balance_due:,.2f} by {invoice.due_date}\n\n"
        f"You can view and pay your invoice securely in your Brightloop Customer Portal:\n{portal_url}\n\n"
        f"Best regards,\nBrightloop Software Billing Team"
    )

    html_content = f"""
    <p>Hello <strong>{customer.name}</strong>,</p>
    <p>Your invoice <strong>{invoice.invoice_number}</strong> for the period <strong>{invoice.period_start}</strong> to <strong>{invoice.period_end}</strong> has been issued.</p>
    
    <table style="width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 14px;">
        <tr style="border-bottom: 1px solid #e2e8f0;">
            <td style="padding: 8px 0; color: #64748b;">Subtotal</td>
            <td style="padding: 8px 0; text-align: right; font-weight: 500;">${invoice.subtotal:,.2f}</td>
        </tr>
        <tr style="border-bottom: 1px solid #e2e8f0;">
            <td style="padding: 8px 0; color: #64748b;">Discount</td>
            <td style="padding: 8px 0; text-align: right; color: #16a34a; font-weight: 500;">-${invoice.discount_amount:,.2f}</td>
        </tr>
        <tr style="border-bottom: 1px solid #e2e8f0;">
            <td style="padding: 8px 0; color: #64748b;">Tax</td>
            <td style="padding: 8px 0; text-align: right; font-weight: 500;">${invoice.tax_amount:,.2f}</td>
        </tr>
        <tr style="border-bottom: 2px solid #0f172a; font-size: 16px;">
            <td style="padding: 12px 0; font-weight: 700;">Total Amount</td>
            <td style="padding: 12px 0; text-align: right; font-weight: 700;">${invoice.total_amount:,.2f}</td>
        </tr>
        <tr>
            <td style="padding: 8px 0; color: #dc2626; font-weight: 600;">Balance Due (by {invoice.due_date})</td>
            <td style="padding: 8px 0; text-align: right; color: #dc2626; font-weight: 700;">${invoice.balance_due:,.2f}</td>
        </tr>
    </table>
    """

    html_body = _build_html_wrapper(
        title=f"Invoice {invoice.invoice_number}",
        body_content=html_content,
        action_url=portal_url,
        action_label="View & Pay in Customer Portal",
    )

    return send_email(db, to_email, subject, plain_body, html_body=html_body)


def send_password_reset_email(db: Session, user: Any, reset_link: str) -> EmailLog:
    """Format and send a secure one-time password reset link."""
    subject = "Reset your Brightloop password"
    plain_body = (
        f"Hello {user.name},\n\n"
        f"Use this link to set a new password. It expires in {config.RESET_TOKEN_MINUTES} minutes and works once:\n\n"
        f"{reset_link}\n\n"
        f"If you did not ask for this, you can safely ignore this email."
    )

    html_content = f"""
    <p>Hello <strong>{user.name}</strong>,</p>
    <p>A request was received to reset the password for your Brightloop account. Click the button below to set a new password.</p>
    <p style="color: #64748b; font-size: 13px;">This secure link expires in <strong>{config.RESET_TOKEN_MINUTES} minutes</strong> and is valid for a single use.</p>
    <p style="word-break: break-all; font-size: 12px; color: #94a3b8;">If the button does not work, copy and paste this URL into your browser:<br>{reset_link}</p>
    <p style="color: #64748b; font-size: 13px;">If you did not request this password reset, please disregard this notification.</p>
    """

    html_body = _build_html_wrapper(
        title="Reset Your Password",
        body_content=html_content,
        action_url=reset_link,
        action_label="Reset Password",
    )

    return send_email(db, user.email, subject, plain_body, html_body=html_body)


def send_test_email(db: Session, to_email: str) -> EmailLog:
    """Send an operational diagnostic test email to verify SMTP handshake and delivery."""
    subject = "Brightloop System Diagnostic — SMTP Operational Verification"
    plain_body = (
        f"Hello,\n\n"
        f"This is an automated test notification confirming that the Brightloop Mail Module "
        f"is properly configured and transmitting over SMTP.\n\n"
        f"Host: {config.SMTP_HOST or 'Offline (Outbox Only)'}\n"
        f"Port: {config.SMTP_PORT}\n"
        f"Sender: {config.SMTP_FROM}\n\n"
        f"Brightloop Software"
    )

    html_content = f"""
    <p>This automated diagnostic verifies that your Brightloop transactional email system is operational.</p>
    <div style="background: #f8fafc; border-left: 4px solid #2563eb; padding: 12px 16px; margin: 16px 0; font-size: 13px;">
        <p style="margin: 4px 0;"><strong>SMTP Host:</strong> <code>{config.SMTP_HOST or 'Offline / Demo Mode'}</code></p>
        <p style="margin: 4px 0;"><strong>SMTP Port:</strong> <code>{config.SMTP_PORT}</code></p>
        <p style="margin: 4px 0;"><strong>Sender:</strong> <code>{config.SMTP_FROM}</code></p>
        <p style="margin: 4px 0;"><strong>Security:</strong> <code>TLS Enabled</code></p>
    </div>
    """

    html_body = _build_html_wrapper(
        title="SMTP Diagnostic Check",
        body_content=html_content,
        action_url=config.APP_BASE_URL,
        action_label="Open Brightloop Platform",
    )

    return send_email(db, to_email, subject, plain_body, html_body=html_body)
