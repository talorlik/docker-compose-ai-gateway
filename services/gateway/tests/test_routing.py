"""Unit tests for gateway routing with mocked ai-router and backends."""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("T_ROUTE", "0.55")
os.environ.setdefault("T_MARGIN", "0.10")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_routes(client):
    resp = client.get("/routes")
    assert resp.status_code == 200
    data = resp.json()
    assert "routes" in data
    labels = {r["label"] for r in data["routes"]}
    assert labels == {"search", "image", "ops"}


class MockResponse:
    """Mock httpx response for testing."""

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


def make_classify_response(
    route: str,
    confidence: float,
    probs: dict,
) -> dict:
    return {
        "route": route,
        "confidence": confidence,
        "probabilities": probs,
        "explanation": f"top tokens: test, mock",
        "top_tokens": ["test", "mock"],
        "trace_append": {
            "service": "ai-router",
            "event": "classified",
            "ts": "2024-01-01T00:00:00.000+00:00",
            "meta": {"route": route, "confidence": confidence},
        },
    }


def make_handle_response(service: str) -> dict:
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


@pytest.fixture
def mock_http():
    """Fixture to mock the httpx client on app.state."""
    mock_client = AsyncMock()
    with patch.object(app.state, "http", mock_client):
        yield mock_client


def test_known_route_search(client, mock_http):
    async def mock_post(url, json, headers):
        if "/classify" in url:
            return MockResponse(
                make_classify_response(
                    "search",
                    0.85,
                    {"search": 0.85, "image": 0.05, "ops": 0.05, "unknown": 0.05},
                )
            ), 10
        if "/handle" in url:
            return MockResponse(make_handle_response("search-service")), 20
        raise ValueError(f"Unexpected URL: {url}")

    mock_http.post = AsyncMock(side_effect=mock_post)

    with patch("app.main.timed_post", side_effect=mock_post):
        resp = client.post(
            "/api/request",
            json={"text": "compare nginx vs traefik"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["route"] == "search"
    assert data["confidence"] == 0.85
    assert "backend_response" in data
    assert data["backend_response"]["service"] == "search-service"
    assert "timings_ms" in data
    assert "trace" in data
    assert len(data["trace"]) >= 3


def test_known_route_image(client, mock_http):
    async def mock_post(url, json, headers):
        if "/classify" in url:
            return MockResponse(
                make_classify_response(
                    "image",
                    0.90,
                    {"search": 0.03, "image": 0.90, "ops": 0.04, "unknown": 0.03},
                )
            ), 10
        if "/handle" in url:
            return MockResponse(make_handle_response("image-service")), 20
        raise ValueError(f"Unexpected URL: {url}")

    with patch("app.main.timed_post", side_effect=mock_post):
        resp = client.post(
            "/api/request",
            json={"text": "resize this image to 800x600"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["route"] == "image"


def test_known_route_ops(client, mock_http):
    async def mock_post(url, json, headers):
        if "/classify" in url:
            return MockResponse(
                make_classify_response(
                    "ops",
                    0.88,
                    {"search": 0.04, "image": 0.04, "ops": 0.88, "unknown": 0.04},
                )
            ), 10
        if "/handle" in url:
            return MockResponse(make_handle_response("ops-service")), 20
        raise ValueError(f"Unexpected URL: {url}")

    with patch("app.main.timed_post", side_effect=mock_post):
        resp = client.post(
            "/api/request",
            json={"text": "kubectl get pods crashloopbackoff"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["route"] == "ops"


def test_unknown_route_model_unknown(client, mock_http):
    async def mock_post(url, json, headers):
        if "/classify" in url:
            return MockResponse(
                make_classify_response(
                    "unknown",
                    0.70,
                    {"search": 0.10, "image": 0.10, "ops": 0.10, "unknown": 0.70},
                )
            ), 10
        raise ValueError(f"Unexpected URL: {url}")

    with patch("app.main.timed_post", side_effect=mock_post):
        resp = client.post(
            "/api/request",
            json={"text": "hello how are you"},
        )

    assert resp.status_code == 404
    data = resp.json()
    assert data["route"] == "unknown"
    assert "message" in data
    assert "trace" in data
    assert data["timings_ms"]["proxy"] == 0


def test_unknown_route_low_confidence(client, mock_http):
    async def mock_post(url, json, headers):
        if "/classify" in url:
            return MockResponse(
                make_classify_response(
                    "search",
                    0.40,
                    {"search": 0.40, "image": 0.25, "ops": 0.25, "unknown": 0.10},
                )
            ), 10
        raise ValueError(f"Unexpected URL: {url}")

    with patch("app.main.timed_post", side_effect=mock_post):
        resp = client.post(
            "/api/request",
            json={"text": "ambiguous query"},
        )

    assert resp.status_code == 404
    data = resp.json()
    assert data["route"] == "unknown"
    trace_events = [t.get("event") for t in data["trace"]]
    assert "responded" in trace_events


def test_unknown_route_low_margin(client, mock_http):
    async def mock_post(url, json, headers):
        if "/classify" in url:
            return MockResponse(
                make_classify_response(
                    "search",
                    0.58,
                    {"search": 0.35, "image": 0.33, "ops": 0.22, "unknown": 0.10},
                )
            ), 10
        raise ValueError(f"Unexpected URL: {url}")

    with patch("app.main.timed_post", side_effect=mock_post):
        resp = client.post(
            "/api/request",
            json={"text": "could be search or image"},
        )

    assert resp.status_code == 404
    data = resp.json()
    assert data["route"] == "unknown"


def test_request_id_generation(client, mock_http):
    async def mock_post(url, json, headers):
        if "/classify" in url:
            assert "request_id" in json
            assert json["request_id"]
            return MockResponse(
                make_classify_response(
                    "search",
                    0.85,
                    {"search": 0.85, "image": 0.05, "ops": 0.05, "unknown": 0.05},
                )
            ), 10
        if "/handle" in url:
            return MockResponse(make_handle_response("search-service")), 20
        raise ValueError(f"Unexpected URL: {url}")

    with patch("app.main.timed_post", side_effect=mock_post):
        resp = client.post(
            "/api/request",
            json={"text": "test query"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "request_id" in data
    assert data["request_id"]


def test_request_id_propagation(client, mock_http):
    custom_id = "custom-request-id-12345"

    async def mock_post(url, json, headers):
        assert json["request_id"] == custom_id
        assert headers.get("X-Request-ID") == custom_id
        if "/classify" in url:
            return MockResponse(
                make_classify_response(
                    "search",
                    0.85,
                    {"search": 0.85, "image": 0.05, "ops": 0.05, "unknown": 0.05},
                )
            ), 10
        if "/handle" in url:
            return MockResponse(make_handle_response("search-service")), 20
        raise ValueError(f"Unexpected URL: {url}")

    with patch("app.main.timed_post", side_effect=mock_post):
        resp = client.post(
            "/api/request",
            json={"request_id": custom_id, "text": "test query"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["request_id"] == custom_id


def test_trace_aggregation(client, mock_http):
    async def mock_post(url, json, headers):
        if "/classify" in url:
            return MockResponse(
                make_classify_response(
                    "search",
                    0.85,
                    {"search": 0.85, "image": 0.05, "ops": 0.05, "unknown": 0.05},
                )
            ), 10
        if "/handle" in url:
            return MockResponse(make_handle_response("search-service")), 20
        raise ValueError(f"Unexpected URL: {url}")

    with patch("app.main.timed_post", side_effect=mock_post):
        resp = client.post(
            "/api/request",
            json={
                "text": "test query",
                "trace": [{"service": "web", "event": "submit", "ts": "2024-01-01T00:00:00.000+00:00"}],
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    trace = data["trace"]

    services = [t["service"] for t in trace]
    assert "web" in services
    assert "gateway" in services
    assert "ai-router" in services
    assert "search-service" in services

    events = [t["event"] for t in trace]
    assert "submit" in events
    assert "received" in events
    assert "classified" in events
    assert "handled" in events
    assert "responded" in events


def test_timings_present(client, mock_http):
    async def mock_post(url, json, headers):
        if "/classify" in url:
            return MockResponse(
                make_classify_response(
                    "search",
                    0.85,
                    {"search": 0.85, "image": 0.05, "ops": 0.05, "unknown": 0.05},
                )
            ), 15
        if "/handle" in url:
            return MockResponse(make_handle_response("search-service")), 25
        raise ValueError(f"Unexpected URL: {url}")

    with patch("app.main.timed_post", side_effect=mock_post):
        resp = client.post(
            "/api/request",
            json={"text": "test query"},
        )

    assert resp.status_code == 200
    data = resp.json()
    timings = data["timings_ms"]
    assert "classify" in timings
    assert "proxy" in timings
    assert "total" in timings
    assert timings["classify"] == 15
    assert timings["proxy"] == 25
    assert timings["total"] >= timings["classify"] + timings["proxy"]
