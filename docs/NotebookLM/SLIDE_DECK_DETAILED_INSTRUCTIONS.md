# Slide Deck Instructions (Detailed)

Generate a **15-20 slide technical reference deck** for **Docker Compose AI
Gateway**. Self-contained for stakeholders reading without a presenter.

## Objective

Lead with the **product purpose**: a local AI gateway that routes requests to
specialized services through intent classification. Then cover architecture,
routing flow, train/refine pipelines, state handling, observability, and
operations. Ground all content in this project's Markdown docs.

## Visual Theme

**"Knowledge-Cloud Industrial."** Neon blue/cyan service icons; translucent
mesh/routing visuals; glowing observability and security motifs; dark slate
backgrounds with subtle data-flow accents.

## Per-Slide Structure

1. **Clear title** (one line).
2. **3-5 technical bullets** (high information density).
3. **One key insight** sentence ("so what" for this slide).

## Mandatory Categories (All Seven)

### 1. Local Service Deployment Model

- **Compose-first topology**: gateway, AI router, domain backends, trainer,
  refiner, Redis, and training API.
- **Runtime model**: local containers, shared networks, explicit dependencies,
  optional profile-driven services.
- **Lifecycle**: generate env, build/start stack, run optional train/refine,
  and teardown cleanly.

### 2. Request Routing and Gateway Contract

- **Entrypoint**: gateway serves UI and API edge.
- **Routing**: AI router returns route + confidence from intent classification.
- **Dispatch**: gateway forwards to backend services based on route policy.
- **Insight:** consistent contracts keep UX stable even when model behavior
  shifts.

### 3. Core Services and Responsibilities

- **Gateway**: request orchestration and response normalization.
- **AI Router**: intent inference and confidence scoring.
- **Backends**: domain-specific handlers (search/image/ops style).
- **Training API + Redis**: job lifecycle, progress tracking, transient state.
- **Insight:** clear boundaries reduce coupling and simplify debugging.

### 4. Train and Refine Workflows

- **Trainer**: optional model training and artifact output.
- **Refiner**: optional relabel/augmentation workflow to improve data quality.
- **Profiles**: train/refine paths are enabled only when needed.
- **Insight:** iterative refinement improves routing quality without changing
  client contracts.

### 5. State, Configuration, and Environment

- **Configuration**: generated env files define reproducible runtime inputs.
- **State placement**: artifacts/datasets on volumes; transient job state in
  Redis where applicable.
- **Operational consistency**: same env patterns for local and CI usage.
- **Insight:** explicit config/state boundaries improve repeatability.

### 6. Security and Observability

- **Security posture**: no committed secrets; bounded inputs at API boundaries.
- **Network hygiene**: service exposure limited to required ports.
- **Observability**: request tracing and structured logs across services.
- **Insight:** traceability is the fastest path to root cause in multi-service
  flows.

### 7. Operations, Troubleshooting, and Documentation

- **Ops flow**: start, verify health, inspect logs, isolate failing service.
- **Troubleshooting**: route mismatch, confidence issues, dependency failures,
  stale artifacts.
- **Documentation map**: architecture, configuration, technical, demo, and
  runbooks in docs.
- **Insight:** docs-first operations make local environments predictable.

## Data Grounding

**All specs must match this project's docs:** `README.md`, `docs/index.html`,
`docs/auxiliary/architecture/`, `docs/auxiliary/planning/`,
`docs/auxiliary/refiner/`, `docs/auxiliary/troubleshooting/`, and related
project documentation.

Do not add or contradict details about gateway routing, service roles,
train/refine behavior, Redis/training API responsibilities, or operational
procedures from those files.
