import logging
import smtplib
from email.message import EmailMessage

import httpx

from app.core.config import settings

logger = logging.getLogger("pipelinemedic.email")


def _resend_invitation_email(to_email: str, organization_name: str, invitation_url: str, inviter_name: str) -> bool:
    if not settings.resend_api_key or not settings.resend_from_email:
        return False

    payload = {
        "from": settings.resend_from_email,
        "to": [to_email],
        "subject": f"You are invited to join {organization_name} on PipelineMedic",
        "html": (
            "<p>Hi,</p>"
            f"<p>{inviter_name} invited you to join <strong>{organization_name}</strong> on PipelineMedic.</p>"
            f"<p><a href=\"{invitation_url}\">Accept invitation</a></p>"
            "<p>If you did not expect this invitation, you can safely ignore this email.</p>"
        ),
        "text": (
            f"Hi,\n\n{inviter_name} invited you to join {organization_name} on PipelineMedic.\n\n"
            f"Accept your invitation here: {invitation_url}\n\n"
            "If you did not expect this invitation, you can safely ignore this email."
        ),
    }
    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15.0,
        )
        if response.status_code < 400:
            return True
        logger.warning("Failed to send invitation email via Resend to %s: %s %s", to_email, response.status_code, response.text)
        return False
    except Exception as exc:  # pragma: no cover - environment-dependent delivery path
        logger.warning("Failed to send invitation email via Resend to %s: %s", to_email, exc)
        return False


def send_invitation_email(to_email: str, organization_name: str, invitation_url: str, inviter_name: str = "team") -> bool:
    if settings.resend_api_key and settings.resend_from_email:
        if _resend_invitation_email(to_email, organization_name, invitation_url, inviter_name):
            return True

    if not settings.smtp_host or not settings.smtp_from_email:
        logger.warning("Invitation email not sent to %s because no SMTP or Resend provider is configured.", to_email)
        return False

    message = EmailMessage()
    message["Subject"] = f"You are invited to join {organization_name} on PipelineMedic"
    message["From"] = settings.smtp_from_email
    message["To"] = to_email
    text = (
        f"Hi,\n\n{inviter_name} invited you to join {organization_name} on PipelineMedic.\n\n"
        f"Accept your invitation here: {invitation_url}\n\n"
        "If you did not expect this invitation, you can safely ignore this email."
    )
    html = (
        "<p>Hi,</p>"
        f"<p>{inviter_name} invited you to join <strong>{organization_name}</strong> on PipelineMedic.</p>"
        f"<p><a href=\"{invitation_url}\">Accept invitation</a></p>"
        "<p>If you did not expect this invitation, you can safely ignore this email.</p>"
    )
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_username and settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
        return True
    except Exception as exc:  # pragma: no cover - environment-dependent delivery path
        logger.warning("Failed to send invitation email to %s: %s", to_email, exc)
        return False
