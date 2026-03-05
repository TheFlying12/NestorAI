"""Command execution handlers for device_agent.

Each handler receives the command payload dict and returns a result dict.
Raise RuntimeError on unrecoverable failure with a human-readable message.
"""
import hashlib
import logging
import os
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Dict

import httpx

logger = logging.getLogger("device_agent.handlers")

SKILLS_DIR = os.getenv("SKILLS_DIR", "/data/skills_installed")
OPENCLAW_INTERNAL_URL = os.getenv("OPENCLAW_INTERNAL_URL", "http://openclaw:18789")
DOWNLOAD_TIMEOUT = float(os.getenv("DOWNLOAD_TIMEOUT_SECONDS", "60"))
OPENCLAW_TIMEOUT = float(os.getenv("OPENCLAW_RELOAD_TIMEOUT_SECONDS", "10"))


async def handle_install_skill(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Download, SHA256-verify, extract, and activate a skill.

    payload keys: skill_id, version, archive_url, sha256
    """
    skill_id: str = payload["skill_id"]
    version: str = payload["version"]
    archive_url: str = payload["archive_url"]
    expected_sha256: str = payload["sha256"].lower()

    logger.info("Installing skill skill_id=%s version=%s", skill_id, version)

    # 1. Download archive to temp file
    with tempfile.TemporaryDirectory() as tmpdir:
        archive_path = Path(tmpdir) / f"{skill_id}-{version}.tar.gz"

        async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT) as client:
            response = await client.get(archive_url)
            response.raise_for_status()
            archive_path.write_bytes(response.content)

        # 2. Verify SHA256 — fail-fast on mismatch
        actual_sha256 = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            raise RuntimeError(
                f"SHA256 mismatch for skill_id={skill_id}: "
                f"expected={expected_sha256} actual={actual_sha256}"
            )

        # 3. Extract to /data/skills_installed/{skill_id}/
        install_path = Path(SKILLS_DIR) / skill_id
        install_path.mkdir(parents=True, exist_ok=True)

        with tarfile.open(archive_path) as tar:
            # Security: only extract safe members (no absolute paths, no ..)
            safe_members = [
                m for m in tar.getmembers()
                if not m.name.startswith("/") and ".." not in m.name
            ]
            tar.extractall(path=str(install_path), members=safe_members)

        logger.info("Skill extracted skill_id=%s path=%s", skill_id, install_path)

    # 4. Signal OpenClaw to reload skill catalog
    try:
        async with httpx.AsyncClient(timeout=OPENCLAW_TIMEOUT) as client:
            response = await client.post(
                f"{OPENCLAW_INTERNAL_URL.rstrip('/')}/v1/skills/reload",
                json={"skill_id": skill_id},
            )
            response.raise_for_status()
        logger.info("OpenClaw skill reload triggered skill_id=%s", skill_id)
    except httpx.HTTPError as exc:
        # Non-fatal — skill is installed but reload failed; OpenClaw will pick it up on restart.
        logger.warning("OpenClaw reload signal failed for skill_id=%s: %s", skill_id, exc)

    return {"skill_id": skill_id, "version": version, "installed_path": str(Path(SKILLS_DIR) / skill_id)}


async def handle_config_reload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Write new config values and signal gateway to reload.

    payload keys: config_key (str), config_value (str)
    Writes to /data/runtime.env which gateway reads on restart.
    """
    config_key: str = payload["config_key"]
    config_value: str = payload["config_value"]

    if not config_key.isidentifier() and not config_key.replace("_", "").isalnum():
        raise RuntimeError(f"Invalid config_key: {config_key!r}")

    config_path = Path("/data/runtime.env")
    lines = []
    found = False

    if config_path.exists():
        for line in config_path.read_text().splitlines():
            if line.startswith(f"{config_key}="):
                lines.append(f"{config_key}={config_value}")
                found = True
            else:
                lines.append(line)

    if not found:
        lines.append(f"{config_key}={config_value}")

    config_path.write_text("\n".join(lines) + "\n")
    logger.info("Config updated key=%s", config_key)

    # Signal OpenClaw to reload (best-effort)
    try:
        async with httpx.AsyncClient(timeout=OPENCLAW_TIMEOUT) as client:
            await client.post(f"{OPENCLAW_INTERNAL_URL.rstrip('/')}/v1/reload")
    except httpx.HTTPError as exc:
        logger.warning("OpenClaw reload signal failed after config update: %s", exc)

    return {"updated_key": config_key}


async def handle_reload_runtime(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Restart the OpenClaw container via Docker socket.

    Requires /var/run/docker.sock mounted in the device_agent container.
    payload keys: target (optional, default "openclaw")
    """
    import json as _json
    target_container: str = payload.get("target", "openclaw")

    logger.info("Reloading runtime container=%s", target_container)

    try:
        async with httpx.AsyncClient(
            base_url="http://localhost",
            transport=httpx.AsyncHTTPTransport(uds="/var/run/docker.sock"),
            timeout=30.0,
        ) as client:
            response = await client.post(f"/containers/{target_container}/restart")
            if response.status_code not in (204, 404):
                raise RuntimeError(
                    f"Docker API error: {response.status_code} {response.text}"
                )
    except Exception as exc:
        raise RuntimeError(f"Failed to restart container {target_container}: {exc}") from exc

    logger.info("Container restart triggered container=%s", target_container)
    return {"restarted": target_container}
