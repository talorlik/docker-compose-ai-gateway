"""Training API - FastAPI service for train/refine/promote flows.

Per TRAIN_AND_REFINE_GUI_PAGES_TECH: job state in Redis, event-driven
completion via SSE. Batch 5: train endpoints. Batch 6: refine and promote.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from app.jobs.runner import (
    _refiner_error_short_message,
    get_last_refine_result,
    get_last_train_result,
    run_promote,
    run_refine,
    run_train,
)
from app.redis_client import (
    get_connection,
    get_job_state,
    publish_job_event,
    set_job_state,
    subscribe_to_job_channel,
    subscribe_to_job_channel_until_done,
)

# Redis key/channel patterns (TECH §3)
TRAIN_KEY_PREFIX = "job:train:"
TRAIN_EVENTS_CHANNEL_PREFIX = "job:train:events:"
REFINE_KEY_PREFIX = "job:refine:"
REFINE_EVENTS_CHANNEL_PREFIX = "job:refine:events:"

logger = logging.getLogger(__name__)


def _validate_redis_on_startup() -> None:
    try:
        get_connection().ping()
    except Exception as e:
        raise RuntimeError(f"Redis connection failed: {e}") from e


def _train_job_runner(job_id: str) -> None:
    """Background: SET pending already done by caller; run_train(); SET result + PUBLISH."""
    key = f"{TRAIN_KEY_PREFIX}{job_id}"
    channel = f"{TRAIN_EVENTS_CHANNEL_PREFIX}{job_id}"
    now = datetime.now(timezone.utc).isoformat()
    try:
        result = run_train()
        set_job_state(key, {
            "status": "completed",
            "result": result,
            "created_at": now,
        })
        publish_job_event(channel, {"status": "completed", "result": result})
    except Exception as e:
        set_job_state(key, {
            "status": "failed",
            "error": str(e),
            "created_at": now,
        })
        publish_job_event(channel, {"status": "failed", "error": str(e)})


def _refine_job_runner(job_id: str) -> None:
    """Background: SET pending already done by caller; run_refine(); SET result + PUBLISH."""
    key = f"{REFINE_KEY_PREFIX}{job_id}"
    channel = f"{REFINE_EVENTS_CHANNEL_PREFIX}{job_id}"
    now = datetime.now(timezone.utc).isoformat()

    def _progress(detail: str) -> None:
        """Publish a progress event to the SSE channel."""
        publish_job_event(channel, {"status": "progress", "detail": detail})

    try:
        result = run_refine(progress_callback=_progress)
        set_job_state(key, {
            "status": "completed",
            "result": result,
            "created_at": now,
        })
        publish_job_event(channel, {"status": "completed", "result": result})
    except Exception as e:
        full_error = str(e)
        short_error = getattr(e, "short_message", None) or _refiner_error_short_message(full_error)
        logger.exception("Refine job failed")
        set_job_state(key, {
            "status": "failed",
            "error": short_error,
            "error_detail": full_error,
            "created_at": now,
        })
        publish_job_event(channel, {
            "status": "failed",
            "error": short_error,
            "error_detail": full_error,
        })


app = FastAPI(
    title="Training API",
    description="Train, refine, and promote flows with Redis-backed job state.",
)


@app.on_event("startup")
def startup() -> None:
    _validate_redis_on_startup()


@app.get("/health")
def health() -> dict:
    """Health check; returns 200 when service and Redis are available."""
    return {"status": "ok"}


@app.post("/train")
def post_train() -> dict:
    """Create job; SET pending; start background run_train(); return job_id immediately."""
    job_id = str(uuid.uuid4())
    key = f"{TRAIN_KEY_PREFIX}{job_id}"
    now = datetime.now(timezone.utc).isoformat()
    set_job_state(key, {"status": "pending", "created_at": now})
    thread = threading.Thread(target=_train_job_runner, args=(job_id,))
    thread.daemon = True
    thread.start()
    return {"job_id": job_id}


@app.get("/train/status/{job_id}")
def get_train_status(job_id: str) -> dict:
    """Read Redis key; return job_id, status, result, error; 404 if missing."""
    key = f"{TRAIN_KEY_PREFIX}{job_id}"
    state = get_job_state(key)
    if state is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    return {
        "job_id": job_id,
        "status": state.get("status", "unknown"),
        "result": state.get("result"),
        "error": state.get("error"),
    }


def _train_events_sse_generator(job_id: str):
    """Yield SSE data lines from Redis channel; first message then stop.
    If job already completed/failed (e.g. client connected late), send state immediately.
    """
    key = f"{TRAIN_KEY_PREFIX}{job_id}"
    state = get_job_state(key)
    if state and state.get("status") in ("completed", "failed"):
        payload = {"status": state["status"]}
        if state.get("result") is not None:
            payload["result"] = state["result"]
        if state.get("error") is not None:
            payload["error"] = state["error"]
        yield f"data: {json.dumps(payload)}\n\n"
        return
    channel = f"{TRAIN_EVENTS_CHANNEL_PREFIX}{job_id}"
    for message in subscribe_to_job_channel(channel):
        yield f"data: {message}\n\n"
        break


@app.get("/train/events/{job_id}")
def get_train_events(job_id: str):
    """SSE: SUBSCRIBE to job channel; stream first message as SSE; close. Handles disconnect via stream end."""
    return StreamingResponse(
        _train_events_sse_generator(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/train/last")
def get_train_last() -> dict:
    """Read last run from volume (fixed path MODEL_ARTIFACTS_PATH or /model). 404 if absent."""
    result = get_last_train_result()
    if result is None:
        raise HTTPException(status_code=404, detail="No previous train run found")
    return result


# Refine endpoints (Batch 6)
@app.post("/refine")
def post_refine() -> dict:
    """Create job; SET pending; start background run_refine(); return job_id immediately."""
    job_id = str(uuid.uuid4())
    key = f"{REFINE_KEY_PREFIX}{job_id}"
    now = datetime.now(timezone.utc).isoformat()
    set_job_state(key, {"status": "pending", "created_at": now})
    thread = threading.Thread(target=_refine_job_runner, args=(job_id,))
    thread.daemon = True
    thread.start()
    return {"job_id": job_id}


@app.get("/refine/status/{job_id}")
def get_refine_status(job_id: str) -> dict:
    """Read Redis key; return job_id, status, result, error; 404 if missing."""
    key = f"{REFINE_KEY_PREFIX}{job_id}"
    state = get_job_state(key)
    if state is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    return {
        "job_id": job_id,
        "status": state.get("status", "unknown"),
        "result": state.get("result"),
        "error": state.get("error"),
    }


def _refine_events_sse_generator(job_id: str):
    """Yield SSE data lines from Redis refine channel; streams progress then final result.
    If job already completed/failed (e.g. client connected late), send state immediately.
    """
    key = f"{REFINE_KEY_PREFIX}{job_id}"
    state = get_job_state(key)
    if state and state.get("status") in ("completed", "failed"):
        payload = {"status": state["status"]}
        if state.get("result") is not None:
            payload["result"] = state["result"]
        if state.get("error") is not None:
            payload["error"] = state["error"]
        if state.get("error_detail") is not None:
            payload["error_detail"] = state["error_detail"]
        yield f"data: {json.dumps(payload)}\n\n"
        return
    channel = f"{REFINE_EVENTS_CHANNEL_PREFIX}{job_id}"
    for message in subscribe_to_job_channel_until_done(channel):
        yield f"data: {message}\n\n"


@app.get("/refine/events/{job_id}")
def get_refine_events(job_id: str):
    """SSE: SUBSCRIBE to refine channel; stream first message as SSE; close."""
    return StreamingResponse(
        _refine_events_sse_generator(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/refine/last")
def get_refine_last() -> dict:
    """Read last refine run from volume. 404 if absent."""
    result = get_last_refine_result()
    if result is None:
        raise HTTPException(status_code=404, detail="No previous refine run found")
    return result


@app.post("/refine/promote")
def post_refine_promote() -> dict:
    """Synchronous run_promote(); return promoted, message, acc_before, acc_after. 400 if train_candidate missing."""
    try:
        return run_promote()
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
