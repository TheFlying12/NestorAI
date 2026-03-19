"""
Root conftest — sets environment variables before any cloud_service module
is imported.  Intentionally imports nothing from cloud_service so that the
existing unit tests (test_cloud_invariants, test_agent_loop) can still stub
sys.modules themselves.

Integration-specific fixtures (async client, test_db) live in
tests/integration/conftest.py, which is only loaded when pytest collects
tests under that directory.
"""
import os
from pathlib import Path

# ── 1. Load .env.test if present (pytest-dotenv handles this too, but this
#        ensures the vars are available even when pytest-dotenv is absent) ───
_env_file = Path(__file__).parent.parent / ".env.test"
if _env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file, override=True)
    except ImportError:
        pass  # python-dotenv optional; pytest-dotenv handles it otherwise

# ── 2. Defaults for every test session ───────────────────────────────────────
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_nestor.db")
os.environ.setdefault("AUTO_MIGRATE", "false")
os.environ.setdefault("FERNET_KEY", "")
os.environ.setdefault("CLERK_JWKS_URL", "https://example.clerk.accounts.dev/.well-known/jwks.json")
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("ALLOWED_ORIGINS", "*")
os.environ.setdefault("LOG_LEVEL", "WARNING")  # quieter test output
