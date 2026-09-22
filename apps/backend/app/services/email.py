import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger("pipelinemedic.email")


def send_invitation_email(to_email: str, organization_name: str, invitation_url: str, inviter_name: str = "team") -> bool:
    if not settings.smtp_host or not settings.smtp_from_email:
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
