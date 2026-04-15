"""
Email outreach sender using SendGrid.
Falls back to a preview-only mode if SendGrid is not configured.
"""

import logging
from jinja2 import Environment, FileSystemLoader, select_autoescape
from config import get_settings
from pathlib import Path

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "data" / "email_templates"


def _get_jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
    )


def render_email(template_name: str, context: dict) -> tuple[str, str]:
    """Render an email template. Returns (subject, body)."""
    env = _get_jinja_env()
    template = env.get_template(f"{template_name}.j2")
    rendered = template.render(**context)

    # Split subject from body (first line is subject)
    lines = rendered.strip().split("\n")
    subject = ""
    body_lines = []
    for i, line in enumerate(lines):
        if line.startswith("Subject:"):
            subject = line.replace("Subject:", "").strip()
        else:
            body_lines.append(line)
    body = "\n".join(body_lines).strip()
    return subject, body


async def send_outreach_email(
    to_email: str,
    to_name: str,
    domain_name: str,
    asking_price: float,
    template_name: str = "initial_offer",
) -> dict:
    """
    Send an outreach email. Returns {"sent": bool, "preview": str, "error": str|None}
    """
    settings = get_settings()

    context = {
        "domain_name": domain_name,
        "asking_price": f"${asking_price:,.0f}",
        "sender_name": settings.outreach_from_name,
        "to_name": to_name or "Domain Owner",
    }

    try:
        subject, body = render_email(template_name, context)
    except Exception as e:
        return {"sent": False, "preview": "", "error": f"Template error: {e}"}

    preview = f"To: {to_email}\nSubject: {subject}\n\n{body}"

    if not settings.sendgrid_api_key:
        logger.warning("SendGrid not configured — email preview only (not sent).")
        return {"sent": False, "preview": preview, "error": "SendGrid API key not set (preview only)"}

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        message = Mail(
            from_email=(settings.outreach_from_email, settings.outreach_from_name),
            to_emails=to_email,
            subject=subject,
            plain_text_content=body,
        )
        sg = SendGridAPIClient(settings.sendgrid_api_key)
        response = sg.send(message)

        if response.status_code in (200, 201, 202):
            logger.info(f"Outreach email sent to {to_email} for {domain_name}")
            return {"sent": True, "preview": preview, "error": None}
        else:
            return {
                "sent": False,
                "preview": preview,
                "error": f"SendGrid returned status {response.status_code}",
            }
    except Exception as e:
        logger.exception(f"Failed to send email to {to_email}")
        return {"sent": False, "preview": preview, "error": str(e)}
