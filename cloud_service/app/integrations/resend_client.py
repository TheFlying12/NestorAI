"""Resend email integration — send_email via Resend REST API (httpx, no SDK)."""
import logging
import os

import httpx

logger = logging.getLogger("cloud.integrations.resend")

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "")

_RESEND_URL = "https://api.resend.com/emails"

if not RESEND_API_KEY:
    logger.warning("RESEND_API_KEY not set — email sending disabled")


async def send_email(to: str, subject: str, html_body: str) -> None:
    """Send an email via Resend REST API.

    Silently no-ops if RESEND_API_KEY is not configured.
    Raises httpx.HTTPStatusError on Resend API errors.
    """
    if not RESEND_API_KEY:
        logger.debug("send_email skipped (no credentials): to=%s", to)
        return
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            _RESEND_URL,
            json={
                "from": RESEND_FROM_EMAIL,
                "to": [to],
                "subject": subject,
                "html": html_body,
            },
            headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
        )
        if resp.status_code >= 400:
            logger.error(
                "Resend send_email failed status=%d body=%.200s", resp.status_code, resp.text
            )
            resp.raise_for_status()
    logger.info("Email sent to=%s", to)
