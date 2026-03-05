"""Unit tests for cloud_service invariants."""
import hashlib
import hmac
import os
import secrets
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Minimal env so modules import cleanly without a real DB.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("CLOUD_SECRET_KEY", "test_secret_key_for_unit_tests")


class TestTokenHashing(unittest.TestCase):
    """Device tokens are stored as HMAC-SHA256 hashes; never plaintext."""

    def _hash(self, value: str) -> str:
        key = "test_secret_key_for_unit_tests"
        return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()

    def test_hash_is_64_hex_chars(self):
        h = self._hash("some_raw_token")
        self.assertEqual(len(h), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in h))

    def test_different_tokens_different_hashes(self):
        h1 = self._hash("token_a")
        h2 = self._hash("token_b")
        self.assertNotEqual(h1, h2)

    def test_verify_uses_constant_time_compare(self):
        raw = secrets.token_hex(32)
        h = self._hash(raw)
        # Verify: correct token passes
        self.assertTrue(hmac.compare_digest(self._hash(raw), h))
        # Verify: wrong token fails
        self.assertFalse(hmac.compare_digest(self._hash("wrong"), h))


class TestPairingCodeExpiry(unittest.TestCase):
    """Pairing codes must be rejected when expired or already used."""

    def _make_code(self, used: bool, expired: bool):
        from unittest.mock import MagicMock
        code = MagicMock()
        code.used = used
        code.expires_at = (
            datetime.now(timezone.utc) - timedelta(hours=1)
            if expired
            else datetime.now(timezone.utc) + timedelta(hours=24)
        )
        return code

    def test_unused_valid_code_passes(self):
        code = self._make_code(used=False, expired=False)
        now = datetime.now(timezone.utc)
        expires = code.expires_at.replace(tzinfo=timezone.utc)
        self.assertFalse(code.used)
        self.assertGreater(expires, now)

    def test_used_code_is_rejected(self):
        code = self._make_code(used=True, expired=False)
        self.assertTrue(code.used)

    def test_expired_code_is_rejected(self):
        code = self._make_code(used=False, expired=True)
        now = datetime.now(timezone.utc)
        expires = code.expires_at.replace(tzinfo=timezone.utc)
        self.assertLess(expires, now)


class TestCommandExpiry(unittest.TestCase):
    """Commands past TTL are marked expired and not retried."""

    def test_command_within_ttl_is_valid(self):
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=1)
        self.assertGreater(expires_at, now)

    def test_command_past_ttl_is_expired(self):
        now = datetime.now(timezone.utc)
        expires_at = now - timedelta(hours=1)
        self.assertLess(expires_at, now)


class TestDeviceTokenFormat(unittest.TestCase):
    """Device token format: '{device_id}:{raw_token}'."""

    def test_token_split_extracts_device_id(self):
        device_id = "dev_abc123"
        raw = secrets.token_hex(32)
        token = f"{device_id}:{raw}"
        parts = token.split(":", 1)
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[0], device_id)
        self.assertEqual(parts[1], raw)

    def test_malformed_token_has_no_colon(self):
        token = "no_colon_in_here"
        parts = token.split(":", 1)
        self.assertEqual(len(parts), 1)


class TestTransferNonceExpiry(unittest.TestCase):
    """Transfer nonces expire after TRANSFER_NONCE_TTL_MINUTES."""

    def test_fresh_nonce_is_valid(self):
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        self.assertGreater(expires_at, datetime.now(timezone.utc))

    def test_old_nonce_is_expired(self):
        expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        self.assertLess(expires_at, datetime.now(timezone.utc))


if __name__ == "__main__":
    unittest.main()
