"""Gateway refine proxy tests with mocked training-api."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app import main as gateway_main
from app.main import app


class MockResponse:
    def __init__(self, json_data: dict, status_code: int = 200):
        self._json_data = json_data
        self.status_code = status_code

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError(
                f"Mock error {self.status_code}",
                request=None,
                response=self,
            )


def test_proxy_post_refine_relabel(client):
    async def mock_post(url, json=None, headers=None):
        _ = (json, headers)
        assert url.endswith("/refine/relabel")
        return MockResponse({"job_id": "jid", "run_id": "rid"})

    with patch.object(app.state, "http", AsyncMock(), create=True) as mock_http:
        mock_http.post = AsyncMock(side_effect=mock_post)
        resp = client.post("/api/refine/relabel")
        assert resp.status_code == 200
        assert resp.json()["job_id"] == "jid"
        assert resp.json()["run_id"] == "rid"


def test_proxy_post_refine_augment(client):
    async def mock_post(url, json=None, headers=None):
        _ = (json, headers)
        assert url.endswith("/refine/augment")
        return MockResponse({"job_id": "jid2", "run_id": "rid2"})

    with patch.object(app.state, "http", AsyncMock(), create=True) as mock_http:
        mock_http.post = AsyncMock(side_effect=mock_post)
        resp = client.post("/api/refine/augment")
        assert resp.status_code == 200
        assert resp.json()["job_id"] == "jid2"
        assert resp.json()["run_id"] == "rid2"


def test_proxy_relabel_returns_503_on_connect_error(client):
    import httpx

    with patch.object(app.state, "http", AsyncMock(), create=True) as mock_http:
        mock_http.post = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )
        resp = client.post("/api/refine/relabel")
        assert resp.status_code == 503
        assert "Training API unavailable" in resp.json()["detail"]


def test_proxy_augment_returns_503_on_timeout(client):
    import httpx

    with patch.object(app.state, "http", AsyncMock(), create=True) as mock_http:
        mock_http.post = AsyncMock(
            side_effect=httpx.TimeoutException("read timeout")
        )
        resp = client.post("/api/refine/augment")
        assert resp.status_code == 503
        assert "Training API unavailable" in resp.json()["detail"]


def test_proxy_relabel_forwards_upstream_status_code(client):
    async def mock_post(url, json=None, headers=None):
        _ = (json, headers)
        return MockResponse({"detail": "busy"}, status_code=429)

    with patch.object(app.state, "http", AsyncMock(), create=True) as mock_http:
        mock_http.post = AsyncMock(side_effect=mock_post)
        resp = client.post("/api/refine/relabel")
        assert resp.status_code == 503


def test_proxy_relabel_events_endpoint_exists(client):
    """GET /api/refine/relabel/events/{job_id} should stream SSE."""
    job_id = "550e8400-e29b-41d4-a716-446655440000"
    with patch.object(
        gateway_main,
        "_stream_training_api_events",
        return_value=iter([b'data: {"status":"completed"}\n\n']),
    ):
        resp = client.get(f"/api/refine/relabel/events/{job_id}")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")


def test_proxy_augment_events_endpoint_exists(client):
    job_id = "550e8400-e29b-41d4-a716-446655440000"
    with patch.object(
        gateway_main,
        "_stream_training_api_events",
        return_value=iter([b'data: {"status":"completed"}\n\n']),
    ):
        resp = client.get(f"/api/refine/augment/events/{job_id}")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")


def test_proxy_events_invalid_job_id_returns_400(client):
    resp = client.get("/api/refine/relabel/events/not-a-uuid")
    assert resp.status_code == 400
