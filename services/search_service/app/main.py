"""Search service - backend for search intents (FR-010, FR-067)."""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI
from pydantic import BaseModel


class JsonFormatter(logging.Formatter):
    """JSON-structured log format for request_id correlation (TECH-20)."""

    def format(self, record: logging.LogRecord) -> str:
        obj = {
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
    logger = logging.getLogger(service_name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.addHandler(handler)
    return logger


logger = setup_logging("search-service", os.environ.get("LOG_LEVEL", "INFO"))


class TraceEntry(BaseModel):
    """Trace entry schema: service, event, ts (ISO 8601), optional meta."""

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


class HandleRequest(BaseModel):
    request_id: str
    text: str


class HandleResponse(BaseModel):
    payload: Dict[str, Any]
    trace_append: Dict[str, Any]


app = FastAPI(title="Search Service", version="0.1.0")


@app.get("/health")
async def health():
    """Health check for Compose/load balancers."""
    return {"status": "ok"}


@app.post("/handle", response_model=HandleResponse)
async def handle(req: HandleRequest):
    """Handle search intent: simulated lookup payload and trace entry."""
    logger.info(
        "handle request",
        extra={"request_id": req.request_id},
    )
    instance = socket.gethostname()
    payload = {
        "service": "search-service",
        "result": f"Search results for: {req.text}",
        "instance": instance,
        "summary": f"Mock lookup completed for query (request_id={req.request_id})",
        "results": [
            "Result 1: relevant doc",
            "Result 2: related article",
            "Result 3: reference link",
        ],
    }

    trace = make_trace_entry(
        service="search-service",
        event="handled",
        meta={
            "status": 200,
            "instance": instance,
        },
    )

    return HandleResponse(
        payload=payload,
        trace_append=trace.model_dump(),
    )
