# FLASHCARDS BULLET LIST INSTRUCTIONS

## Architecture & deployment

- Service topology: gateway, AI router, domain backends, trainer, refiner
- Request flow: UI/API -> gateway -> router -> selected backend
- Docker Compose orchestration and service dependencies
- Startup order and health checks across local services
- Optional profiles for train/refine workloads

## Platform & infrastructure

- Local-first architecture with optional cloud integrations
- Container networking, exposed ports, and internal service discovery
- Volume mounts for datasets, artifacts, and runtime state
- Environment-based config generation for reproducible setups
- Static docs site structure and local documentation hosting

## Routing model & intents

- Intent classification domain and service routing behavior
- Class labels/intents drive AI router request dispatch
- Route contracts between classifier output and backend handlers
- Fallback behavior for low-confidence or unavailable routes

## Core services

- Gateway role: single UI/API entrypoint for clients
- AI router role: classify intent and return route plus confidence
- Domain backends: search/image/ops style task handlers
- Trainer role: model training and artifact generation
- Refiner role: dataset relabel/augmentation workflow
- Training API + Redis role: job lifecycle and transient state

## Security

- No secrets committed; use environment variables and local secret handling
- Input validation and bounded payloads at API boundaries
- Service isolation through container network and minimal exposure
- Safe local defaults and explicit production-hardening caveats
- Auditability through request tracing and structured logs

## Development & CI/CD

- Local loop: edit, rebuild, compose up, and verify
- CI flow: lint/test/build for gateway, router, and services
- Profile-gated jobs for optional training/refinement stages
- Artifact/version handling for trained classifier outputs
- Deterministic env generation for local and CI parity

## Scripts & operations

- `scripts/generate_env.py` usage and expected outputs
- Compose lifecycle commands for boot, logs, and teardown
- Optional profile commands for trainer and refiner services
- Health and status checks through service logs and endpoints
- Operational runbooks for repeatable troubleshooting

## Prerequisites & configuration

- Docker/Compose availability for local orchestration
- Python runtime for env generation and utility scripts
- Optional model/runtime dependencies for train/refine paths
- Required env vars versus optional feature flags
- Port and resource expectations for stable local execution

## Compose & portability

- Not required in the local Compose baseline
- If ported to Kubernetes, preserve gateway-router-backend contracts
- Keep training/refinement as optional isolated workloads
- Maintain config parity across local and future K8s manifests

## Troubleshooting & docs

- Troubleshooting by layer: gateway, router, backends, train/refine
- Common failures: route mismatch, low confidence, dependency outage
- Validation points: API responses, trace IDs, logs, health endpoints
- Key docs: architecture, configuration, technical design, runbooks
- Docs index remains the operational source of truth
