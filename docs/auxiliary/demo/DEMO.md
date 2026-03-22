# Demo Guide

This guide covers native and containerized Ollama workflows, configuration
management, and the demo scripts for train/relabel/augment/promote.

## Table Of Contents

- [Runtime Modes](#runtime-modes)
- [Native Ollama Setup (macOS)](#native-ollama-setup-macos)
- [Native Ollama Setup (Ubuntu)](#native-ollama-setup-ubuntu)
- [Configuration Reference](#configuration-reference)
- [Running The Demo](#running-the-demo)
- [Demo Prompt Examples](#demo-prompt-examples)
- [Using The Frontend](#using-the-frontend)
- [Troubleshooting](#troubleshooting)
- [See Also](#see-also)

## Runtime Modes

Exactly one Ollama backend mode must be active:

- `OLLAMA_MODE=native`
  - Use host-native Ollama.
  - Containerized Ollama must not run.
- `OLLAMA_MODE=container`
  - Use Compose-managed `ollama` service.
  - Host-native endpoint must not be used by the services.

`scripts/demo.sh` enforces this when
`OLLAMA_BACKEND_ENFORCE_EXCLUSIVE=true`.

## Native Ollama Setup (macOS)

### Prerequisites

- macOS on Apple Silicon (recommended for this project).
- Docker Desktop and Docker Compose.

### Install

1. Install Ollama from [Ollama Download](https://ollama.com/download).
2. Start Ollama once from Applications.
3. Verify:

```bash
ollama --version
ollama list
```

### Pull Model

```bash
ollama pull phi3:mini
```

### Smoke Test

```bash
curl -s http://localhost:11434/api/tags | python3 -m json.tool
```

### Use Native Mode In This Project

Set in `config/PROJECT_CONFIG.yaml` (or `env/.env.<env>`):

- `OLLAMA_MODE=native`
- `OLLAMA_HOST=http://host.docker.internal:11434`
- `OLLAMA_BACKEND_ENFORCE_EXCLUSIVE=true`

Then run:

```bash
CONFIG_ENV=dev ./scripts/demo.sh run
```

## Native Ollama Setup (Ubuntu)

### Prerequisites

- Ubuntu 22.04+.
- Docker and Docker Compose plugin.

### Install

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Start service and enable at boot:

```bash
sudo systemctl enable ollama
sudo systemctl start ollama
```

Verify:

```bash
ollama --version
curl -s http://localhost:11434/api/tags | python3 -m json.tool
```

### Pull Model

```bash
ollama pull phi3:mini
```

### Use Native Mode In This Project

Set:

- `OLLAMA_MODE=native`
- `OLLAMA_HOST=http://host.docker.internal:11434` (Docker Desktop or host bridge)

If your host networking differs, set `OLLAMA_HOST` to the reachable host address.

## Configuration Reference

All values are defined in `config/PROJECT_CONFIG.yaml` and rendered to
`env/.env.<env>` by `scripts/generate_env.py`.

> [!NOTE]
> Use `CONFIG_ENV=dev` (or `prod`) with `scripts/demo.sh` to select env.

| Variable | Default | Meaning |
| --- | --- | --- |
| `OLLAMA_MODE` | `native` | Backend mode (`native` or `container`) |
| `OLLAMA_BACKEND_ENFORCE_EXCLUSIVE` | `true` | Fail if both backends are active |
| `OLLAMA_CONTAINER_SERVICE` | `ollama` | Compose service name for container backend |
| `OLLAMA_HOST` | `http://host.docker.internal:11434` | Active endpoint used by services |
| `OLLAMA_MODEL` | `phi3:mini` | Model tag used by refiner/training-api |
| `OLLAMA_URLS` | one URL | Comma list for pool (single URL recommended) |
| `OLLAMA_TIMEOUT_SECONDS` | `300` | Request timeout to Ollama |
| `OLLAMA_MAX_INFLIGHT_PER_INSTANCE` | `1` | Inflight cap per backend instance |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | Max loaded models for container Ollama |
| `OLLAMA_NUM_PARALLEL` | `1` | Parallel requests per loaded model |
| `OLLAMA_MAX_QUEUE` | `512` | Queue limit before overload |
| `OLLAMA_KEEP_ALIVE` | `30m` | Keep model in memory between requests |
| `OLLAMA_FLASH_ATTENTION` | `0` | Optional memory/throughput experiment |
| `OLLAMA_KV_CACHE_TYPE` | `f16` | KV cache precision (`q8_0`, `q4_0`, etc.) |
| `REFINER_RELABEL_NUM_CTX` | `1024` | Relabel context budget |
| `REFINER_AUGMENT_NUM_CTX` | `768` | Augment context budget |
| `REFINER_RELABEL_NUM_PREDICT` | `120` | Relabel output token cap |
| `REFINER_AUGMENT_NUM_PREDICT` | `180` | Augment output token cap |
| `REFINER_TEMPERATURE` | `0.1` | Generation determinism |
| `REFINER_SEED` | `42` | Reproducibility seed |
| `REFINER_STRUCTURED_OUTPUT_ENABLED` | `true` | Force structured JSON output |
| `REFINER_RELABEL_BATCH_SIZE` | `25` | Relabel batch size |
| `REFINER_RELABEL_MAX_PARALLEL_BATCHES` | `1` | Relabel worker parallelism |
| `REFINER_AUGMENT_N_PER_LABEL` | `3` | Aug examples per selected label |
| `REFINER_AUGMENT_MAX_PARALLEL_LABELS` | `1` | Augment label parallelism |
| `REFINER_RELABEL_MAX_RETRIES` | `3` | Max retries per relabel batch |
| `REFINER_AUGMENT_MAX_RETRIES` | `3` | Max retries per augment label |
| `REFINER_LIMIT` | `5` | Max misclassified rows for relabel phase |
| `DEMO_START_BACKEND` | `true` | Let `demo.sh` start selected backend |
| `DEMO_RUN_RELABEL` | `true` | Enable relabel phase in `demo.sh refine` |
| `DEMO_RUN_AUGMENT` | `true` | Enable augment phase in `demo.sh refine` |
| `BENCH_PROFILE` | `mac_performance` | Benchmark profile label |
| `BENCH_EXPERIMENT_ID` | `baseline` | Benchmark experiment id |
| `BENCH_METRICS_INTERVAL_SEC` | `5` | Metrics sampling cadence |
| `BENCH_MAX_RETRIES` | `3` | Retry cap during benchmark runs |

### Cross References

- Configuration architecture:
  [CONFIGURATION.md](../architecture/CONFIGURATION.md)
- Refiner flow:
  [REFINER_FLOW.md](../refiner/REFINER_FLOW.md)
- Performance plan:
  [PERFORMANCE_IMPROVEMENTS.md](../planning/PERFORMANCE_IMPROVEMENTS.md)

## Running The Demo

### Build

```bash
./scripts/demo.sh build
```

### Start Stack

```bash
./scripts/demo.sh run
```

### Start With Dev Overlay

```bash
./scripts/demo.sh run --dev
```

### Train

```bash
./scripts/demo.sh train
```

### Relabel Only

```bash
./scripts/demo.sh relabel --limit 5
```

### Augment Only

```bash
./scripts/demo.sh augment --run-id <run-id-from-relabel>
```

### Full Split Refine (Relabel + Augment)

```bash
./scripts/demo.sh refine --limit 5
```

### Promote

```bash
./scripts/demo.sh promote
```

### Stop / Restart / Delete / Reset

```bash
./scripts/demo.sh stop
./scripts/demo.sh restart
./scripts/demo.sh restart --dev
./scripts/demo.sh delete
./scripts/demo.sh reset
```

- `stop` - stop the stack (containers remain).
- `restart` - stop + start. Accepts the same flags as `run`
  (`--dev`, `--scale N`).
- `delete` - remove containers, networks, and volumes.
- `reset` - stop + delete + start (full teardown and rebuild).
  Accepts the same flags as `run`.

## Demo Prompt Examples

Paste these `text` values into the Query tab to demo routing across labels.

### search

1. Compare nginx ingress vs traefik
2. How does kubernetes scheduling work
3. Best practices for docker multi-stage builds
4. Terraform vs pulumi comparison
5. Search for microservice patterns for observability
6. What is an SLO and how do you measure it
7. How to troubleshoot a 502 Bad Gateway in nginx
8. Latest guidance on docker compose profiles
9. Explain k8s liveness vs readiness probes
10. Find resources for learning vector databases

### image

1. Generate a logo for a coffee roaster, minimalist style
2. Create an illustration of a cat wearing a space helmet
3. Detect objects in this image and return labels
4. Turn this photo into a watercolor painting
5. Generate a realistic product mockup of a smartwatch on a dark background
6. Create an icon set for a mobile app: settings, search, notifications
7. Generate a poster design for "Summer Sale" with bold typography
8. Analyze this screenshot and describe what UI elements are present
9. Create a simple illustration diagram of a home network
10. Generate a thumbnail image for a YouTube video about kubernetes

### ops

1. Kubectl get pods in namespace default
2. Restart the deployment `my-service`
3. Pod stuck in CrashLoopBackOff debug steps
4. Check service health for gateway and ai-router
5. Docker compose logs for `search_service` with tail 200
6. Terraform plan looks risky, how do I review safely
7. Rate limit requests on nginx ingress
8. How to resize an EBS volume and extend the filesystem
9. Fix permissions for a mounted volume in docker compose
10. Troubleshoot why a container cannot reach host.docker.internal

### unknown

1. Help
2. Hi
3. Do something
4. Analyze
5. I need assistance
6. Something is broken
7. It depends
8. Explain that
9. Test request
10. Can you do the thing again

## Using The Frontend

The gateway UI is available at <http://localhost:8000>.

- **Query** tab routes requests.
- **Train** tab triggers training and displays metrics.
- **Refine** tab runs relabel and augment phases and allows promotion.

Train/Refine tabs require `training-api` in the running stack.

## Troubleshooting

### Both Native And Container Backends Running

Set `OLLAMA_BACKEND_ENFORCE_EXCLUSIVE=true` and run with `demo.sh`.
The script will fail fast or stop conflicting backend processes.

### Native Ollama Unreachable

- Verify local service:
  `curl -s http://localhost:11434/api/tags`
- Verify project endpoint:
  `echo $OLLAMA_HOST`

### Container Ollama Unreachable

- Confirm mode:
  `OLLAMA_MODE=container`
- Confirm host:
  `OLLAMA_HOST=http://ollama:11434`
- Check service:
  `docker compose -f compose/docker-compose.yaml --profile refine-container ps`

### Missing Model

Pull the selected model in active backend:

```bash
ollama pull phi3:mini
```

### Performance Regressions

- Check `OLLAMA_NUM_PARALLEL`, `OLLAMA_NUM_CTX`, and `OLLAMA_NUM_PREDICT`.
- Reduce relabel/augment parallelism first.
- Re-run the benchmark protocol in
  [PERFORMANCE_IMPROVEMENTS.md](../planning/PERFORMANCE_IMPROVEMENTS.md).

## See Also

- [PERFORMANCE_IMPROVEMENTS.md](../planning/PERFORMANCE_IMPROVEMENTS.md)
- [CONFIGURATION.md](../architecture/CONFIGURATION.md)
- [REFINER_FLOW.md](../refiner/REFINER_FLOW.md)
- [TRAIN_AND_REFINE_GUI_PAGES_TECH.md](../architecture/TRAIN_AND_REFINE_GUI_PAGES_TECH.md)
