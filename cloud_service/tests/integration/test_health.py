"""Smoke tests for the /health endpoint."""
import pytest


async def test_health_returns_200(client):
    response = await client.get("/health")
    assert response.status_code == 200


async def test_health_payload(client):
    response = await client.get("/health")
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "cloud"
    assert "version" in body
    assert "connected_browsers" in body
