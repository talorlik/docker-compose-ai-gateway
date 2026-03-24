# Slide Deck Instructions (Presenter Deck)

Generate a **10-slide minimalist presenter deck** for a **15-minute technical
deep-dive** on **Docker Compose AI Gateway**. All content must be grounded in
this project's Markdown documentation.

## Objective

Walk the audience from problem and solution through local service topology,
request routing, train/refine workflows, configuration/state handling, and
operations. Emphasize **why** decisions were made, not just what was built.

## Visual Theme

**Futuristic Minimalist:** Black/dark slate backgrounds; neon blue/cyan or
gold accents. Abstract visuals (service graph, classifier paths, state flow).
Minimal text per slide; visuals support the speaker.

## Per-Slide Requirements

1. **Visual Focus** - One core diagram or concept.
2. **Minimalist Text** - At least 5 short bullets (scannable).
3. **Speaker Script** - 2-3 sentences the presenter can say aloud.

## Mandatory Categories (~10 Slides)

**1. Problem and Solution** - Need: local, self-hosted AI routing with clear
service boundaries and reproducible operations. Solution: gateway \+ AI router
\+ domain backends with optional trainer/refiner workflows. *Why* a local
microservice stack enables fast iteration and controlled testing.

**2. Golden Path Deployment** - Order: generate env, start compose stack,
verify health, optionally run train/refine, then teardown. Services run as
standalone containers with shared network contracts. *Why* this path keeps
setup deterministic and easy to repeat.

**3. Gateway and Router Flow** - Gateway is UI/API entrypoint; AI router
classifies intent and returns route + confidence; gateway dispatches to the
selected backend. *Why* one orchestration point simplifies clients and
observability.

**4. Service Responsibilities** - Gateway orchestration, router inference,
backend domain handling, training API coordination, Redis transient state,
trainer artifact creation, refiner data improvement. *Why* strict boundaries
reduce coupling and regression risk.

**5. Train/Refine Lifecycle** - Optional profile-based workflows for model
training and data refinement; artifacts feed routing quality improvements.
*Why* iterative quality gains without changing client-facing contracts.

**6. Configuration and State** - Environment generation drives reproducible
inputs; volumes hold artifacts/datasets; transient runtime state is isolated.
*Why* explicit config/state ownership improves reliability.

**7. Security Posture** - No committed secrets; constrained exposure; input
validation; local-safe defaults. *Why* security controls should exist even in
local-first systems.

**8. Observability and Debugging** - Request tracing, structured logs, health
checks, and service-level diagnostics. *Why* traceability shortens incident
resolution in distributed flows.

**9. Documentation-Driven Operations** - Use architecture/config/technical and
troubleshooting docs as source of truth. *Why* docs-first workflows make
handoffs and onboarding faster.

**10. Conclusion - End-State and Ops** - End-state: stable local AI gateway
stack with routable services, optional model lifecycle workflows, and clear
runbooks. *Why* this is a practical foundation for future scaling.

## Narrative Focus (Why)

- **Gateway + router split:** Separation of orchestration and inference logic.
- **Compose-first deployment:** Fast local iteration with deterministic startup.
- **Optional train/refine profiles:** Improve model quality without always-on
  overhead.
- **Redis/training API pairing:** Transient state and job control are isolated.
- **Docs-centric operations:** Reliable execution and troubleshooting.

## Data Grounding

**All content must come from this project's docs.** Source of truth includes
`README.md`, `docs/index.html`, `docs/auxiliary/architecture/`,
`docs/auxiliary/planning/`, `docs/auxiliary/refiner/`, and
`docs/auxiliary/troubleshooting/`.

Do not add or contradict details from these documents.

**Important:** Base the entire deck on this documentation. Slide count,
categories, and narrative must align with the Docker Compose AI Gateway
architecture, train/refine workflows, and operational procedures.
