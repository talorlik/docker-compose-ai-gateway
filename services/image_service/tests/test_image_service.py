"""Unit tests for image service /handle and /health endpoints."""

from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

_SERVICE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

_saved_app = {k: sys.modules.pop(k) for k in list(sys.modules) if k == "app" or k.startswith("app.")}
sys.path.insert(0, _SERVICE_ROOT)

from app.main import app  # noqa: E402

_image_app = app

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
    with TestClient(_image_app) as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_handle_returns_200(client):
    resp = client.post(
        "/handle",
        json={"request_id": "test-001", "text": "resize this image to 800x600"},
    )
    assert resp.status_code == 200


def test_handle_response_shape(client):
    resp = client.post(
        "/handle",
        json={"request_id": "test-002", "text": "convert image to PNG"},
    )
    data = resp.json()
    assert "payload" in data
    assert "trace_append" in data

    payload = data["payload"]
    assert payload["service"] == "image-service"
    assert "result" in payload
    assert "instance" in payload
    assert "detected_labels" in payload
    assert "dimensions" in payload

    trace = data["trace_append"]
    assert trace["service"] == "image-service"
    assert trace["event"] == "handled"
    assert "ts" in trace
    assert trace["meta"]["status"] == 200


def test_handle_includes_request_text_in_result(client):
    text = "analyze this photograph"
    resp = client.post(
        "/handle",
        json={"request_id": "test-003", "text": text},
    )
    data = resp.json()
    assert text in data["payload"]["result"]


def test_handle_missing_text_returns_422(client):
    resp = client.post("/handle", json={"request_id": "test-004"})
    assert resp.status_code == 422


def test_handle_text_max_length(client):
    long_text = "a" * 10001
    resp = client.post(
        "/handle",
        json={"request_id": "test-005", "text": long_text},
    )
    assert resp.status_code == 422
