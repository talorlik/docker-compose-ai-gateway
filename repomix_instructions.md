# Repomix Instructions for docker-compose-ai-gateway

## Overview

You are an expert AWS DevOps and Platform Architect. This document is a packed
snapshot of my repository "docker-compose-ai-gateway". Use the directory tree at
the top as the system-of-record for how components relate.

## Primary Goal

Build an accurate mental model of the end-to-end deployment and runtime architecture,
focusing on:

- Runtime topology and service boundaries in Docker Compose:
  - gateway, ai_router, search_service, image_service, ops_service, trainer,
    refiner, and training-api responsibilities
  - service-to-service contracts (HTTP endpoints, payload shapes, error behavior)
  - dependency graph and startup/readiness assumptions across services
- Request and data flow through the platform:
  - user/API requests entering via gateway and routing to downstream services
  - training/refine lifecycle: raw data -> augmentation/relabel -> model artifacts
    -> metrics/misclassifications
  - where artifacts and datasets live (`services/trainer/*.csv`, `metrics.json`,
    `model.joblib`) and how they are consumed
- Environment and configuration model:
  - `.env` layering and generation (`scripts/generate_env.py`, `env/.env.dev`)
  - compose variants/profiles (`compose/docker-compose.yaml`,
    `compose/docker-compose.dev.yaml`) and what changes between them
  - per-service config surfaces (`config/PROJECT_CONFIG.yaml`, app-level settings)
- Automation and operational workflows:
  - local scripts (`scripts/demo.sh`, `scripts/promote.sh`, refine scripts, load
    test) and expected execution order
  - test coverage layers (service unit tests, compose tests, integration/e2e) and
    what behavior each protects
- Security and reliability posture:
  - internal-only service exposure vs externally reachable interfaces
  - API boundary controls, input validation, and safe defaults for cross-service
    calls
  - failure handling patterns (timeouts, retries, fallback behavior) and common
    operational gotchas

## Extraction Instructions

1. Start by summarizing the repository's runtime boundaries and startup order
   (which containers/services must be available before others).
2. Enumerate all execution contexts and configuration sources used locally and in
   automation:
   - `.env` files and generated env values
   - Compose files/profiles
   - script-provided environment variables and arguments
3. Trace request flows through the gateway:
   - Web/UI: browser -> gateway static pages -> `/api` proxy routes -> downstream
     services
   - Programmatic/CLI: client -> gateway `/api` -> backend services
   - Include optional branches (search/image/ops/refine/train routes) where present
4. Identify all key data and artifact inputs/outputs between services:
   - training datasets, refined outputs, model artifacts, metrics, and
     misclassification files
   - where each value/file originates, which service writes it, and which service
     consumes it
5. List project invariants and gotchas (for example: stable gateway API route
   prefixes, expected file locations for model/data artifacts, no hidden
   cross-service dependencies outside Compose, and script ordering assumptions).

## Ignore Patterns

- Non-essential markdown boilerplate, badges, and screenshots.
- Generated files, local caches, Terraform .terraform directories, plan/state artifacts,
node_modules, Python venvs.

## Ambiguity Handling

When something is ambiguous, state the assumption explicitly and point to the
exact file/path that would confirm it.
