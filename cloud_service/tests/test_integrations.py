"""Unit tests for Twilio and Resend integration clients."""
import hashlib
import hmac
import unittest
from base64 import b64encode
from unittest.mock import AsyncMock, MagicMock, patch


def _make_twilio_sig(url: str, params: dict, token: str) -> str:
    """Reproduce Twilio HMAC-SHA1 signature for test fixtures."""
    s = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    mac = hmac.new(token.encode("utf-8"), s.encode("utf-8"), hashlib.sha1)
    return b64encode(mac.digest()).decode("utf-8")


# ─── Twilio signature validation ──────────────────────────────────────────────

class TestTwilioSignatureValidation(unittest.TestCase):
    def setUp(self):
        from cloud_service.app.integrations import twilio_client
        self._module = twilio_client

    def test_valid_signature(self):
        url = "https://example.com/webhooks/twilio/sms"
        params = {"From": "+14155550100", "Body": "hello", "To": "+15005550006"}
        token = "testtoken123"
        sig = _make_twilio_sig(url, params, token)
        with patch.object(self._module, "TWILIO_AUTH_TOKEN", token), \
             patch.object(self._module, "TWILIO_ACCOUNT_SID", "ACtest"):
            self.assertTrue(self._module.validate_signature(url, params, sig))

    def test_invalid_signature(self):
        url = "https://example.com/webhooks/twilio/sms"
        params = {"From": "+14155550100", "Body": "hello"}
        with patch.object(self._module, "TWILIO_AUTH_TOKEN", "testtoken"), \
             patch.object(self._module, "TWILIO_ACCOUNT_SID", "ACtest"):
            self.assertFalse(self._module.validate_signature(url, params, "badsig=="))

    def test_missing_auth_token_returns_false(self):
        with patch.object(self._module, "TWILIO_AUTH_TOKEN", ""):
            self.assertFalse(
                self._module.validate_signature("https://example.com", {}, "anysig")
            )

    def test_tampered_params_fail(self):
        """Modifying a param after signing should invalidate the signature."""
        url = "https://example.com/webhooks/twilio/sms"
        params = {"From": "+14155550100", "Body": "hello"}
        token = "securetoken"
        sig = _make_twilio_sig(url, params, token)
        tampered = {**params, "Body": "injected"}
        with patch.object(self._module, "TWILIO_AUTH_TOKEN", token), \
             patch.object(self._module, "TWILIO_ACCOUNT_SID", "ACtest"):
            self.assertFalse(self._module.validate_signature(url, tampered, sig))


# ─── send_sms payload ─────────────────────────────────────────────────────────

class TestSendSmsPayload(unittest.IsolatedAsyncioTestCase):
    async def test_send_sms_calls_twilio_api(self):
        from cloud_service.app.integrations import twilio_client

        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.raise_for_status = MagicMock()

        with patch.object(twilio_client, "TWILIO_ACCOUNT_SID", "ACtest"), \
             patch.object(twilio_client, "TWILIO_AUTH_TOKEN", "token"), \
             patch.object(twilio_client, "TWILIO_FROM_NUMBER", "+15005550006"), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await twilio_client.send_sms("+14155550100", "Test message")

            mock_client.post.assert_called_once()
            call_kwargs = mock_client.post.call_args
            # URL contains the account SID
            self.assertIn("ACtest", call_kwargs[0][0])
            data = call_kwargs[1]["data"]
            self.assertEqual(data["To"], "+14155550100")
            self.assertEqual(data["Body"], "Test message")
            self.assertEqual(data["From"], "+15005550006")

    async def test_send_sms_no_op_when_unconfigured(self):
        """No HTTP call should be made when TWILIO_ACCOUNT_SID is empty."""
        from cloud_service.app.integrations import twilio_client

        with patch.object(twilio_client, "TWILIO_ACCOUNT_SID", ""), \
             patch("httpx.AsyncClient") as mock_client_cls:
            await twilio_client.send_sms("+14155550100", "Test")
            mock_client_cls.assert_not_called()

    async def test_send_sms_truncates_long_body(self):
        from cloud_service.app.integrations import twilio_client

        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.raise_for_status = MagicMock()

        with patch.object(twilio_client, "TWILIO_ACCOUNT_SID", "ACtest"), \
             patch.object(twilio_client, "TWILIO_AUTH_TOKEN", "token"), \
             patch.object(twilio_client, "TWILIO_FROM_NUMBER", "+15005550006"), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            long_body = "x" * 2000
            await twilio_client.send_sms("+14155550100", long_body)

            data = mock_client.post.call_args[1]["data"]
            self.assertEqual(len(data["Body"]), 1600)


# ─── send_email payload ───────────────────────────────────────────────────────

class TestSendEmailPayload(unittest.IsolatedAsyncioTestCase):
    async def test_send_email_calls_resend_api(self):
        from cloud_service.app.integrations import resend_client

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        with patch.object(resend_client, "RESEND_API_KEY", "re_test"), \
             patch.object(resend_client, "RESEND_FROM_EMAIL", "nestor@example.com"), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await resend_client.send_email("user@example.com", "Test Subject", "<p>Hello</p>")

            mock_client.post.assert_called_once()
            call_kwargs = mock_client.post.call_args
            self.assertEqual(call_kwargs[0][0], resend_client._RESEND_URL)
            payload = call_kwargs[1]["json"]
            self.assertEqual(payload["to"], ["user@example.com"])
            self.assertEqual(payload["subject"], "Test Subject")
            self.assertEqual(payload["from"], "nestor@example.com")
            self.assertEqual(payload["html"], "<p>Hello</p>")

    async def test_send_email_no_op_when_unconfigured(self):
        """No HTTP call should be made when RESEND_API_KEY is empty."""
        from cloud_service.app.integrations import resend_client

        with patch.object(resend_client, "RESEND_API_KEY", ""), \
             patch("httpx.AsyncClient") as mock_client_cls:
            await resend_client.send_email("user@example.com", "Subject", "<p>body</p>")
            mock_client_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
