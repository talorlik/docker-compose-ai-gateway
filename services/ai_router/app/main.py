"""AI router service - intent classification."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

BUILD_MODEL_PATH = "/app/model/model.joblib"


class JsonFormatter(logging.Formatter):
    """JSON-structured log format for request_id correlation (TECH-20)."""

    def format(self, record: logging.LogRecord) -> str:
        obj: Dict[str, Any] = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "service": record.name,
            "msg": record.getMessage(),
        }
        if hasattr(record, "request_id"):
            obj["request_id"] = record.request_id
        return json.dumps(obj)


def setup_logging(service_name: str, level: str = "INFO") -> logging.Logger:
    """Configure JSON logging for request correlation (TECH-20.1)."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    _logger = logging.getLogger(service_name)
    _logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    _logger.addHandler(handler)
    return _logger


logger = setup_logging("ai-router", os.getenv("LOG_LEVEL", "INFO"))


def load_model():
    """Load from MODEL_PATH if set and exists, else build-time artifact (TECH-7.5)."""
    volume_path = os.getenv("MODEL_PATH")
    if volume_path and os.path.exists(volume_path):
        path_to_load = volume_path
    elif os.path.exists(BUILD_MODEL_PATH):
        path_to_load = BUILD_MODEL_PATH
    else:
        tried = [p for p in (volume_path, BUILD_MODEL_PATH) if p]
        raise RuntimeError(f"Model not found. Tried: {tried}")
    artifact = joblib.load(path_to_load)
    return artifact["vectorizer"], artifact["model"], artifact["labels"]


def top_contributing_tokens(
    text: str,
    vectorizer,
    model,
    labels: List[str],  # noqa: ARG001
    top_n: int = 6,
) -> Tuple[str, float, Dict[str, float], List[str]]:
    X = vectorizer.transform([text])

    classes = list(model.classes_)
    probs = model.predict_proba(X)[0]
    pred_idx = int(np.argmax(probs))
    pred_label = classes[pred_idx]
    confidence = float(probs[pred_idx])
    probs_map = {classes[i]: float(probs[i]) for i in range(len(classes))}

    feature_names = vectorizer.get_feature_names_out()

    if not hasattr(model, "coef_"):
        return pred_label, confidence, probs_map, []

    class_coef = model.coef_[pred_idx]

    indices = X.indices
    values = X.data

    if indices.size == 0:
        return pred_label, confidence, probs_map, []

    contrib = values * class_coef[indices]
    order = np.argsort(contrib)[::-1]

    top_tokens: List[str] = []
    for i in order[:top_n]:
        top_tokens.append(str(feature_names[indices[i]]))

    return pred_label, confidence, probs_map, top_tokens


class TraceEntry(BaseModel):
    service: str
    event: str
    ts: str
    meta: Optional[Dict[str, Any]] = None


def make_trace_entry(
    service: str,
    event: str,
    meta: Optional[Dict[str, Any]] = None,
) -> TraceEntry:
    return TraceEntry(
        service=service,
        event=event,
        ts=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        meta=meta,
    )


class ClassifyRequest(BaseModel):
    request_id: str
    text: str = Field(..., max_length=10000)


class ClassifyResponse(BaseModel):
    route: str
    confidence: float
    probabilities: Dict[str, float]
    explanation: str
    top_tokens: List[str]
    trace_append: Dict[str, Any]


@asynccontextmanager
async def lifespan(application: FastAPI):
    vec, mdl, labels = load_model()
    application.state.vectorizer = vec
    application.state.model = mdl
    application.state.labels = labels
    application.state.model_loaded = True
    yield


app = FastAPI(title="AI Router", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health():
    """Health check - verifies model is loaded."""
    if not getattr(app.state, "model_loaded", False):
        return {"status": "not_ready"}
    return {"status": "ok"}


@app.post("/classify", response_model=ClassifyResponse)
async def classify(req: ClassifyRequest):
    logger.info(
        "classify request",
        extra={"request_id": req.request_id},
    )
    try:
        pred_label, confidence, probs_map, tokens = await asyncio.to_thread(
            top_contributing_tokens,
            req.text,
            app.state.vectorizer,
            app.state.model,
            app.state.labels,
            6,
        )
    except (ValueError, TypeError, KeyError, AttributeError, OSError) as exc:
        logger.error("Inference error: %s", exc, extra={"request_id": req.request_id})
        return JSONResponse(
            status_code=500,
            content={"detail": "Classification inference failed"},
        )

    explanation = f"top tokens: {', '.join(tokens)}" if tokens else ""

    trace = make_trace_entry(
        service="ai-router",
        event="classified",
        meta={
            "route": pred_label,
            "confidence": round(confidence, 4),
        },
    )

    logger.info(
        "classified route=%s confidence=%.4f",
        pred_label,
        confidence,
        extra={"request_id": req.request_id},
    )
    return ClassifyResponse(
        route=pred_label,
        confidence=round(confidence, 4),
        probabilities={k: round(v, 4) for k, v in probs_map.items()},
        explanation=explanation,
        top_tokens=tokens,
        trace_append=trace.model_dump(),
    )
