# Acceptance Verification

Verification of acceptance criteria (AC-002 through AC-010) and definition of
done (DoD). Per TASKS.md Batch 8.

## Unknown vs Backend Failure Distinction (AC-010)

Two distinct error responses; trace shape and HTTP status differ.

### Unknown Classification (AI Decision)

- **Cause:** Model returns `unknown`, or confidence below `T_ROUTE`, or margin
  below `T_MARGIN`.
- **Gateway behavior:** Does not proxy to any backend.
- **HTTP status:** 404.
- **Trace shape:** gateway-received, ai-router-classified, gateway-responded.
  No backend hop.
- **Response body:** `request_id`, `route` (unknown), `confidence`, `message`,
  `trace`, `timings_ms`.

### Backend Failure (Infrastructure)

- **Cause:** AI-router classifies to a known route, but the backend is down,
  unreachable, or times out.
- **Gateway behavior:** Attempts proxy, catches error, returns 502.
- **HTTP status:** 502.
- **Trace shape:** gateway-received, ai-router-classified, gateway-responded
  with `meta.status: 502` and `meta.error`. No backend-handled entry (attempt
  failed before response).
- **Response body:** `request_id`, `route` (intended backend), `confidence`,
  `message` (e.g. "Backend image unavailable"), `trace`, `timings_ms`.

### Summary Table

| Scenario | HTTP | Trace backend hop | Cause |
| --- | --- | --- | --- |
| Unknown classification | 404 | None | AI decision |
| Low confidence / low margin | 404 | None | Policy decision |
| Backend unreachable | 502 | None (attempted) | Infrastructure |
| AI router unreachable | 503 | None | Infrastructure |
| Successful route | 200 | Yes | Normal flow |

## Verification Results

### AC-002, AC-003: Browser UI and Test Cases

| Prompt | Expected Route | Verified |
| --- | --- | --- |
| compare nginx ingress vs traefik | search | Yes |
| detect objects in an image and return labels | image | Yes |
| kubectl pods CrashLoopBackOff, debug steps | ops | Yes |
| hello | unknown | Yes |
| tell me a joke | unknown | Yes |

### AC-004: Unknown Trace Shape

For unknown: trace has no backend hop (gateway, ai-router, gateway only);
HTTP 404.

### AC-005: Full JSON Response

curl POST to `/api/request` returns JSON with `request_id`, `route`,
`confidence`, `explanation`, `trace`, `backend_response` (or `message` for
unknown), `timings_ms`.

### AC-006: Log Correlation

All services log `request_id` in JSON format. Filter logs:

```bash
docker compose -f compose/docker-compose.yaml logs -f | grep "request_id.*<uuid>"
```

### AC-007, AC-008: Scaling

`docker compose up -d --scale search_service=3` distributes requests;
trace `instance` field shows which container handled each request.

### AC-009, AC-010: Failure Demo

Stop a backend (e.g. `docker compose stop image_service`), send image prompt;
gateway returns 502 with trace showing classification and backend failure.
Unknown (404) is distinguishable from backend failure (502).

### DoD-001, DoD-006, DoD-007: Final Check

`docker compose up --build` succeeds; multi-stage Dockerfiles, Compose
anchors/profiles, health checks implemented; all services log request_id.
