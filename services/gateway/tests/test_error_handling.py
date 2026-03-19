"""Unit tests for gateway error handling scenarios."""

from __future__ import annotations

from unittest.mock import patch

from app.main import app


class MockResponse:
    def __init__(self, json_data, status_code=200):
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


def _classify_response(route, confidence, probs):
    return {
        "route": route,
        "confidence": confidence,
        "probabilities": probs,
        "explanation": "test",
        "top_tokens": [],
        "trace_append": {
            "service": "ai-router",
            "event": "classified",
            "ts": "2024-01-01T00:00:00.000+00:00",
            "meta": {"route": route, "confidence": confidence},
        },
    }


def _handle_response(service):
    return {
        "payload": {"service": service, "result": f"Mock from {service}"},
        "trace_append": {
            "service": service,
            "event": "handled",
            "ts": "2024-01-01T00:00:01.000+00:00",
            "meta": {"status": 200},
        },
    }


def test_ai_router_connect_error_returns_503(client):
    import httpx

    async def mock_post(_client, url, json, headers):
        raise httpx.ConnectError("connection refused")

    with patch("app.main.timed_post", side_effect=mock_post):
        resp = client.post("/api/request", json={"text": "test query"})

    assert resp.status_code == 503
    data = resp.json()
    assert "Classification service unavailable" in data["message"]
    assert "trace" in data
    assert "timings_ms" in data


def test_ai_router_timeout_returns_503(client):
    import httpx

    async def mock_post(_client, url, json, headers):
        raise httpx.TimeoutException("read timeout")

    with patch("app.main.timed_post", side_effect=mock_post):
        resp = client.post("/api/request", json={"text": "test query"})

    assert resp.status_code == 503


def test_bad_classify_response_returns_502(client):
    async def mock_post(_client, url, json, headers):
        if "/classify" in url:
            return MockResponse({"invalid": "missing trace_append"}), 10
        raise ValueError(f"Unexpected URL: {url}")

    with patch("app.main.timed_post", side_effect=mock_post):
        resp = client.post("/api/request", json={"text": "test query"})

    assert resp.status_code == 502
    data = resp.json()
    assert "Invalid response from classification" in data["message"]


def test_backend_connect_error_returns_502(client):
    import httpx

    async def mock_post(_client, url, json, headers):
        if "/classify" in url:
            return MockResponse(
                _classify_response(
                    "search",
                    0.85,
                    {"search": 0.85, "image": 0.05, "ops": 0.05, "unknown": 0.05},
                )
            ), 10
        if "/handle" in url:
            raise httpx.ConnectError("backend down")
        raise ValueError(f"Unexpected URL: {url}")

    with patch("app.main.timed_post", side_effect=mock_post):
        resp = client.post("/api/request", json={"text": "search test"})

    assert resp.status_code == 502
    data = resp.json()
    assert "unavailable" in data["message"].lower()


def test_bad_backend_response_returns_502(client):
    async def mock_post(_client, url, json, headers):
        if "/classify" in url:
            return MockResponse(
                _classify_response(
                    "search",
                    0.85,
                    {"search": 0.85, "image": 0.05, "ops": 0.05, "unknown": 0.05},
                )
            ), 10
        if "/handle" in url:
            return MockResponse({"invalid": "no trace_append or payload"}), 20
        raise ValueError(f"Unexpected URL: {url}")

    with patch("app.main.timed_post", side_effect=mock_post):
        resp = client.post("/api/request", json={"text": "search test"})

    assert resp.status_code == 502
    data = resp.json()
    assert "Invalid response from backend" in data["message"]


def test_no_backend_configured_returns_502(client):
    async def mock_post(_client, url, json, headers):
        if "/classify" in url:
            return MockResponse(
                _classify_response(
                    "nonexistent",
                    0.95,
                    {"nonexistent": 0.95, "search": 0.05},
                )
            ), 10
        raise ValueError(f"Unexpected URL: {url}")

    with patch("app.main.timed_post", side_effect=mock_post):
        resp = client.post("/api/request", json={"text": "test query"})

    assert resp.status_code == 502
    data = resp.json()
    assert "No backend configured" in data["message"]
