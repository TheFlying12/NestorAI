"""Device agent entrypoint.

Reads config from environment, then starts the outbound WebSocket connect loop
with exponential backoff reconnect.
"""
import asyncio
import logging
import os
import random

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("device_agent")

DEVICE_ID = os.environ.get("DEVICE_ID", "")
DEVICE_TOKEN = os.environ.get("DEVICE_TOKEN", "")
CLOUD_WS_URL = os.environ.get("CLOUD_WS_URL", "")
AGENT_VERSION = os.environ.get("AGENT_VERSION", "0.1.0")
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL_SECONDS", "30"))

BACKOFF_BASE = 1.0
BACKOFF_MAX = 60.0


def _validate_config() -> None:
    missing = [k for k, v in [("DEVICE_ID", DEVICE_ID), ("DEVICE_TOKEN", DEVICE_TOKEN), ("CLOUD_WS_URL", CLOUD_WS_URL)] if not v]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")


async def _run_with_backoff() -> None:
    from app.agent import run_agent

    delay = BACKOFF_BASE
    attempt = 0

    while True:
        attempt += 1
        try:
            await run_agent(
                device_id=DEVICE_ID,
                device_token=DEVICE_TOKEN,
                cloud_ws_url=CLOUD_WS_URL,
                agent_version=AGENT_VERSION,
                heartbeat_interval=HEARTBEAT_INTERVAL,
            )
            # run_agent only returns on clean disconnect; reset backoff
            delay = BACKOFF_BASE
            attempt = 0
        except Exception as exc:
            jitter = random.uniform(0, delay * 0.2)
            wait = min(delay + jitter, BACKOFF_MAX)
            logger.warning(
                "Agent disconnected (attempt %d): %s — reconnecting in %.1fs",
                attempt,
                exc,
                wait,
            )
            await asyncio.sleep(wait)
            delay = min(delay * 2, BACKOFF_MAX)


async def main() -> None:
    _validate_config()
    logger.info(
        "Device agent starting device_id=%s version=%s cloud=%s",
        DEVICE_ID,
        AGENT_VERSION,
        CLOUD_WS_URL,
    )
    await _run_with_backoff()


if __name__ == "__main__":
    asyncio.run(main())
