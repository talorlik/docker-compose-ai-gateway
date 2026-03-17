from __future__ import annotations

from unittest.mock import patch

import pytest  # pylint: disable=import-error
from fastapi.testclient import TestClient  # pylint: disable=import-error

from import_training_api import training_api_imported


@pytest.fixture(scope="module")
def client():
    with training_api_imported():
        from app.main import app  # pylint: disable=import-error
        # Avoid real Redis dependency in unit/integration tests.
        app.router.on_startup.clear()

        class _DummyThread:
            daemon = True

            def __init__(self, *args, **kwargs):  # noqa: ANN001
                _ = (args, kwargs)

            def start(self):  # noqa: ANN201
                return None

        with (
            patch("app.main.set_job_state") as _set_state,  # pylint: disable=import-error
            patch("app.main.publish_job_event") as _pub,  # pylint: disable=import-error
            patch("app.main.threading.Thread", side_effect=lambda *a, **k: _DummyThread(*a, **k)),  # pylint: disable=import-error
        ):
            _set_state.return_value = None
            _pub.return_value = None
            with TestClient(app) as c:
                yield c


def test_post_relabel_returns_job_and_run_id(client):
    resp = client.post("/refine/relabel")
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data and data["job_id"]
    assert "run_id" in data and data["run_id"]


def test_post_augment_returns_job_and_run_id(client):
    resp = client.post("/refine/augment")
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data and data["job_id"]
    assert "run_id" in data and data["run_id"]


def test_relabel_events_completed_immediate(client):
    job_id = "job123"

    with patch("app.main.get_job_state") as mock_get:  # pylint: disable=import-error
        mock_get.return_value = {
            "status": "completed",
            "result": {"ok": True},
        }
        resp = client.get(f"/refine/relabel/events/{job_id}")
        assert resp.status_code == 200
        body = resp.text
        assert "data:" in body
        assert '"status": "completed"' in body
        assert '"ok": true' in body.lower()


def test_augment_events_failed_immediate(client):
    job_id = "job456"
    with patch("app.main.get_job_state") as mock_get:  # pylint: disable=import-error
        mock_get.return_value = {
            "status": "failed",
            "error": "boom",
            "error_detail": "full",
        }
        resp = client.get(f"/refine/augment/events/{job_id}")
        assert resp.status_code == 200
        body = resp.text
        assert '"status": "failed"' in body
        assert "boom" in body
