from __future__ import annotations

from unittest.mock import patch, MagicMock

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
            patch("app.main._validate_redis_on_startup"),
            patch("app.redis_client.get_connection") as _get_conn,
            patch("app.redis_client.get_publish_connection") as _get_pub_conn,
        ):
            _set_state.return_value = None
            _pub.return_value = None
            _get_conn.return_value = MagicMock()
            _get_pub_conn.return_value = MagicMock()
            _get_pub_conn.return_value = MagicMock()
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
    job_id = "a1337000-0000-0000-0000-000000000001"

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
    job_id = "a1337000-0000-0000-0000-000000000002"
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


def test_post_relabel_sets_pending_state(client):
    """POST /refine/relabel should call set_job_state with pending status."""
    with (
        patch("app.main.set_job_state") as mock_set,
        patch("app.main.threading.Thread", side_effect=lambda *a, **k: type(
            "T", (), {"daemon": True, "start": lambda self: None}
        )()),
        patch("app.redis_client.get_connection"),
        patch("app.redis_client.get_publish_connection"),
    ):
        resp = client.post("/refine/relabel")
        assert resp.status_code == 200
        call_args = mock_set.call_args
        assert call_args is not None
        key, payload = call_args[0]
        assert key.startswith("job:refine:relabel:")
        assert payload["status"] == "pending"
        assert "run_id" in payload


def test_post_augment_sets_pending_state(client):
    """POST /refine/augment should call set_job_state with pending status."""
    with (
        patch("app.main.set_job_state") as mock_set,
        patch("app.main.threading.Thread", side_effect=lambda *a, **k: type(
            "T", (), {"daemon": True, "start": lambda self: None}
        )()),
        patch("app.redis_client.get_connection"),
        patch("app.redis_client.get_publish_connection"),
    ):
        resp = client.post("/refine/augment")
        assert resp.status_code == 200
        call_args = mock_set.call_args
        assert call_args is not None
        key, payload = call_args[0]
        assert key.startswith("job:refine:augment:")
        assert payload["status"] == "pending"


def test_relabel_events_error_detail_included(client):
    """When job failed, error_detail should be in the SSE payload."""
    with patch("app.main.get_job_state") as mock_get:
        mock_get.return_value = {
            "status": "failed",
            "error": "short",
            "error_detail": "long detailed error message",
        }
        resp = client.get("/refine/relabel/events/a1337000-0000-0000-0000-000000000003")
        assert resp.status_code == 200
        assert "long detailed error message" in resp.text


def test_relabel_events_pending_does_not_yield_immediately(client):
    """If job is still pending, SSE should not return a completed/failed payload."""
    with (
        patch("app.main.get_job_state") as mock_get,
        patch("app.main.subscribe_to_job_channel_until_done", return_value=iter([])),
    ):
        mock_get.return_value = {"status": "pending"}
        resp = client.get("/refine/relabel/events/a1337000-0000-0000-0000-000000000004")
        assert resp.status_code == 200
        assert '"status": "completed"' not in resp.text
        assert '"status": "failed"' not in resp.text


def test_post_relabel_job_id_and_run_id_are_uuids(client):
    resp = client.post("/refine/relabel")
    data = resp.json()
    import uuid
    uuid.UUID(data["job_id"])
    uuid.UUID(data["run_id"])
