"""Gateway refine proxy tests with mocked training-api."""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, patch

import pytest  # pylint: disable=import-error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# Ensure we import the gateway service's `app` package (this repo has multiple).
for k in list(sys.modules.keys()):
    if k == "app" or k.startswith("app."):
        sys.modules.pop(k, None)

from fastapi.testclient import TestClient  # pylint: disable=import-error  # noqa: E402
from app.main import app  # pylint: disable=import-error  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


class MockResponse:
    def __init__(self, json_data: dict, status_code: int = 200):
        self._json_data = json_data
        self.status_code = status_code

    def json(self):
        return self._json_data


def test_proxy_post_refine_relabel(client):
    async def mock_post(url, json=None, headers=None):  # noqa: ANN001
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
    async def mock_post(url, json=None, headers=None):  # noqa: ANN001
        _ = (json, headers)
        assert url.endswith("/refine/augment")
        return MockResponse({"job_id": "jid2", "run_id": "rid2"})

    with patch.object(app.state, "http", AsyncMock(), create=True) as mock_http:
        mock_http.post = AsyncMock(side_effect=mock_post)
        resp = client.post("/api/refine/augment")
        assert resp.status_code == 200
        assert resp.json()["job_id"] == "jid2"
        assert resp.json()["run_id"] == "rid2"
