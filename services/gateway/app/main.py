"""Gateway service - entry point for the AI microservice mesh.

Implements:
- Request ID generation/propagation (TECH-11.1)
- AI router classification call (TECH-10, TECH-14.3)
- Confidence threshold and margin policy (TECH-5, TECH-6)
- Backend proxy (TECH-10.2)
- Trace aggregation and timings (TECH-11.3, TECH-11.4)
- Unknown (404) and backend failure (502) handling (TECH-19)
- Static UI serving at GET / (TECH-14.5, TECH-17)
- Structured logging with request_id (TECH-20)
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

STATIC_DIR = Path(__file__).resolve().parent / "static"

AI_ROUTER_URL = os.getenv("AI_ROUTER_URL", "http://ai_router:8000")
ROUTE_MAP = {
    "search": os.getenv("SEARCH_SERVICE_URL", "http://search_service:8000"),
    "image": os.getenv("IMAGE_SERVICE_URL", "http://image_service:8000"),
    "ops": os.getenv("OPS_SERVICE_URL", "http://ops_service:8000"),
}
T_ROUTE = float(os.getenv("T_ROUTE", "0.55"))
T_MARGIN = float(os.getenv("T_MARGIN", "0.10"))
TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "30"))
TRAINING_API_URL = os.getenv("TRAINING_API_URL", "http://training-api:8000")
PROMOTE_TIMEOUT = float(os.getenv("PROMOTE_TIMEOUT", "300"))
SSE_TIMEOUT = float(os.getenv("SSE_TIMEOUT", "3600"))

_JOB_ID_RE = re.compile(r"^[a-f0-9\-]{36}$")

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

_PROXY_ERRORS = (
    httpx.ConnectError,
    httpx.TimeoutException,
    httpx.HTTPStatusError,
)


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


logger = setup_logging("gateway", os.getenv("LOG_LEVEL", "INFO"))


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


class ApiRequest(BaseModel):
    request_id: Optional[str] = None
    text: str = Field(..., max_length=10000)
    trace: Optional[List[Dict[str, Any]]] = None


class ApiResponse(BaseModel):
    request_id: str
    route: str
    confidence: float
    explanation: str
    trace: List[Dict[str, Any]]
    backend_response: Optional[Dict[str, Any]] = None
    timings_ms: Dict[str, int]


class UnknownResponse(BaseModel):
    request_id: str
    route: str
    confidence: float
    message: str
    trace: List[Dict[str, Any]]
    timings_ms: Dict[str, int]


class RouteInfo(BaseModel):
    label: str
    backend_url: str


class RoutesResponse(BaseModel):
    routes: List[RouteInfo]


def _validate_job_id(job_id: str) -> str:
    """Validate job_id matches UUID format to prevent path traversal."""
    if not _JOB_ID_RE.match(job_id):
        raise ValueError("Invalid job_id format")
    return job_id


async def timed_post(
    client: httpx.AsyncClient,
    url: str,
    json_body: dict,
    headers: dict,
) -> tuple[httpx.Response, int]:
    t0 = time.monotonic()
    resp = await client.post(url, json=json_body, headers=headers)
    elapsed_ms = round((time.monotonic() - t0) * 1000)
    return resp, elapsed_ms


def apply_policy(
    raw_route: str,
    probabilities: Dict[str, float],
) -> tuple[str, Optional[str]]:
    """Apply threshold and margin policy. Returns (effective_route, reason)."""
    if raw_route == "unknown":
        return "unknown", "model_unknown"

    non_unknown = {k: v for k, v in probabilities.items() if k != "unknown"}
    if not non_unknown:
        return "unknown", "no_routes"

    sorted_routes = sorted(non_unknown.items(), key=lambda x: x[1], reverse=True)
    best_route, p_best = sorted_routes[0]
    p_second = sorted_routes[1][1] if len(sorted_routes) > 1 else 0.0

    if p_best < T_ROUTE:
        return "unknown", f"low_confidence ({p_best:.2f} < {T_ROUTE})"
    if (p_best - p_second) < T_MARGIN:
        return "unknown", f"low_margin ({p_best - p_second:.2f} < {T_MARGIN})"

    return best_route, None


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.http = httpx.AsyncClient(
        timeout=httpx.Timeout(TIMEOUT),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )
    application.state.sse_http = httpx.AsyncClient(
        timeout=httpx.Timeout(SSE_TIMEOUT),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
    )
    application.state.promote_http = httpx.AsyncClient(
        timeout=httpx.Timeout(PROMOTE_TIMEOUT),
        limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
    )
    yield
    for attr in ("http", "sse_http", "promote_http"):
        client = getattr(application.state, attr, None)
        if client is not None:
            await client.aclose()


app = FastAPI(title="Gateway", version="0.1.0", lifespan=lifespan)

app.mount(
    "/static",
    StaticFiles(directory=str(STATIC_DIR)),
    name="static",
)


@app.get("/")
async def root():
    """Serve the Query page (FR-058, FR-078)."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/train")
async def train_page():
    """Serve the Train page."""
    return FileResponse(STATIC_DIR / "train.html")


@app.get("/refine")
async def refine_page():
    """Serve the Refine page."""
    return FileResponse(STATIC_DIR / "refine.html")


@app.get("/health")
async def health():
    """Health check for Compose/load balancers (NFR-028)."""
    return {"status": "ok"}


@app.get("/routes", response_model=RoutesResponse)
async def routes():
    """Return available route labels (FR-061)."""
    return RoutesResponse(
        routes=[
            RouteInfo(label=k, backend_url="(internal)") for k in ROUTE_MAP
        ]
    )


def _training_api_proxy_error(err: Exception) -> JSONResponse:
    """Return 503 when training-api is unreachable (Batch 7)."""
    logger.error("Training API proxy error: %s", err)
    return JSONResponse(
        status_code=503,
        content={"detail": "Training API unavailable"},
    )


def _safe_json(resp: httpx.Response) -> Any:
    """Parse JSON from response, returning error dict on failure."""
    try:
        return resp.json()
    except json.JSONDecodeError:
        return {"detail": "Upstream returned non-JSON response", "status": resp.status_code}


async def _proxy_post(path: str) -> JSONResponse:
    """Generic POST proxy to training-api."""
    http = app.state.http
    try:
        r = await http.post(f"{TRAINING_API_URL.rstrip('/')}{path}")
        r.raise_for_status()
        return JSONResponse(status_code=r.status_code, content=_safe_json(r))
    except _PROXY_ERRORS as err:
        return _training_api_proxy_error(err)


async def _proxy_get(path: str) -> JSONResponse:
    """Generic GET proxy to training-api."""
    http = app.state.http
    try:
        r = await http.get(f"{TRAINING_API_URL.rstrip('/')}{path}")
        r.raise_for_status()
        return JSONResponse(status_code=r.status_code, content=_safe_json(r))
    except _PROXY_ERRORS as err:
        return _training_api_proxy_error(err)


async def _stream_training_api_events(url: str) -> AsyncGenerator[bytes, None]:
    """Stream response body from training-api (chunk-by-chunk). Batch 8."""
    try:
        async with app.state.sse_http.stream("GET", url) as upstream:
            async for chunk in upstream.aiter_bytes():
                yield chunk
    except _PROXY_ERRORS as exc:
        logger.error("SSE proxy connection lost: %s", exc)
        yield b"data: {\"status\": \"failed\", \"error\": \"SSE connection lost\"}\n\n"


def _sse_response(job_id: str, events_path: str) -> Union[JSONResponse, StreamingResponse]:
    """Build an SSE StreamingResponse for a validated job_id."""
    try:
        _validate_job_id(job_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid job_id format"})
    url = f"{TRAINING_API_URL.rstrip('/')}{events_path}/{job_id}"
    return StreamingResponse(
        _stream_training_api_events(url),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@app.post("/api/train")
async def proxy_post_train():
    """Proxy POST /train to training-api (Batch 7)."""
    return await _proxy_post("/train")


@app.get("/api/train/status/{job_id}")
async def proxy_get_train_status(job_id: str):
    """Proxy GET /train/status/{job_id} to training-api (Batch 7)."""
    try:
        _validate_job_id(job_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid job_id format"})
    return await _proxy_get(f"/train/status/{job_id}")


@app.get("/api/train/last")
async def proxy_get_train_last():
    """Proxy GET /train/last to training-api (Batch 7)."""
    return await _proxy_get("/train/last")


@app.get("/api/train/events/{job_id}")
async def proxy_get_train_events(job_id: str):
    """Stream GET /train/events/{job_id} from training-api (Batch 8)."""
    return _sse_response(job_id, "/train/events")


@app.post("/api/refine/relabel")
async def proxy_post_refine_relabel():
    """Proxy POST /refine/relabel to training-api."""
    return await _proxy_post("/refine/relabel")


@app.get("/api/refine/relabel/events/{job_id}")
async def proxy_get_refine_relabel_events(job_id: str):
    """Stream GET /refine/relabel/events/{job_id} from training-api."""
    return _sse_response(job_id, "/refine/relabel/events")


@app.get("/api/refine/relabel/last")
async def proxy_get_refine_relabel_last():
    """Proxy GET /refine/relabel/last to training-api."""
    return await _proxy_get("/refine/relabel/last")


@app.post("/api/refine/augment")
async def proxy_post_refine_augment():
    """Proxy POST /refine/augment to training-api."""
    return await _proxy_post("/refine/augment")


@app.get("/api/refine/augment/events/{job_id}")
async def proxy_get_refine_augment_events(job_id: str):
    """Stream GET /refine/augment/events/{job_id} from training-api."""
    return _sse_response(job_id, "/refine/augment/events")


@app.get("/api/refine/augment/last")
async def proxy_get_refine_augment_last():
    """Proxy GET /refine/augment/last to training-api."""
    return await _proxy_get("/refine/augment/last")


@app.post("/api/refine/promote")
async def proxy_post_refine_promote(req: Request):
    """Proxy POST /refine/promote with long timeout (Batch 7)."""
    try:
        body = await req.json()
    except json.JSONDecodeError:
        return JSONResponse(status_code=400, content={"detail": "Invalid JSON body"})
    try:
        r = await app.state.promote_http.post(
            f"{TRAINING_API_URL.rstrip('/')}/refine/promote",
            json=body,
        )
        r.raise_for_status()
        return JSONResponse(status_code=r.status_code, content=_safe_json(r))
    except _PROXY_ERRORS as err:
        return _training_api_proxy_error(err)


@app.post("/api/request")
async def api_request(req: ApiRequest):
    """Main request endpoint - classify, apply policy, proxy to backend."""
    request_id = req.request_id or str(uuid.uuid4())
    trace: List[Dict[str, Any]] = list(req.trace or [])
    t_start = time.monotonic()
    http = app.state.http
    headers = {"X-Request-ID": request_id}

    logger.info(
        "request received",
        extra={"request_id": request_id},
    )
    trace.append(make_trace_entry("gateway", "received").model_dump())

    classify_ms = 0
    proxy_ms = 0

    try:
        classify_body = {"request_id": request_id, "text": req.text}
        classify_resp, classify_ms = await timed_post(
            http, f"{AI_ROUTER_URL}/classify", classify_body, headers
        )
        classify_resp.raise_for_status()
    except _PROXY_ERRORS as exc:
        logger.error("AI router error: %s", exc, extra={"request_id": request_id})
        trace.append(
            make_trace_entry(
                "gateway",
                "responded",
                meta={"status": 503, "error": "AI router unavailable"},
            ).model_dump()
        )
        total_ms = round((time.monotonic() - t_start) * 1000)
        return JSONResponse(
            status_code=503,
            content={
                "request_id": request_id,
                "route": None,
                "message": "Classification service unavailable",
                "trace": trace,
                "timings_ms": {"classify": classify_ms, "proxy": 0, "total": total_ms},
            },
        )

    try:
        cdata = classify_resp.json()
        trace.append(cdata["trace_append"])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.error("Bad classify response: %s", exc, extra={"request_id": request_id})
        total_ms = round((time.monotonic() - t_start) * 1000)
        return JSONResponse(
            status_code=502,
            content={
                "request_id": request_id,
                "route": None,
                "message": "Invalid response from classification service",
                "trace": trace,
                "timings_ms": {"classify": classify_ms, "proxy": 0, "total": total_ms},
            },
        )

    route = cdata["route"]
    confidence = cdata["confidence"]
    logger.info(
        "classify route=%s confidence=%.4f",
        route,
        confidence,
        extra={"request_id": request_id},
    )
    probabilities = cdata.get("probabilities", {})
    explanation = cdata.get("explanation", "")

    effective_route, policy_reason = apply_policy(route, probabilities)

    if effective_route == "unknown":
        trace.append(
            make_trace_entry(
                "gateway",
                "responded",
                meta={"status": 404, "policy": policy_reason},
            ).model_dump()
        )
        total_ms = round((time.monotonic() - t_start) * 1000)
        return JSONResponse(
            status_code=404,
            content=UnknownResponse(
                request_id=request_id,
                route="unknown",
                confidence=confidence,
                message="Unable to determine a suitable backend for this request",
                trace=trace,
                timings_ms={"classify": classify_ms, "proxy": 0, "total": total_ms},
            ).model_dump(),
        )

    backend_url = ROUTE_MAP.get(effective_route)
    if backend_url is None:
        logger.error("No backend for route: %s", effective_route, extra={"request_id": request_id})
        total_ms = round((time.monotonic() - t_start) * 1000)
        return JSONResponse(
            status_code=502,
            content={
                "request_id": request_id,
                "route": effective_route,
                "message": f"No backend configured for route: {effective_route}",
                "trace": trace,
                "timings_ms": {"classify": classify_ms, "proxy": 0, "total": total_ms},
            },
        )

    handle_body = {"request_id": request_id, "text": req.text}

    try:
        handle_resp, proxy_ms = await timed_post(
            http, f"{backend_url}/handle", handle_body, headers
        )
        handle_resp.raise_for_status()
    except _PROXY_ERRORS as err:
        logger.error("Backend %s error: %s", effective_route, err, extra={"request_id": request_id})
        trace.append(
            make_trace_entry(
                "gateway",
                "responded",
                meta={"status": 502, "error": "Backend unavailable"},
            ).model_dump()
        )
        total_ms = round((time.monotonic() - t_start) * 1000)
        return JSONResponse(
            status_code=502,
            content={
                "request_id": request_id,
                "route": effective_route,
                "confidence": confidence,
                "message": f"Backend {effective_route} unavailable",
                "trace": trace,
                "timings_ms": {
                    "classify": classify_ms,
                    "proxy": proxy_ms,
                    "total": total_ms,
                },
            },
        )

    try:
        hdata = handle_resp.json()
        trace.append(hdata["trace_append"])
        backend_response = hdata.get("payload")
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.error("Bad backend response: %s", exc, extra={"request_id": request_id})
        total_ms = round((time.monotonic() - t_start) * 1000)
        return JSONResponse(
            status_code=502,
            content={
                "request_id": request_id,
                "route": effective_route,
                "message": "Invalid response from backend service",
                "trace": trace,
                "timings_ms": {
                    "classify": classify_ms,
                    "proxy": proxy_ms,
                    "total": total_ms,
                },
            },
        )

    trace.append(
        make_trace_entry("gateway", "responded", meta={"status": 200}).model_dump()
    )
    total_ms = round((time.monotonic() - t_start) * 1000)

    return ApiResponse(
        request_id=request_id,
        route=effective_route,
        confidence=confidence,
        explanation=explanation,
        trace=trace,
        backend_response=backend_response,
        timings_ms={"classify": classify_ms, "proxy": proxy_ms, "total": total_ms},
    )
