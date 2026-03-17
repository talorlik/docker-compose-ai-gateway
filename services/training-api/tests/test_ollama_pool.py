"""Unit tests for OllamaPool: selection, health checks, generate."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

from import_training_api import training_api_imported

with training_api_imported():
    from app.refine import ollama_pool as pool_mod
    from app.refine.ollama_pool import OllamaPool, get_ollama_pool
    import requests as _requests_mod


URLS = ["http://ollama1:11434", "http://ollama2:11434", "http://ollama3:11434"]


def _make_pool(**overrides) -> OllamaPool:
    defaults = dict(
        urls=URLS,
        model="phi3:mini",
        timeout_seconds=10,
        max_inflight_per_instance=2,
        num_ctx=512,
        num_predict=128,
    )
    defaults.update(overrides)
    return OllamaPool(**defaults)


# --- acquire / release ---


def test_acquire_returns_url_from_pool():
    pool = _make_pool()
    with pool._lock:
        for inst in pool._instances.values():
            inst.healthy = True
    url = pool.acquire()
    assert url in URLS


def test_acquire_selects_least_inflight():
    pool = _make_pool()
    with pool._lock:
        for inst in pool._instances.values():
            inst.healthy = True
        pool._instances[URLS[0]].inflight = 2
        pool._instances[URLS[1]].inflight = 1
        pool._instances[URLS[2]].inflight = 0
    url = pool.acquire()
    assert url == URLS[2]


def test_acquire_increments_inflight():
    pool = _make_pool()
    with pool._lock:
        for inst in pool._instances.values():
            inst.healthy = True
    url = pool.acquire()
    with pool._lock:
        assert pool._instances[url].inflight == 1


def test_release_decrements_inflight():
    pool = _make_pool()
    with pool._lock:
        pool._instances[URLS[0]].healthy = True
        pool._instances[URLS[0]].inflight = 1
    pool.release(URLS[0])
    with pool._lock:
        assert pool._instances[URLS[0]].inflight == 0


def test_release_does_not_go_below_zero():
    pool = _make_pool()
    pool.release(URLS[0])
    with pool._lock:
        assert pool._instances[URLS[0]].inflight == 0


def test_release_unknown_url_is_noop():
    pool = _make_pool()
    pool.release("http://unknown:11434")  # should not raise


def test_acquire_skips_unhealthy_instances():
    pool = _make_pool()
    with pool._lock:
        pool._instances[URLS[0]].healthy = False
        pool._instances[URLS[1]].healthy = True
        pool._instances[URLS[2]].healthy = False
    url = pool.acquire()
    assert url == URLS[1]


def test_acquire_skips_instances_at_max_inflight():
    pool = _make_pool(max_inflight_per_instance=1)
    with pool._lock:
        for inst in pool._instances.values():
            inst.healthy = True
        pool._instances[URLS[0]].inflight = 1
        pool._instances[URLS[1]].inflight = 1
    url = pool.acquire()
    assert url == URLS[2]


def test_acquire_falls_back_to_unhealthy_when_none_available():
    """When all instances are unhealthy, acquire still returns the least-inflight."""
    pool = _make_pool()
    with pool._lock:
        for inst in pool._instances.values():
            inst.healthy = False
        pool._instances[URLS[0]].inflight = 2
        pool._instances[URLS[1]].inflight = 0
        pool._instances[URLS[2]].inflight = 1
    url = pool.acquire()
    assert url == URLS[1]


# --- snapshot ---


def test_snapshot_returns_all_instances():
    pool = _make_pool()
    snap = pool.snapshot()
    assert set(snap.keys()) == set(URLS)
    for info in snap.values():
        assert "healthy" in info
        assert "inflight" in info


# --- health probes ---


def test_probe_one_healthy():
    pool = _make_pool()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = json.dumps({"models": []})
    mock_resp.raise_for_status = MagicMock()

    with patch.object(pool_mod.requests, "get", return_value=mock_resp):
        healthy, err = pool._probe_one(URLS[0])
    assert healthy is True
    assert err is None


def test_probe_one_unhealthy_on_connection_error():
    pool = _make_pool()

    with patch.object(
        pool_mod.requests, "get", side_effect=_requests_mod.ConnectionError("refused")
    ):
        healthy, err = pool._probe_one(URLS[0])
    assert healthy is False
    assert err is not None
    assert "refused" in err


def test_probe_one_unhealthy_on_invalid_json():
    pool = _make_pool()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "not json"
    mock_resp.raise_for_status = MagicMock()

    with patch.object(pool_mod.requests, "get", return_value=mock_resp):
        healthy, err = pool._probe_one(URLS[0])
    assert healthy is False
    assert err is not None


# --- generate ---


def test_generate_calls_correct_endpoint():
    pool = _make_pool()
    with pool._lock:
        for inst in pool._instances.values():
            inst.healthy = True

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"response": "test output"}
    mock_resp.raise_for_status = MagicMock()

    with patch.object(pool_mod.requests, "post", return_value=mock_resp) as mock_post:
        result = pool.generate(prompt="hello", system="sys")
    assert result == "test output"

    call_args = mock_post.call_args
    url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
    assert url.endswith("/api/generate")
    payload = call_args[1].get("json") or call_args[0][1]
    assert payload["model"] == "phi3:mini"
    assert payload["prompt"] == "hello"
    assert payload["system"] == "sys"
    assert payload["stream"] is False
    assert payload["options"]["num_ctx"] == 512
    assert payload["options"]["num_predict"] == 128


def test_generate_releases_instance_on_success():
    pool = _make_pool()
    with pool._lock:
        for inst in pool._instances.values():
            inst.healthy = True

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"response": "ok"}
    mock_resp.raise_for_status = MagicMock()

    with patch.object(pool_mod.requests, "post", return_value=mock_resp):
        pool.generate(prompt="hello")
    snap = pool.snapshot()
    for info in snap.values():
        assert info["inflight"] == 0


def test_generate_releases_instance_on_error():
    pool = _make_pool()
    with pool._lock:
        for inst in pool._instances.values():
            inst.healthy = True

    with patch.object(pool_mod.requests, "post", side_effect=Exception("network error")):
        try:
            pool.generate(prompt="hello")
        except Exception:
            pass

    snap = pool.snapshot()
    for info in snap.values():
        assert info["inflight"] == 0


def test_generate_without_system_prompt():
    pool = _make_pool()
    with pool._lock:
        for inst in pool._instances.values():
            inst.healthy = True

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"response": "ok"}
    mock_resp.raise_for_status = MagicMock()

    with patch.object(pool_mod.requests, "post", return_value=mock_resp) as mock_post:
        pool.generate(prompt="hello")
    payload = mock_post.call_args[1].get("json") or mock_post.call_args[0][1]
    assert "system" not in payload


# --- start/stop probes ---


def test_probe_loop_updates_health():
    pool = _make_pool(probe_interval_seconds=0.05)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = json.dumps({"models": []})
    mock_resp.raise_for_status = MagicMock()

    with (
        patch.object(pool_mod.requests, "get", return_value=mock_resp),
        patch.object(pool_mod, "publish_event"),
    ):
        pool.start_probes()
        time.sleep(0.2)
        pool.stop_probes()

    snap = pool.snapshot()
    for info in snap.values():
        assert info["healthy"] is True
        assert info["last_checked_ts"] is not None


# --- singleton ---


def test_get_ollama_pool_singleton():
    """get_ollama_pool returns the same instance on repeated calls."""
    with pool_mod._singleton_lock:
        old = pool_mod._singleton
        pool_mod._singleton = None

    try:
        factory_calls = []

        def factory() -> OllamaPool:
            p = _make_pool()
            factory_calls.append(p)
            return p

        p1 = get_ollama_pool(factory)
        p2 = get_ollama_pool(factory)
        assert p1 is p2
        assert len(factory_calls) == 1
        p1.stop_probes()
    finally:
        with pool_mod._singleton_lock:
            if pool_mod._singleton is not None:
                pool_mod._singleton.stop_probes()
            pool_mod._singleton = old
