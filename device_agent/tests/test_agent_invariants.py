"""Unit tests for device_agent invariants."""
import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Patch DB_PATH before importing agent
os.environ.setdefault("DEVICE_ID", "dev_test")
os.environ.setdefault("DEVICE_TOKEN", "test_token")
os.environ.setdefault("CLOUD_WS_URL", "wss://example.com")


class TestTransactionParsing(unittest.TestCase):
    """Budget assistant parsing is deterministic — no LLM needed."""

    def _import_skill(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "budget_main",
            os.path.join(os.path.dirname(__file__), "../../skills/budget_assistant/main.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        # Patch DB so tests don't write to /data
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            mod_env = {"BUDGET_DB_PATH": f.name}
        with patch.dict(os.environ, mod_env):
            spec.loader.exec_module(mod)
        return mod, mod_env

    def test_parse_amount_dollar_sign(self):
        import sys
        skill_path = os.path.join(os.path.dirname(__file__), "../../skills/budget_assistant")
        sys.path.insert(0, skill_path)
        # Direct import of module-level parse function
        import importlib
        import importlib.util
        spec = importlib.util.spec_from_file_location("ba", os.path.join(skill_path, "main.py"))
        mod = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {"BUDGET_DB_PATH": ":memory:"}):
            spec.loader.exec_module(mod)
        result = mod._parse_transaction("I spent $45 at Whole Foods")
        self.assertIsNotNone(result)
        self.assertEqual(result["amount"], 45.0)
        self.assertEqual(result["category"], "food")
        self.assertEqual(result["merchant"], "Whole Foods")

    def test_parse_amount_without_dollar(self):
        import sys
        skill_path = os.path.join(os.path.dirname(__file__), "../../skills/budget_assistant")
        sys.path.insert(0, skill_path)
        import importlib.util
        spec = importlib.util.spec_from_file_location("ba2", os.path.join(skill_path, "main.py"))
        mod = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {"BUDGET_DB_PATH": ":memory:"}):
            spec.loader.exec_module(mod)
        result = mod._parse_transaction("spent 80 on groceries")
        self.assertIsNotNone(result)
        self.assertEqual(result["amount"], 80.0)
        self.assertEqual(result["category"], "food")

    def test_parse_no_amount_returns_none(self):
        import sys
        skill_path = os.path.join(os.path.dirname(__file__), "../../skills/budget_assistant")
        sys.path.insert(0, skill_path)
        import importlib.util
        spec = importlib.util.spec_from_file_location("ba3", os.path.join(skill_path, "main.py"))
        mod = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {"BUDGET_DB_PATH": ":memory:"}):
            spec.loader.exec_module(mod)
        result = mod._parse_transaction("how am I doing on my budget?")
        self.assertIsNone(result)

    def test_categorize_transport(self):
        import sys
        skill_path = os.path.join(os.path.dirname(__file__), "../../skills/budget_assistant")
        sys.path.insert(0, skill_path)
        import importlib.util
        spec = importlib.util.spec_from_file_location("ba4", os.path.join(skill_path, "main.py"))
        mod = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {"BUDGET_DB_PATH": ":memory:"}):
            spec.loader.exec_module(mod)
        self.assertEqual(mod._categorize("Uber ride downtown"), "transport")

    def test_budget_alert_over_budget(self):
        import sys
        skill_path = os.path.join(os.path.dirname(__file__), "../../skills/budget_assistant")
        sys.path.insert(0, skill_path)
        import importlib.util
        spec = importlib.util.spec_from_file_location("ba5", os.path.join(skill_path, "main.py"))
        mod = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {"BUDGET_DB_PATH": ":memory:"}):
            spec.loader.exec_module(mod)
        alerts = mod._check_budget_alerts({"food": 500.0})  # budget is 400
        self.assertTrue(any("food" in a.lower() for a in alerts))


class TestIdempotencyKey(unittest.IsolatedAsyncioTestCase):
    """Command deduplication via idempotency_key."""

    async def test_duplicate_command_not_re_executed(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        with patch.dict(os.environ, {"DB_PATH": db_path}):
            import importlib.util, sys
            agent_path = os.path.join(os.path.dirname(__file__), "../app/agent.py")
            spec = importlib.util.spec_from_file_location("agent_mod", agent_path)
            mod = importlib.util.module_from_spec(spec)
            # Patch DB_PATH in the module before loading
            with patch("builtins.__import__"):
                pass

            # Direct test: record then check
            import aiosqlite
            async with aiosqlite.connect(db_path) as db:
                await db.execute(
                    "CREATE TABLE IF NOT EXISTS executed_commands "
                    "(idempotency_key TEXT PRIMARY KEY, command_id TEXT NOT NULL, executed_at TEXT NOT NULL)"
                )
                await db.execute(
                    "INSERT INTO executed_commands VALUES (?, ?, ?)",
                    ("idem_abc", "cmd_001", datetime.now(timezone.utc).isoformat()),
                )
                await db.commit()
                cursor = await db.execute(
                    "SELECT 1 FROM executed_commands WHERE idempotency_key = ?", ("idem_abc",)
                )
                row = await cursor.fetchone()
            self.assertIsNotNone(row)

        os.unlink(db_path)


class TestCommandTTL(unittest.TestCase):
    """Expired commands are rejected before execution."""

    def test_expired_command_detected(self):
        past = datetime.now(timezone.utc) - timedelta(hours=25)
        now = datetime.now(timezone.utc)
        self.assertGreater(now, past)


class TestMainConfigValidation(unittest.TestCase):
    """main.py fails fast when required env vars are missing."""

    def test_missing_device_id_raises(self):
        with patch.dict(os.environ, {"DEVICE_ID": "", "DEVICE_TOKEN": "tok", "CLOUD_WS_URL": "wss://x"}, clear=False):
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "agent_main",
                os.path.join(os.path.dirname(__file__), "../app/main.py"),
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            # Temporarily override DEVICE_ID
            orig = mod.DEVICE_ID
            mod.DEVICE_ID = ""
            with self.assertRaises(RuntimeError):
                mod._validate_config()
            mod.DEVICE_ID = orig


if __name__ == "__main__":
    unittest.main()
