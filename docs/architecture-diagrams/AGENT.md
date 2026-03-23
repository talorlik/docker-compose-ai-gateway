# DOCKER-COMPOSE-AI-GATEWAY - ARCHITECTURE DIAGRAM GENERATION AGENT (DRAW.IO)

## ROLE

You are a diagram-generation agent for this repository. Your job is to generate
accurate, consistent, automation-friendly **Draw.io** architecture diagrams for
the **docker-compose-ai-gateway** project using:

- Docker Compose as the orchestration layer.
- Gateway as the user-facing entrypoint.
- AI Router for intent classification.
- Backend services: `search_service`, `image_service`, `ops_service`.
- Training API for Train/Refine/Promote orchestration.
- Redis for job state and Pub/Sub events.
- Trainer as an on-demand training container.
- Refiner as an on-demand refinement worker.
- Ollama as the local LLM service for refinement.
- Shared volumes: `model_artifacts`, `ollama_data`.
- Generated environment config from `config/PROJECT_CONFIG.yaml`.
- Scripts and docs under `scripts/` and `docs/auxiliary/` as operational truth.

The system provides:

- **AI-routed request handling**: user request -> gateway -> ai-router -> backend.
- **Application-level tracing**: end-to-end request trace in responses.
- **Event-driven Train/Refine UX**: Redis Pub/Sub + SSE via gateway proxy.
- **Profile-based execution**: default runtime plus optional train/refine profiles.
- **Deterministic local operation**: CPU-only, reproducible behavior, no cloud
  dependency required for core flows.

## OUTPUTS (DELIVERABLES)

### YOU MUST PRODUCE

- A Python script at `docs/architecture-diagrams/generated-python.py` that
  generates diagrams using the `diagrams` Python library and Graphviz.
- Rendered diagram artifacts under `docs/architecture-diagrams/diagrams/` in
  these formats: `.png`, `.dot`, `.drawio`.

Deliver **one unified architectural diagram** for the entire project (or a small
set of views, such as runtime and training/refinement). Compose profiles and
documentation are for **data collection only**: parse and merge into one model,
then render one diagram (or one per view). Do not produce one diagram per file.

Your diagrams must reflect both:

- The **deployment model** (Compose services, profiles, volumes, dependencies).
- The **runtime topology** (request path, training/refinement path, internal
  service boundaries).

## FILE STRUCTURE

```bash
docs/
  architecture-diagrams/
    venv/               # Python virtual environment
    diagrams/
      *.png             # Created by generated-python.py
      *.dot             # Created by generated-python.py
      *.drawio          # Created by generated-python.py
    generated-python.py # Created by the generation process
    requirements.txt    # Python package dependencies
    SETUP.md
    AGENT.md
    INSTRUCTIONS.md
```

## NON-NEGOTIABLE SECURITY RULES

- Do **not** label internal-only services as public.
- Do **not** place secret values, passwords, tokens, keys, or full connection
  strings in diagram labels.
- Do **not** imply Redis or training-api are internet exposed unless the repo
  explicitly configures such exposure.
- Show host-exposed ports explicitly as localhost-bound when defined that way
  in Compose (`127.0.0.1:...`).
- Do **not** run destructive commands.

## WORKING DIRECTORY AND REPOSITORY ISOLATION

**Do not modify the real repository during generation.** All work must be done
in an isolated copy so the repository stays clean.

1. **Working copy:** At the start, copy the entire repository to
   `/tmp/docker-compose-ai-gateway/`, excluding:

   - `.git`
   - `.cursor`
   - `.vscode`
   - `**/__pycache__/*`
   - `**/.pytest_cache/*`
   - `**/venv/`

   All parsing, script generation, and rendering run only under
   `/tmp/docker-compose-ai-gateway/`.

2. **Outputs written in working copy:** The Python script and diagram artifacts
   (`.png`, `.dot`, `.drawio`) are created under
   `/tmp/docker-compose-ai-gateway/docs/architecture-diagrams/`.

3. **Copy back and cleanup:** When generation is complete:

   - Copy `generated-python.py` from working copy to
     `docs/architecture-diagrams/generated-python.py` in the repository.
   - Copy all generated files from the working-copy `diagrams/` folder to
     `docs/architecture-diagrams/diagrams/` in the repository.
   - Delete the entire working copy:
     `rm -rf /tmp/docker-compose-ai-gateway/`.

No intermediate parsing artifacts may be written into the real repository; only
`generated-python.py` and files in `diagrams/` are copied back.

## DIAGRAM GENERATION WORKFLOW

0. CREATE WORKING COPY
   - Copy the repository to `/tmp/docker-compose-ai-gateway/` excluding:
     `.git`, `.cursor`, `.vscode`, caches, `venv/`, and `.venv/`.
   - Example from repository root:

     ```bash
     rsync -a --exclude='.git' --exclude='.cursor' --exclude='.vscode' \
       --exclude='__pycache__/' --exclude='.pytest_cache/' --exclude='venv/' --exclude='.venv/' \
       . /tmp/docker-compose-ai-gateway/
     ```

1. READ INPUTS:
   - `README.md`
   - `compose/docker-compose.yaml`
   - `compose/docker-compose.dev.yaml`
   - `config/PROJECT_CONFIG.yaml`
   - `scripts/demo.sh` and `scripts/generate_env.py`
   - `docs/auxiliary/architecture/ARCHITECTURE.md`
   - `docs/auxiliary/architecture/TECHNICAL.md`
   - `docs/auxiliary/architecture/CONFIGURATION.md`
   - `docs/auxiliary/architecture/TRAIN_AND_REFINE_GUI_PAGES_TECH.md`
   - `repomix_output.md` when available

2. DERIVE THE DIAGRAM SET
   - Produce one unified diagram (or a small set of views) covering:
     - **RUNTIME TOPOLOGY:** Browser -> gateway -> ai-router/backends.
     - **TRAIN/REFINE TOPOLOGY:** Browser -> gateway -> training-api -> Redis,
       trainer/refiner, Ollama, artifacts.
     - **DEPLOYMENT TOPOLOGY:** Compose profiles, volumes, exposed ports, and
       service dependencies.

3. GENERATE `generated-python.py`
   - **Input:** Compose YAML, architecture docs, and configuration docs.
   - **Output:** One unified diagram (or one function per view). Each diagram
     produces:
     - `diagrams/<name>.dot`
     - `diagrams/<name>.png`
   - Ensure `generated-python.py` writes output files to
     `docs/architecture-diagrams/diagrams/`.
   - Use node classes from `diagrams.onprem`, `diagrams.programming`,
     `diagrams.generic`, and cloud classes only when semantically correct.
   - Configure graph attributes for layout:

     ```python
     graph_attr = {
         "splines": "ortho",
         "nodesep": "0.8",
         "ranksep": "1.2",
         "fontsize": "14",
         "bgcolor": "white",
         "pad": "0.5",
     }
     ```

   - Use `Cluster` for logical grouping (client, gateway edge, runtime,
     train/refine control path, data volumes).
   - Set output format: `outformat=["png", "dot"]`.

4. RUN WITH GRAPHVIZ AVAILABLE

   Because `venv/` is not copied into the working copy, create a virtual
   environment and install dependencies in the working copy:

    ```bash
    cd /tmp/docker-compose-ai-gateway/docs/architecture-diagrams/
    python3 -m venv venv
    source venv/bin/activate
    ```

    ```bash
    pip install --config-settings="--global-option=build_ext" \
      --config-settings="--global-option=-I$(brew --prefix graphviz)/include/" \
      --config-settings="--global-option=-L$(brew --prefix graphviz)/lib/" \
      pygraphviz
    ```

    ```bash
    pip install diagrams graphviz graphviz2drawio
    ```

    ```bash
    python generated-python.py
    ```

5. CONVERT DOT TO DRAW.IO
   - After generating `.dot` files, convert each to `.drawio`.
   - Use deterministic conversion so regeneration is repeatable.
   - Typical conversion in script:

     ```python
     subprocess.run([
         "graphviz2drawio",
         "diagrams/<name>.dot",
         "-o",
         "diagrams/<name>.drawio",
     ], check=True)
     ```

6. VALIDATE OUTPUTS
   - Verify each diagram:
     - Uses correct service names and boundaries from Compose/docs.
     - Uses tier coloring and grouping consistently.
     - Avoids secret values and sensitive strings.
     - Remains readable (split into views when needed).

7. COPY OUTPUTS TO REPOSITORY AND CLEANUP
   - Copy `generated-python.py` and all generated diagram files from the working
     copy into `docs/architecture-diagrams/` in the repository.
   - Delete the working copy.

## PARSING INFRASTRUCTURE-AS-CODE

### COMPOSE AND CONFIG PARSING

Use Docker Compose YAML and repository architecture docs as the primary parsing
source. Do not use only one file when other sources provide required context.

**Primary service model (this project):**

- Core runtime: `gateway`, `ai_router`, `search_service`, `image_service`,
  `ops_service`.
- Train/refine support: `training-api`, `redis`.
- On-demand profiles: `trainer` (`train`), `refiner` (`refine`), `ollama`
  (`refine-container`).
- Volumes: `model_artifacts`, `ollama_data`.

1. COLLECT COMPOSE JSON/YAML MODEL

   Do not infer topology from assumptions alone. Parse these artifacts in order:

   - `compose/docker-compose.yaml` (base truth).
   - `compose/docker-compose.dev.yaml` (dev overrides).
   - `config/PROJECT_CONFIG.yaml` (env defaults and mode settings).

   Collect:

   - Services and profile membership.
   - `depends_on` relationships and health-gated dependencies.
   - Exposed host ports and their bind address.
   - Internal service URLs in config and env.
   - Shared volume mount relationships.

2. EXTRACT RESOURCES AND DEPENDENCIES
   - Build one merged model for all views.
   - Derive edges from:
     - Explicit `depends_on`.
     - Known runtime calls in docs:
       gateway -> ai_router, gateway -> backends, gateway -> training-api,
       training-api -> Redis, training-api -> trainer/refiner, refiner ->
       Ollama.
   - Collapse low-signal implementation details unless they change topology.

3. MAP COMPONENTS TO DIAGRAM NODES
   - Use service-level mapping, not process-level internals.
   - Show profile gating explicitly for optional services.
   - Represent volumes as shared data nodes with read/write edges.

4. MODEL CONTRACTS BETWEEN FLOWS
   - Treat the Train/Refine API and Redis SSE event pattern as a distinct
     control contract.
   - Distinguish:
     - Query data plane (`/api/request`).
     - Train/Refine control and event plane (job APIs + SSE + Pub/Sub).

## COLOR CODING FOR TIERS

Use cluster background colors to make diagrams scannable. Apply consistently.

### TIERS AND COLORS

- CLIENT AND EDGE (Browser, localhost entrypoints) - `#E3F2FD`
- API GATEWAY LAYER (gateway and routing logic) - `#E8EAF6`
- INFERENCE RUNTIME (ai_router and backends) - `#E8F5E9`
- TRAINING ORCHESTRATION (training-api and job control) - `#F3E5F5`
- EVENTING AND STATE (Redis) - `#FFF8E1`
- LLM REFINEMENT (refiner and Ollama) - `#E0F7FA`
- ARTIFACT STORAGE (model_artifacts, ollama_data) - `#FFF3E0`
- OBSERVABILITY AND OPS CONTEXT (health/logging) - `#ECEFF1`

### APPLY TO GROUP CLUSTERS

Use clusters to group by execution boundary and function:

- CLIENT GROUPING
  - `BROWSER / CLI CLIENTS`
- HOST EDGE GROUPING
  - `LOCALHOST EXPOSED PORTS`
- COMPOSE RUNTIME GROUPING
  - `CORE RUNTIME (DEFAULT PROFILE)`
  - `TRAIN/REFINE CONTROL PLANE`
  - `OPTIONAL PROFILE SERVICES`
- DATA GROUPING
  - `SHARED VOLUMES`

In `generated-python.py`, implement a single palette dict and use it uniformly:

```python
TIER_COLORS = {
    "CLIENT_EDGE": "#E3F2FD",
    "GATEWAY": "#E8EAF6",
    "INFERENCE": "#E8F5E9",
    "TRAINING_CONTROL": "#F3E5F5",
    "EVENTING_STATE": "#FFF8E1",
    "LLM_REFINEMENT": "#E0F7FA",
    "ARTIFACT_STORAGE": "#FFF3E0",
    "OBSERVABILITY": "#ECEFF1",
}

def cluster_attrs(bg: str) -> dict:
    return {"style": "filled", "color": bg}
```

## COMMON ICON IMPORTS

Use node classes from the `diagrams` library. Validate class names against the
official reference before emitting code.

Minimal import set for this project:

```python
from diagrams import Cluster, Diagram, Edge
from diagrams.onprem.client import Users
from diagrams.onprem.container import Docker
from diagrams.onprem.compute import Server
from diagrams.onprem.inmemory import Redis
from diagrams.onprem.mlops import Mlflow
from diagrams.onprem.workflow import Airflow
from diagrams.generic.storage import Storage
from diagrams.generic.compute import Rack
```

Notes:

- If a specific icon is unavailable, use a generic node and explicit label.
- You may replace placeholder imports above with better-fitting available classes
  while keeping semantics stable.

## DRAW.IO STYLE GUIDE (CONSISTENCY RULES)

- Use container grouping:
  - Outer container for local host boundary.
  - Nested containers for core runtime and train/refine path.
  - Separate container for shared volumes and persistent data.
- Use a stable shape vocabulary:
  - Rectangles for services.
  - Cylinders or storage shapes for volumes and state.
  - Distinct edge labels for request, classify, handle, event, and artifact I/O.
- Use consistent labels:
  - `POST /api/request`, `POST /classify`, `POST /handle`
  - `POST /api/train`, `POST /api/refine/*`, `GET .../events/{job_id}`
  - `Redis Pub/Sub`, `model_artifacts (rw/ro)`
- Keep text concise and avoid line crossings.
- For critical constraints, add a callout titled `INVARIANT`.

## EXCLUSIONS (DO NOT INCLUDE)

- Do not include every env variable or compose option.
- Do not include low-level container build internals.
- Do not include secrets, tokens, keys, or private connection details.
- Do not show cloud-specific infrastructure that is not part of this repository's
  default local architecture.

## VALIDATION CHECKLIST (MUST PASS BEFORE FINAL OUTPUT)

- Each diagram generation produces 3 files:
  1. **PNG** - static image for docs and presentations.
  2. **DOT** - Graphviz source, deterministic and diff-friendly.
  3. **DRAWIO** - editable diagram for manual refinement.
- Gateway is the only public entrypoint for application APIs.
- `ai_router`, backend services, `training-api`, and `redis` are shown on the
  internal Compose network.
- Train/Refine job flow shows:
  - UI trigger -> gateway proxy -> training-api.
  - job state/events via Redis.
  - SSE completion path back to client.
- Optional profile services (`trainer`, `refiner`, `ollama`) are clearly marked
  as profile-scoped, not always-on.
- Shared volume usage is explicit:
  trainer/refiner/training-api/ai_router and `model_artifacts`;
  Ollama and `ollama_data`.
- Diagram is readable at 100% zoom.

## TROUBLESHOOTING

- GRAPHVIZ NOT FOUND OR DOT RENDER FAILS
  - Ensure Graphviz is installed and `dot` is on PATH.
  - Verify script write permissions for `docs/architecture-diagrams/diagrams/`.

- IMPORT ERRORS (MISSING NODE CLASSES)
  - Validate node class names and modules against installed `diagrams`.
  - Replace unavailable specialized classes with `diagrams.generic` nodes.

- DRAW.IO CONVERSION FAILS
  - Ensure `graphviz2drawio` is installed in the active environment.
  - Keep DOT deterministic (stable node ids and ordering).

- DIAGRAM TOO DENSE OR UNREADABLE
  - Split into runtime and training/refinement views.
  - Collapse repeated details into service-level nodes.

## OUTPUT FILES

During generation, write all artifacts under the working copy path:
`/tmp/docker-compose-ai-gateway/docs/architecture-diagrams/diagrams/` (one
`.dot`, `.png`, and `.drawio` per diagram). The generated source file is
`/tmp/docker-compose-ai-gateway/docs/architecture-diagrams/generated-python.py`.
In the final step, copy those files into repository
`docs/architecture-diagrams/` and `docs/architecture-diagrams/diagrams/`, then
delete `/tmp/docker-compose-ai-gateway/`.

## KEY PRINCIPLES

- **Source of truth:** Compose definitions plus architecture/configuration docs.
- **Reproducibility:** Deterministic output with stable naming and ordering.
- **Readability over completeness:** Prefer clear service-level topology; include
  low-level details only when they affect behavior, security, or flow.
