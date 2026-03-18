"""Twilio SMS integration — send_sms and webhook signature validation via httpx (no SDK)."""
import hashlib
import hmac
import logging
import os
from base64 import b64encode

import httpx

logger = logging.getLogger("cloud.integrations.twilio")

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "")

_MESSAGES_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"

if not TWILIO_ACCOUNT_SID:
    logger.warning("TWILIO_ACCOUNT_SID not set — SMS sending disabled")


async def send_sms(to: str, body: str) -> None:
    """Send an SMS via Twilio Messages API (httpx, no SDK).

    Silently no-ops if TWILIO_ACCOUNT_SID is not configured.
    Raises httpx.HTTPStatusError on Twilio API errors.
    """
    if not TWILIO_ACCOUNT_SID:
        logger.debug("send_sms skipped (no credentials): to=%s", to)
        return
    url = _MESSAGES_URL.format(sid=TWILIO_ACCOUNT_SID)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            url,
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            data={
                "From": TWILIO_FROM_NUMBER,
                "To": to,
                "Body": body[:1600],
            },
        )
        if resp.status_code >= 400:
            logger.error(
                "Twilio send_sms failed status=%d body=%.200s", resp.status_code, resp.text
            )
            resp.raise_for_status()
    logger.info("SMS sent to=%s", to)


def validate_signature(url: str, params: dict, signature: str) -> bool:
    """Validate a Twilio webhook request signature (HMAC-SHA1).

    See: https://www.twilio.com/docs/usage/webhooks/webhooks-security
    Returns False if TWILIO_AUTH_TOKEN is not configured.
    """
    if not TWILIO_AUTH_TOKEN:
        return False
    # Build string: URL + sorted key-value pairs (no separator between them)
    s = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    mac = hmac.new(TWILIO_AUTH_TOKEN.encode("utf-8"), s.encode("utf-8"), hashlib.sha1)
    expected = b64encode(mac.digest()).decode("utf-8")
    return hmac.compare_digest(expected, signature)
