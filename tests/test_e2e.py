"""End-to-end tests that verify the full request flow.

These tests use the actual gateway FastAPI app with mocked timed_post
to simulate the complete request lifecycle without Docker.

Mark: @pytest.mark.e2e
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.main import app  # noqa: F401


class MockResponse:
    def __init__(self, json_data: dict, status_code: int = 200):
        self._json = json_data
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError(
                f"Mock {self.status_code}",
                request=None,
                response=self,
            )


def _classify_response(route, confidence, probs):
    return {
        "route": route,
        "confidence": confidence,
        "probabilities": probs,
        "explanation": f"top tokens: mock",
        "top_tokens": ["mock"],
        "trace_append": {
            "service": "ai-router",
            "event": "classified",
            "ts": "2024-01-01T00:00:00.000+00:00",
            "meta": {"route": route, "confidence": confidence},
        },
    }


def _handle_response(service):
    return {
        "payload": {
            "service": service,
            "result": f"Mock result from {service}",
            "instance": "mock-host",
        },
        "trace_append": {
            "service": service,
            "event": "handled",
            "ts": "2024-01-01T00:00:01.000+00:00",
            "meta": {"status": 200, "instance": "mock-host"},
        },
    }


@pytest.mark.e2e
class TestFullRequestFlow:
    """End-to-end: client -> gateway -> classify -> policy -> backend -> response."""

    def _make_mock_post(self, route, service):
        probs = {"search": 0.05, "image": 0.05, "ops": 0.05, "unknown": 0.05}
        probs[route] = 0.85

        async def mock_post(_client, url, json_body, headers):
            if "/classify" in url:
                return MockResponse(_classify_response(route, 0.85, probs)), 10
            if "/handle" in url:
                return MockResponse(_handle_response(service)), 20
            raise ValueError(f"Unexpected URL: {url}")

        return mock_post

    @pytest.mark.parametrize(
        "text,route,service",
        [
            ("find kubernetes best practices", "search", "search-service"),
            ("resize this image to 1080p", "image", "image-service"),
            ("kubectl get pods status", "ops", "ops-service"),
        ],
    )
    def test_successful_route(self, client, text, route, service):
        with patch(
            "app.main.timed_post",
            side_effect=self._make_mock_post(route, service),
        ):
            resp = client.post("/api/request", json={"text": text})

        assert resp.status_code == 200
        data = resp.json()

        assert data["route"] == route
        assert data["confidence"] == 0.85
        assert data["backend_response"]["service"] == service
        assert data["request_id"]
        assert len(data["trace"]) >= 3
        assert data["timings_ms"]["classify"] >= 0
        assert data["timings_ms"]["proxy"] >= 0
        assert data["timings_ms"]["total"] >= 0

    def test_unknown_request_returns_404(self, client):
        async def mock_post(_client, url, json_body, headers):
            if "/classify" in url:
                return MockResponse(
                    _classify_response(
                        "unknown",
                        0.70,
                        {"search": 0.10, "image": 0.10, "ops": 0.10, "unknown": 0.70},
                    )
                ), 10
            raise ValueError(f"Unexpected URL: {url}")

        with patch("app.main.timed_post", side_effect=mock_post):
            resp = client.post(
                "/api/request",
                json={"text": "what is the meaning of life"},
            )

        assert resp.status_code == 404
        data = resp.json()
        assert data["route"] == "unknown"
        assert "Unable to determine" in data["message"]

    def test_request_preserves_custom_id(self, client):
        custom_id = "e2e-test-id-12345"

        async def mock_post(_client, url, json_body, headers):
            assert json_body.get("request_id") == custom_id
            if "/classify" in url:
                return MockResponse(
                    _classify_response(
                        "search",
                        0.85,
                        {"search": 0.85, "image": 0.05, "ops": 0.05, "unknown": 0.05},
                    )
                ), 10
            if "/handle" in url:
                return MockResponse(_handle_response("search-service")), 20
            raise ValueError(f"Unexpected URL: {url}")

        with patch("app.main.timed_post", side_effect=mock_post):
            resp = client.post(
                "/api/request",
                json={"request_id": custom_id, "text": "test query"},
            )

        assert resp.status_code == 200
        assert resp.json()["request_id"] == custom_id

    def test_trace_includes_all_services(self, client):
        initial_trace = [
            {"service": "browser", "event": "submit", "ts": "2024-01-01T00:00:00.000+00:00"}
        ]

        async def mock_post(_client, url, json_body, headers):
            if "/classify" in url:
                return MockResponse(
                    _classify_response(
                        "search",
                        0.85,
                        {"search": 0.85, "image": 0.05, "ops": 0.05, "unknown": 0.05},
                    )
                ), 10
            if "/handle" in url:
                return MockResponse(_handle_response("search-service")), 20
            raise ValueError(f"Unexpected URL: {url}")

        with patch("app.main.timed_post", side_effect=mock_post):
            resp = client.post(
                "/api/request",
                json={"text": "test", "trace": initial_trace},
            )

        data = resp.json()
        services = [t["service"] for t in data["trace"]]
        events = [t["event"] for t in data["trace"]]

        assert "browser" in services
        assert "gateway" in services
        assert "ai-router" in services
        assert "search-service" in services
        assert "submit" in events
        assert "received" in events
        assert "classified" in events
        assert "handled" in events
        assert "responded" in events


@pytest.mark.e2e
class TestStaticPages:
    def test_query_page(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_train_page(self, client):
        resp = client.get("/train")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_refine_page(self, client):
        resp = client.get("/refine")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]


@pytest.mark.e2e
class TestHealthEndpoints:
    def test_gateway_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_routes_endpoint(self, client):
        resp = client.get("/routes")
        assert resp.status_code == 200
        labels = {r["label"] for r in resp.json()["routes"]}
        assert labels == {"search", "image", "ops"}


@pytest.mark.e2e
class TestErrorScenarios:
    def test_missing_text_rejected(self, client):
        resp = client.post("/api/request", json={})
        assert resp.status_code == 422

    def test_invalid_json_rejected(self, client):
        resp = client.post(
            "/api/request",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 422

    def test_cascade_failure_ai_router_down(self, client):
        import httpx

        async def mock_post(_client, url, json_body, headers):
            raise httpx.ConnectError("connection refused")

        with patch("app.main.timed_post", side_effect=mock_post):
            resp = client.post("/api/request", json={"text": "test"})

        assert resp.status_code == 503
        data = resp.json()
        assert "trace" in data
        assert data["timings_ms"]["total"] >= 0
