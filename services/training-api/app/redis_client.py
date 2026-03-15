"""Redis client and job state helpers for train/refine flows.

Per TRAIN_AND_REFINE_GUI_PAGES_TECH §3: job keys (job:train:{id},
job:refine:{id}), Pub/Sub channels (job:train:events:{id}, etc.), TTL 24h.
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterator

# Default TTL for job keys (24 hours)
JOB_STATE_TTL_SECONDS = 24 * 3600

_client: Any = None
# Separate connection for set/publish so the default connection can be used
# for SUBSCRIBE in SSE handlers (a connection in subscribe mode cannot
# execute PUBLISH or SET).
_publish_client: Any = None


def _redis_url() -> str | None:
    url = os.getenv("REDIS_URL")
    if url:
        return url
    host = os.getenv("REDIS_HOST", "redis")
    port = os.getenv("REDIS_PORT", "6379")
    if host and port:
        return f"redis://{host}:{port}/0"
    return None


def get_connection():  # noqa: ANN201
    """Return a connected Redis client for reads and subscribe. Uses REDIS_URL or REDIS_HOST/REDIS_PORT."""
    global _client
    if _client is not None:
        return _client
    url = _redis_url()
    if not url:
        raise RuntimeError(
            "Redis not configured: set REDIS_URL or REDIS_HOST and REDIS_PORT"
        )
    import redis
    _client = redis.from_url(url, decode_responses=True)
    return _client


def get_publish_connection():  # noqa: ANN201
    """Return a dedicated Redis connection for set/publish. Must be separate from
    the connection used for SUBSCRIBE (subscribe mode cannot run PUBLISH/SET).
    """
    global _publish_client
    if _publish_client is not None:
        return _publish_client
    url = _redis_url()
    if not url:
        raise RuntimeError(
            "Redis not configured: set REDIS_URL or REDIS_HOST and REDIS_PORT"
        )
    import redis
    _publish_client = redis.from_url(url, decode_responses=True)
    return _publish_client


def set_job_state(key: str, payload: dict[str, Any], ttl: int = JOB_STATE_TTL_SECONDS) -> None:
    """Store job state at key (e.g. job:train:{id}, job:refine:{id}). TTL in seconds."""
    conn = get_publish_connection()
    conn.set(key, json.dumps(payload), ex=ttl)


def get_job_state(key: str) -> dict[str, Any] | None:
    """Read job state; returns parsed JSON or None if missing/expired."""
    conn = get_connection()
    raw = conn.get(key)
    if raw is None:
        return None
    return json.loads(raw)


def publish_job_event(channel: str, payload: dict[str, Any]) -> None:
    """Publish payload to channel (e.g. job:train:events:{id}). One message per job."""
    conn = get_publish_connection()
    conn.publish(channel, json.dumps(payload))


def subscribe_to_job_channel(channel: str) -> Iterator[str]:
    """Subscribe to channel and yield the first message. Used by SSE endpoints."""
    conn = get_connection()
    pubsub = conn.pubsub()
    pubsub.subscribe(channel)
    try:
        for message in pubsub.listen():
            if message["type"] == "message":
                yield message["data"]
                break
    finally:
        pubsub.close()


def subscribe_to_job_channel_until_done(channel: str) -> Iterator[str]:
    """Subscribe to channel and yield messages until a completed/failed status is received.

    Used by refine SSE endpoint to stream progress events followed by a final result.
    """
    conn = get_connection()
    pubsub = conn.pubsub()
    pubsub.subscribe(channel)
    try:
        for message in pubsub.listen():
            if message["type"] != "message":
                continue
            data = message["data"]
            yield data
            try:
                parsed = json.loads(data)
                if parsed.get("status") in ("completed", "failed"):
                    break
            except (json.JSONDecodeError, TypeError):
                pass
    finally:
        pubsub.close()


def _verify() -> None:
    """Smoke test: set/get job state and pub/sub. Run with python -m app.redis_client."""
    import threading
    import time
    import uuid
    key = f"job:train:{uuid.uuid4()}"
    channel = f"job:train:events:{uuid.uuid4()}"
    payload = {"status": "completed", "result": {"accuracy": 0.9}}
    set_job_state(key, payload, ttl=60)
    got = get_job_state(key)
    assert got == payload, f"get_job_state: got {got}"
    received: list[str] = []

    def listen() -> None:
        first = next(subscribe_to_job_channel(channel), None)
        if first is not None:
            received.append(first)

    listener = threading.Thread(target=listen)
    listener.start()
    time.sleep(0.2)
    # publish_job_event uses get_publish_connection() so subscriber can hold default conn
    publish_job_event(channel, payload)
    listener.join(timeout=5.0)
    assert len(received) == 1, f"expected one message, got {len(received)}"
    assert json.loads(received[0]) == payload
    get_connection().delete(key)
    print("redis_client: set_job_state, get_job_state, publish_job_event, subscribe_to_job_channel OK")


if __name__ == "__main__":
    _verify()
