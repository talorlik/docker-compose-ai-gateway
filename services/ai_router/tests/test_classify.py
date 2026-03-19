"""Unit tests for ai-router /classify endpoint."""

from __future__ import annotations

import importlib.util
import os
import sys

import pytest
from fastapi.testclient import TestClient

_SERVICE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
MODEL_PATH = os.path.join(_SERVICE_ROOT, "model", "model.joblib")
os.environ["MODEL_PATH"] = MODEL_PATH

sys.path.insert(0, _SERVICE_ROOT)

_saved_app = {k: sys.modules.pop(k) for k in list(sys.modules) if k == "app" or k.startswith("app.")}

from app.main import app  # noqa: E402

_ai_router_app = app

for k in list(sys.modules):
    if k == "app" or k.startswith("app."):
        sys.modules.pop(k, None)
sys.modules.update(_saved_app)
try:
    sys.path.remove(_SERVICE_ROOT)
except ValueError:
    pass


@pytest.fixture(scope="module")
def client():
    with TestClient(_ai_router_app) as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.parametrize(
    "text,expected_route",
    [
        ("compare nginx ingress vs traefik for kubernetes", "search"),
        ("resize image to 800x600 and convert to PNG", "image"),
        ("kubectl get pods shows CrashLoopBackOff", "ops"),
    ],
)
def test_classify_known_routes(client, text: str, expected_route: str):
    resp = client.post(
        "/classify",
        json={"request_id": "test-001", "text": text},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["route"] == expected_route


def test_classify_unknown_route(client):
    resp = client.post(
        "/classify",
        json={"request_id": "test-002", "text": "hello how are you"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["route"] == "unknown"


def test_classify_response_shape(client):
    resp = client.post(
        "/classify",
        json={"request_id": "test-003", "text": "search for kubernetes tutorials"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert "route" in data
    assert "confidence" in data
    assert "probabilities" in data
    assert "explanation" in data
    assert "top_tokens" in data
    assert "trace_append" in data

    assert isinstance(data["confidence"], float)
    assert 0.0 <= data["confidence"] <= 1.0

    probs = data["probabilities"]
    assert set(probs.keys()) == {"search", "image", "ops", "unknown"}
    for v in probs.values():
        assert 0.0 <= v <= 1.0
    assert abs(sum(probs.values()) - 1.0) < 0.01

    assert isinstance(data["top_tokens"], list)
    assert len(data["top_tokens"]) <= 6

    trace = data["trace_append"]
    assert trace["service"] == "ai-router"
    assert trace["event"] == "classified"
    assert "ts" in trace
    assert "meta" in trace
    assert "route" in trace["meta"]
    assert "confidence" in trace["meta"]


def test_classify_explanation_contains_tokens(client):
    resp = client.post(
        "/classify",
        json={"request_id": "test-004", "text": "deploy helm chart to production cluster"},
    )
    data = resp.json()
    if data["top_tokens"]:
        assert "top tokens:" in data["explanation"]
        for token in data["top_tokens"]:
            assert token in data["explanation"]
