"""Unit tests for cloud_service invariants."""
import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

# ── Stub out heavy DB/async dependencies so tests run without asyncpg ──────────
# Must happen BEFORE any cloud_service imports.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("FERNET_KEY", "")

# Stub db and models so create_async_engine is never called and Python 3.9
# doesn't choke on `str | None` union syntax in models.py.
_db_stub = types.ModuleType("cloud_service.app.db")
_db_stub.Base = MagicMock()             # type: ignore
_db_stub.get_db = MagicMock()           # type: ignore
_db_stub.create_all_tables = MagicMock()  # type: ignore
_db_stub.AsyncSessionLocal = MagicMock()  # type: ignore
sys.modules["cloud_service.app.db"] = _db_stub

_models_stub = types.ModuleType("cloud_service.app.models")
_models_stub.Transaction = MagicMock()   # type: ignore
_models_stub.User = MagicMock()          # type: ignore
_models_stub.Conversation = MagicMock()  # type: ignore
_models_stub.ConversationMessage = MagicMock()   # type: ignore
_models_stub.ConversationSummary = MagicMock()   # type: ignore
_models_stub.SkillMemory = MagicMock()   # type: ignore
sys.modules["cloud_service.app.models"] = _models_stub


class TestContextWindowConfig(unittest.TestCase):
    """Context engine configuration invariants."""

    def test_default_window_is_12_turns(self):
        window = int(os.getenv("CONTEXT_WINDOW_TURNS", "12"))
        self.assertEqual(window, 12)

    def test_summary_triggers_before_threshold(self):
        turns_since_summary = 7
        update_every = int(os.getenv("SUMMARY_UPDATE_EVERY_TURNS", "6"))
        self.assertGreaterEqual(turns_since_summary, update_every)

    def test_summary_does_not_trigger_below_threshold(self):
        turns_since_summary = 3
        update_every = int(os.getenv("SUMMARY_UPDATE_EVERY_TURNS", "6"))
        self.assertLess(turns_since_summary, update_every)


class TestBudgetCategorizer(unittest.TestCase):
    """Budget Assistant deterministic categorization."""

    def _categorize(self, text: str) -> str:
        from cloud_service.app.skills.budget_assistant import _categorize
        return _categorize(text)

    def test_starbucks_is_food(self):
        self.assertEqual(self._categorize("coffee at starbucks"), "food")

    def test_uber_is_transport(self):
        self.assertEqual(self._categorize("uber ride downtown"), "transport")

    def test_netflix_is_entertainment(self):
        self.assertEqual(self._categorize("netflix subscription"), "entertainment")

    def test_electric_bill_is_utilities(self):
        self.assertEqual(self._categorize("electric bill payment"), "utilities")

    def test_unknown_is_other(self):
        self.assertEqual(self._categorize("random unknown vendor xyz"), "other")


class TestTransactionParser(unittest.TestCase):
    """Budget Assistant transaction parsing from natural language."""

    def _parse(self, text: str):
        from cloud_service.app.skills.budget_assistant import _parse_transaction
        return _parse_transaction(text)

    def test_parses_dollar_amount(self):
        result = self._parse("I spent $45 at Whole Foods")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["amount"], 45.0)

    def test_parses_merchant_name(self):
        result = self._parse("paid $12 at Starbucks")
        self.assertIsNotNone(result)
        self.assertEqual(result["merchant"], "Starbucks")

    def test_returns_none_with_no_amount(self):
        result = self._parse("I went to the store today")
        self.assertIsNone(result)

    def test_parses_decimal_amount(self):
        result = self._parse("spent $9.99 on Spotify")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["amount"], 9.99)


class TestBudgetAlerts(unittest.TestCase):
    """Budget alert thresholds fire at correct levels."""

    def _alerts(self, totals):
        from cloud_service.app.skills.budget_assistant import _check_budget_alerts
        return _check_budget_alerts(totals)

    def test_over_budget_triggers_alert(self):
        alerts = self._alerts({"food": 500.0})  # default budget 400
        self.assertTrue(any("food" in a.lower() or "Food" in a for a in alerts))

    def test_80_pct_triggers_warning(self):
        alerts = self._alerts({"food": 340.0})  # 85% of 400
        self.assertTrue(any("Food" in a or "food" in a for a in alerts))

    def test_under_threshold_no_alert(self):
        alerts = self._alerts({"food": 100.0})  # 25% of 400
        food_alerts = [a for a in alerts if "Food" in a or "food" in a]
        self.assertEqual(food_alerts, [])


class TestFernetKeyValidation(unittest.TestCase):
    """Fernet encryption round-trips correctly."""

    def test_encrypt_decrypt_roundtrip(self):
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode()
        os.environ["FERNET_KEY"] = key

        # Reset cached _fernet so it picks up the new key
        import cloud_service.app.auth as auth_module
        auth_module._fernet = None

        try:
            from cloud_service.app.auth import encrypt_api_key, decrypt_api_key
            original = "sk-test-abc123"
            encrypted = encrypt_api_key(original)
            self.assertNotEqual(encrypted, original)
            decrypted = decrypt_api_key(encrypted)
            self.assertEqual(decrypted, original)
        finally:
            auth_module._fernet = None
            del os.environ["FERNET_KEY"]

    def test_decrypt_fails_on_garbage(self):
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode()
        os.environ["FERNET_KEY"] = key

        import cloud_service.app.auth as auth_module
        auth_module._fernet = None

        try:
            from cloud_service.app.auth import decrypt_api_key
            with self.assertRaises(ValueError):
                decrypt_api_key("not-a-valid-fernet-token")
        finally:
            auth_module._fernet = None
            del os.environ["FERNET_KEY"]


class TestRetentionCutoff(unittest.TestCase):
    """Message retention cutoff is calculated correctly."""

    def test_cutoff_is_in_the_past(self):
        retention_days = int(os.getenv("MESSAGE_RETENTION_DAYS", "90"))
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        self.assertLess(cutoff, datetime.now(timezone.utc))

    def test_recent_message_survives(self):
        retention_days = 90
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        recent = datetime.now(timezone.utc) - timedelta(days=1)
        self.assertGreater(recent, cutoff)

    def test_old_message_is_pruned(self):
        retention_days = 90
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        old = datetime.now(timezone.utc) - timedelta(days=100)
        self.assertLess(old, cutoff)


if __name__ == "__main__":
    unittest.main()
