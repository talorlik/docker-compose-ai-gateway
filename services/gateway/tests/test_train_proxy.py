"""Gateway train proxy tests with mocked training-api."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

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


def test_proxy_post_train(client):
    async def mock_post(url, json=None, headers=None):
        _ = (json, headers)
        assert url.endswith("/train")
        return MockResponse({"job_id": "train-jid"})

    with patch.object(app.state, "http", AsyncMock(), create=True) as mock_http:
        mock_http.post = AsyncMock(side_effect=mock_post)
        resp = client.post("/api/train")
        assert resp.status_code == 200
        assert resp.json()["job_id"] == "train-jid"


def test_proxy_post_train_503_on_connect_error(client):
    import httpx

    with patch.object(app.state, "http", AsyncMock(), create=True) as mock_http:
        mock_http.post = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )
        resp = client.post("/api/train")
        assert resp.status_code == 503
        assert "Training API unavailable" in resp.json()["detail"]


def test_proxy_get_train_status(client):
    job_id = "550e8400-e29b-41d4-a716-446655440000"

    async def mock_get(url, json=None, headers=None):
        _ = (json, headers)
        assert job_id in url
        return MockResponse({"job_id": job_id, "status": "completed"})

    with patch.object(app.state, "http", AsyncMock(), create=True) as mock_http:
        mock_http.get = AsyncMock(side_effect=mock_get)
        resp = client.get(f"/api/train/status/{job_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"


def test_proxy_get_train_status_invalid_job_id(client):
    resp = client.get("/api/train/status/not-a-valid-uuid")
    assert resp.status_code == 400
    assert "Invalid job_id" in resp.json()["detail"]


def test_proxy_get_train_last(client):
    async def mock_get(url, json=None, headers=None):
        _ = (json, headers)
        assert url.endswith("/train/last")
        return MockResponse({"accuracy": 0.95})

    with patch.object(app.state, "http", AsyncMock(), create=True) as mock_http:
        mock_http.get = AsyncMock(side_effect=mock_get)
        resp = client.get("/api/train/last")
        assert resp.status_code == 200
        assert resp.json()["accuracy"] == 0.95


def test_proxy_get_train_events(client):
    job_id = "550e8400-e29b-41d4-a716-446655440000"

    with patch.object(
        gateway_main,
        "_stream_training_api_events",
        return_value=iter([b'data: {"status":"completed"}\n\n']),
    ):
        resp = client.get(f"/api/train/events/{job_id}")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")


def test_proxy_promote(client):
    async def mock_post(url, json=None):
        _ = json
        assert url.endswith("/refine/promote")
        return MockResponse({"promoted": True})

    with patch.object(
        app.state, "promote_http", AsyncMock(), create=True
    ) as mock_http:
        mock_http.post = AsyncMock(side_effect=mock_post)
        resp = client.post(
            "/api/refine/promote",
            json={"run_id": "550e8400-e29b-41d4-a716-446655440000"},
        )
        assert resp.status_code == 200
        assert resp.json()["promoted"] is True


def test_proxy_promote_invalid_json(client):
    resp = client.post(
        "/api/refine/promote",
        content=b"not json",
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 400
    assert "Invalid JSON" in resp.json()["detail"]
