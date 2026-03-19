"""Training API - FastAPI service for train/refine/promote flows.

Per TRAIN_AND_REFINE_GUI_PAGES_TECH: job state in Redis, event-driven
completion via SSE. Batch 5: train endpoints. Batch 6: refine and promote.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.jobs.runner import (
    _refiner_error_short_message,
    get_last_train_result,
    run_promote,
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
from app.refine.augment import run_augment_phase
from app.refine.config import RefineConfig
from app.refine.relabel import run_relabel_phase

# Redis key/channel patterns (TECH §3)
TRAIN_KEY_PREFIX = "job:train:"
TRAIN_EVENTS_CHANNEL_PREFIX = "job:train:events:"
REFINE_RELABEL_KEY_PREFIX = "job:refine:relabel:"
REFINE_RELABEL_EVENTS_CHANNEL_PREFIX = "job:refine:relabel:events:"
REFINE_AUGMENT_KEY_PREFIX = "job:refine:augment:"
REFINE_AUGMENT_EVENTS_CHANNEL_PREFIX = "job:refine:augment:events:"

logger = logging.getLogger(__name__)
JOB_RUNNER_ERRORS = (
    RuntimeError,
    ValueError,
    OSError,
    FileNotFoundError,
    TimeoutError,
    KeyError,
    TypeError,
)

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _safe_run_id(raw: str) -> str:
    """Accept only canonical UUID run IDs for path usage."""
    try:
        return str(uuid.UUID(raw))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid run_id format") from exc


def _safe_artifact_path(artifacts_dir: str, filename: str) -> str:
    base = Path(artifacts_dir).resolve()
    target = (base / filename).resolve()
    if target.parent != base:
        raise HTTPException(status_code=400, detail="Invalid artifact path")
    return str(target)


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
    except JOB_RUNNER_ERRORS as e:
        set_job_state(key, {
            "status": "failed",
            "error": str(e),
            "created_at": now,
        })
        publish_job_event(channel, {"status": "failed", "error": str(e)})
    except Exception as e:
        logger.exception("Train job failed with unexpected error")
        set_job_state(key, {
            "status": "failed",
            "error": "Internal error - check server logs",
            "created_at": now,
        })
        publish_job_event(channel, {"status": "failed", "error": "Internal error"})


def _relabel_job_runner(job_id: str, run_id: str) -> None:
    key = f"{REFINE_RELABEL_KEY_PREFIX}{job_id}"
    channel = f"{REFINE_RELABEL_EVENTS_CHANNEL_PREFIX}{job_id}"
    now = datetime.now(timezone.utc).isoformat()

    def _progress(detail: str) -> None:
        """Publish a progress event to the SSE channel."""
        publish_job_event(channel, {"status": "progress", "detail": detail})

    try:
        cfg = RefineConfig.from_env(os.environ.get("MODEL_ARTIFACTS_PATH", "/model"))
        artifacts_dir = os.environ.get("MODEL_ARTIFACTS_PATH", "/model")
        promote_dir = os.environ.get("PROMOTE_TARGET_PATH", "/promote_target")
        result = run_relabel_phase(
            cfg,
            model_artifacts_path=artifacts_dir,
            promote_target_path=promote_dir,
            run_id=run_id,
            progress=lambda ev: _progress(ev.get("detail", "Running...")),
        )
        set_job_state(key, {
            "status": "completed",
            "result": result,
            "created_at": now,
        })
        publish_job_event(channel, {"status": "completed", "result": result})
    except JOB_RUNNER_ERRORS as e:
        full_error = str(e)
        short_error = getattr(e, "short_message", None) or _refiner_error_short_message(full_error)
        logger.exception("Relabel job failed")
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
    except Exception as e:
        logger.exception("Relabel job failed with unexpected error")
        set_job_state(key, {
            "status": "failed",
            "error": "Internal error - check server logs",
            "created_at": now,
        })
        publish_job_event(channel, {"status": "failed", "error": "Internal error"})


def _augment_job_runner(job_id: str, run_id: str) -> None:
    key = f"{REFINE_AUGMENT_KEY_PREFIX}{job_id}"
    channel = f"{REFINE_AUGMENT_EVENTS_CHANNEL_PREFIX}{job_id}"
    now = datetime.now(timezone.utc).isoformat()

    def _progress(detail: str) -> None:
        publish_job_event(channel, {"status": "progress", "detail": detail})

    try:
        cfg = RefineConfig.from_env(os.environ.get("MODEL_ARTIFACTS_PATH", "/model"))
        artifacts_dir = os.environ.get("MODEL_ARTIFACTS_PATH", "/model")
        promote_dir = os.environ.get("PROMOTE_TARGET_PATH", "/promote_target")
        result = run_augment_phase(
            cfg,
            model_artifacts_path=artifacts_dir,
            promote_target_path=promote_dir,
            run_id=run_id,
            progress=lambda ev: _progress(ev.get("detail", "Running...")),
        )
        set_job_state(key, {
            "status": "completed",
            "result": result,
            "created_at": now,
        })
        publish_job_event(channel, {"status": "completed", "result": result})
    except JOB_RUNNER_ERRORS as e:
        full_error = str(e)
        short_error = getattr(e, "short_message", None) or _refiner_error_short_message(full_error)
        logger.exception("Augment job failed")
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
    except Exception as e:
        logger.exception("Augment job failed with unexpected error")
        set_job_state(key, {
            "status": "failed",
            "error": "Internal error - check server logs",
            "created_at": now,
        })
        publish_job_event(channel, {"status": "failed", "error": "Internal error"})


@asynccontextmanager
async def lifespan(application: FastAPI):
    _validate_redis_on_startup()
    yield


app = FastAPI(
    title="Training API",
    description="Train, refine, and promote flows with Redis-backed job state.",
    lifespan=lifespan,
)


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
    job_id = _safe_run_id(job_id)
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
    job_id = _safe_run_id(job_id)
    return StreamingResponse(
        _train_events_sse_generator(job_id),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@app.get("/train/last")
def get_train_last() -> dict:
    """Read last run from volume (fixed path MODEL_ARTIFACTS_PATH or /model). 404 if absent."""
    result = get_last_train_result()
    if result is None:
        raise HTTPException(status_code=404, detail="No previous train run found")
    return result


# Refine endpoints (Batch 6)
@app.post("/refine/relabel")
def post_refine_relabel() -> dict:
    job_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    key = f"{REFINE_RELABEL_KEY_PREFIX}{job_id}"
    now = datetime.now(timezone.utc).isoformat()
    set_job_state(key, {"status": "pending", "created_at": now, "run_id": run_id})
    thread = threading.Thread(target=_relabel_job_runner, args=(job_id, run_id))
    thread.daemon = True
    thread.start()
    return {"job_id": job_id, "run_id": run_id}


def _relabel_events_sse_generator(job_id: str):
    key = f"{REFINE_RELABEL_KEY_PREFIX}{job_id}"
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
    channel = f"{REFINE_RELABEL_EVENTS_CHANNEL_PREFIX}{job_id}"
    for message in subscribe_to_job_channel_until_done(channel):
        yield f"data: {message}\n\n"


@app.get("/refine/relabel/events/{job_id}")
def get_refine_relabel_events(job_id: str):
    job_id = _safe_run_id(job_id)
    return StreamingResponse(
        _relabel_events_sse_generator(job_id),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@app.post("/refine/augment")
def post_refine_augment() -> dict:
    job_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    key = f"{REFINE_AUGMENT_KEY_PREFIX}{job_id}"
    now = datetime.now(timezone.utc).isoformat()
    set_job_state(key, {"status": "pending", "created_at": now, "run_id": run_id})
    thread = threading.Thread(target=_augment_job_runner, args=(job_id, run_id))
    thread.daemon = True
    thread.start()
    return {"job_id": job_id, "run_id": run_id}


def _augment_events_sse_generator(job_id: str):
    key = f"{REFINE_AUGMENT_KEY_PREFIX}{job_id}"
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
    channel = f"{REFINE_AUGMENT_EVENTS_CHANNEL_PREFIX}{job_id}"
    for message in subscribe_to_job_channel_until_done(channel):
        yield f"data: {message}\n\n"


@app.get("/refine/augment/events/{job_id}")
def get_refine_augment_events(job_id: str):
    job_id = _safe_run_id(job_id)
    return StreamingResponse(
        _augment_events_sse_generator(job_id),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


class PromoteRequest(BaseModel):
    run_id: str | None = None


@app.post("/refine/promote")
def post_refine_promote(body: PromoteRequest) -> dict:
    """Promote a run's candidate dataset if metrics improved.

    If run_id is omitted, fall back to legacy behavior (train_candidate.csv in
    root artifacts dir).
    """
    if body.run_id:
        import shutil

        artifacts_dir = os.environ.get("MODEL_ARTIFACTS_PATH", "/model")
        run_id = _safe_run_id(body.run_id)
        cfg = RefineConfig.from_env(artifacts_dir)
        cand = cfg.augment_candidate_csv(run_id)
        before = cfg.metrics_before_path(run_id)
        if not cand.exists():
            cand = cfg.relabel_candidate_csv(run_id)
        if not cand.exists():
            raise HTTPException(status_code=400, detail="No candidate CSV found for run_id")

        shutil.copy2(cand, _safe_artifact_path(artifacts_dir, "train_candidate.csv"))
        if before.exists():
            shutil.copy2(before, _safe_artifact_path(artifacts_dir, "metrics_before.json"))
    try:
        return run_promote()
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
