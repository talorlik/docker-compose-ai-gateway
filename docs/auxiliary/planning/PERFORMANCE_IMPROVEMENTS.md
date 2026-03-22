# PERFORMANCE IMPROVEMENTS

Consolidated plan for improving refinement performance (relabeling and
augmentation) on Apple Silicon while keeping the project portable.

## Goals

- Improve relabeling and augmentation throughput on MacBook Air M2 (24 GB).
- Keep one source of truth for tuning and rollout decisions.
- Support both native and containerized Ollama, with strict mutual exclusion.
- Make all performance levers configurable.

## Current Context And Constraints

- Hardware: MacBook Air M2, 24 GB unified memory.
- Pipeline: training -> relabel -> augmentation -> candidate metrics -> promote.
- Existing architecture: Redis + event-driven `training-api` workers.
- Main risk: memory pressure from model loading, context size, and parallelism.

## Consolidated Findings

### Key Bottlenecks

- Memory churn is often a bigger bottleneck than raw model size.
- Throughput drops when multiple model instances compete in unified memory.
- Larger context and output budgets increase latency and memory cost.
- Free-form generation increases retry and parsing overhead.

### What Helps Most

- Keep one active Ollama backend for the run (native or container).
- Keep concurrency low and queue depth controlled.
- Use tight token budgets (`num_ctx`, `num_predict`) per phase.
- Use deterministic, structured JSON outputs to cut retries.
- Keep hot model(s) warm only where needed.

## Priority Actions

### Now (Highest ROI)

1. Enforce backend mode exclusivity (`native` or `container`, never both).
2. Cap concurrency and loaded-model pressure.
3. Lower context and output limits per phase.
4. Enforce structured outputs with schema and low temperature.
5. Track accepted rows per minute, not requests per second.

### Next

1. Use phase-specific model configurations.
2. Split easy generation from expensive validation.
3. Batch semantically similar items by label family.

### Later

1. Benchmark Flash Attention (`OLLAMA_FLASH_ATTENTION=1`).
2. Benchmark K/V cache quantization (`OLLAMA_KV_CACHE_TYPE=q8_0`).
3. Add adaptive escalation to a larger model only for hard cases.

## Recommended Baseline Profiles

### `mac_performance` (Default For Local Mac Development)

- `OLLAMA_MODE=native`
- `OLLAMA_BACKEND_ENFORCE_EXCLUSIVE=true`
- `OLLAMA_HOST=http://host.docker.internal:11434`
- `OLLAMA_MAX_LOADED_MODELS=1`
- `OLLAMA_NUM_PARALLEL=1`
- `OLLAMA_MAX_QUEUE=512`
- `OLLAMA_KEEP_ALIVE=30m`
- `REFINER_RELABEL_MAX_PARALLEL_BATCHES=1`
- `REFINER_AUGMENT_MAX_PARALLEL_LABELS=1`
- `REFINER_RELABEL_NUM_CTX=1024`
- `REFINER_AUGMENT_NUM_CTX=768`
- `REFINER_RELABEL_NUM_PREDICT=120`
- `REFINER_AUGMENT_NUM_PREDICT=180`
- `REFINER_TEMPERATURE=0.1`
- `REFINER_SEED=42`
- `REFINER_STRUCTURED_OUTPUT_ENABLED=true`

### `portable_default` (Shared Compose-Centric Setup)

- `OLLAMA_MODE=container`
- `OLLAMA_BACKEND_ENFORCE_EXCLUSIVE=true`
- `OLLAMA_HOST=http://ollama:11434`
- same tuning values as `mac_performance` unless benchmarked otherwise.

## Runtime Modes And Mutual Exclusion

Exactly one backend mode is active at a time:

- `OLLAMA_MODE=native`
  - use host-native Ollama.
  - containerized Ollama must not run.
- `OLLAMA_MODE=container`
  - use Compose Ollama service.
  - host-native endpoint must not be used by services.

When `OLLAMA_BACKEND_ENFORCE_EXCLUSIVE=true`, startup should fail fast if:

- both backends appear active.
- selected backend is unavailable.
- selected host does not match configured mode expectations.

## Configuration Management Changes

Use `config/PROJECT_CONFIG.yaml` as the source of truth and generate
`env/.env.<env>` from it.

### Backend Mode Controls

- `OLLAMA_MODE` (`native|container`)
- `OLLAMA_HOST`
- `OLLAMA_BACKEND_ENFORCE_EXCLUSIVE` (`true|false`)
- `OLLAMA_CONTAINER_SERVICE` (default `ollama`)

### Ollama Runtime Controls

- `OLLAMA_MODEL`
- `OLLAMA_MAX_LOADED_MODELS`
- `OLLAMA_NUM_PARALLEL`
- `OLLAMA_MAX_QUEUE`
- `OLLAMA_KEEP_ALIVE`
- `OLLAMA_FLASH_ATTENTION`
- `OLLAMA_KV_CACHE_TYPE`
- `OLLAMA_TIMEOUT_SECONDS`

### Refinement Controls

- `REFINER_RELABEL_MAX_PARALLEL_BATCHES`
- `REFINER_AUGMENT_MAX_PARALLEL_LABELS`
- `REFINER_RELABEL_NUM_CTX`
- `REFINER_AUGMENT_NUM_CTX`
- `REFINER_RELABEL_NUM_PREDICT`
- `REFINER_AUGMENT_NUM_PREDICT`
- `REFINER_TEMPERATURE`
- `REFINER_SEED`
- `REFINER_STRUCTURED_OUTPUT_ENABLED`
- `REFINER_RELABEL_BATCH_SIZE`
- `REFINER_RELABEL_MAX_RETRIES`
- `REFINER_AUGMENT_MAX_RETRIES`
- `REFINER_AUGMENT_N_PER_LABEL`
- `REFINER_LIMIT`

### Benchmark Controls

- `BENCH_PROFILE`
- `BENCH_EXPERIMENT_ID`
- `BENCH_METRICS_INTERVAL_SEC`
- `BENCH_MAX_RETRIES`

## Benchmark Protocol

### Baseline

1. Run train -> relabel -> augment with one fixed profile.
2. Record:
   - relabels per minute
   - accepted augmentations per minute
   - seconds per accepted row
   - retry rate
   - parse failure rate

### Change Policy

- Change one variable group at a time.
- Run at least 3 repetitions per candidate config.
- Keep dataset slice and random seed fixed for comparability.

### Acceptance Targets

- +30% to +60% accepted augmentations per minute.
- -40% p95 relabel latency.
- -50% malformed output retries.

## Decision Log Template

Track each applied change in this format:

| Date | Change | Expected Impact | Measured Impact | Keep? |
| --- | --- | --- | --- | --- |
| YYYY-MM-DD | `OLLAMA_NUM_PARALLEL=1` | Reduce memory pressure | +22% accepted rows/min | Yes |

## What Not To Do

- Do not run native and container Ollama at the same time.
- Do not increase parallelism before tuning token budgets.
- Do not keep broad context windows for short classification tasks.
- Do not accept free-form outputs when schema output is available.
- Do not scale infra first when retries and token budgets are the bottleneck.

## References

- [Ollama FAQ](https://docs.ollama.com/faq)
- [Ollama Context Length](https://docs.ollama.com/context-length)
- [Ollama Structured Outputs](https://docs.ollama.com/capabilities/structured-outputs)
- [Ollama Modelfile](https://docs.ollama.com/modelfile)
- [Ollama Docker](https://docs.ollama.com/docker)
