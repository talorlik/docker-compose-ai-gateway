from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

_SAFE_RUN_ID_RE = re.compile(r"^[a-f0-9\-]{36}$")


def _get_int(name: str, default: int, *, min_value: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        value = default
    else:
        try:
            value = int(str(raw).strip())
        except ValueError:
            value = default
    if min_value is not None:
        value = max(min_value, value)
    return value


def _get_float(name: str, default: float, *, min_value: float | None = None) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        value = default
    else:
        try:
            value = float(str(raw).strip())
        except ValueError:
            value = default
    if min_value is not None:
        value = max(min_value, value)
    return value


def _get_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    return default if raw is None or str(raw).strip() == "" else str(raw).strip()


@dataclass(frozen=True)
class RefineConfig:
    # Artifacts are stored in MODEL_ARTIFACTS_PATH (default /model). Runs live
    # in a run-specific subdir to avoid conflicts across parallel workers.
    runs_root: Path

    # Relabel batching and worker concurrency
    relabel_batch_size: int
    relabel_max_parallel_batches: int

    # Augmentation concurrency and desired count per label
    augment_n_per_label: int
    augment_max_parallel_labels: int

    # Ollama pool / routing controls
    ollama_urls: list[str]
    ollama_model: str
    ollama_timeout_seconds: int
    ollama_max_inflight_per_instance: int
    ollama_num_ctx: int
    ollama_num_predict: int
    refiner_temperature: float
    refiner_seed: int
    structured_output_enabled: bool

    # Relabel gating: only apply suggested label changes when the LLM is
    # sufficiently confident that the existing (base/true) label is wrong.
    relabel_min_confidence: float

    # Redis Streams (work queues) and events
    relabel_tasks_stream: str
    augment_tasks_stream: str
    relabel_consumer_group: str
    augment_consumer_group: str
    events_channel_prefix: str

    @staticmethod
    def from_env(model_artifacts_path: str) -> "RefineConfig":
        root = Path(model_artifacts_path) / "refine_runs"

        ollama_urls_raw = _get_str("OLLAMA_URLS", "").strip()
        if ollama_urls_raw:
            urls = [u.strip() for u in ollama_urls_raw.split(",") if u.strip()]
        else:
            # Backwards compatible single instance
            urls = [_get_str("OLLAMA_HOST", "http://ollama:11434")]

        return RefineConfig(
            runs_root=root,
            # Practical default: larger batches reduce prompt overhead.
            relabel_batch_size=_get_int("REFINER_RELABEL_BATCH_SIZE", 25, min_value=1),
            relabel_max_parallel_batches=_get_int(
                "REFINER_RELABEL_MAX_PARALLEL_BATCHES", 4, min_value=1
            ),
            # Practical default: fewer examples per label reduces Ollama time.
            augment_n_per_label=_get_int("REFINER_AUGMENT_N_PER_LABEL", 3, min_value=1),
            augment_max_parallel_labels=_get_int(
                "REFINER_AUGMENT_MAX_PARALLEL_LABELS", 4, min_value=1
            ),
            ollama_urls=urls,
            ollama_model=_get_str("OLLAMA_MODEL", "phi3:mini"),
            ollama_timeout_seconds=_get_int("OLLAMA_TIMEOUT_SECONDS", 300, min_value=1),
            ollama_max_inflight_per_instance=_get_int(
                "OLLAMA_MAX_INFLIGHT_PER_INSTANCE", 2, min_value=1
            ),
            # Limits to control per-request work in Ollama. Keep conservative
            # defaults so the refiner stays responsive on CPU-only machines.
            ollama_num_ctx=_get_int("OLLAMA_NUM_CTX", 2048, min_value=128),
            ollama_num_predict=_get_int("OLLAMA_NUM_PREDICT", 256, min_value=16),
            refiner_temperature=_get_float("REFINER_TEMPERATURE", 0.1, min_value=0.0),
            refiner_seed=_get_int("REFINER_SEED", 42),
            relabel_min_confidence=min(
                1.0,
                max(
                    0.0,
                    _get_float(
                        "REFINER_RELABEL_MIN_CONFIDENCE", 0.85, min_value=0.0
                    ),
                ),
            ),
            structured_output_enabled=_get_str(
                "REFINER_STRUCTURED_OUTPUT_ENABLED", "true"
            ).lower()
            in {"1", "true", "yes", "on"},
            relabel_tasks_stream=_get_str("REFINE_RELABEL_TASKS_STREAM", "refine:relabel:tasks"),
            augment_tasks_stream=_get_str("REFINE_AUGMENT_TASKS_STREAM", "refine:augment:tasks"),
            relabel_consumer_group=_get_str("REFINE_RELABEL_CONSUMER_GROUP", "relabel-workers"),
            augment_consumer_group=_get_str("REFINE_AUGMENT_CONSUMER_GROUP", "augment-workers"),
            events_channel_prefix=_get_str("REFINE_EVENTS_CHANNEL_PREFIX", "refine:events:"),
        )

    def new_run_id(self) -> str:
        return str(uuid.uuid4())

    @staticmethod
    def validate_run_id(run_id: str) -> str:
        """Validate run_id to prevent path traversal."""
        if not _SAFE_RUN_ID_RE.match(run_id):
            raise ValueError(f"Invalid run_id format: {run_id!r}")
        return run_id

    def run_dir(self, run_id: str) -> Path:
        self.validate_run_id(run_id)
        return self.runs_root / run_id

    def events_channel(self, run_id: str) -> str:
        return f"{self.events_channel_prefix}{run_id}"

    def ensure_run_dir(self, run_id: str) -> Path:
        path = self.run_dir(run_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    # Artifact paths (relative to run dir)
    def metrics_before_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "metrics_before.json"

    def relabel_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "relabel"

    def augment_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "augment"

    def relabel_merged_csv(self, run_id: str) -> Path:
        return self.relabel_dir(run_id) / "proposed_relabels.csv"

    def relabel_candidate_csv(self, run_id: str) -> Path:
        return self.relabel_dir(run_id) / "train_relabel_candidate.csv"

    def relabel_candidate_metrics_json(self, run_id: str) -> Path:
        return self.relabel_dir(run_id) / "metrics_relabel_candidate.json"

    def augment_merged_csv(self, run_id: str) -> Path:
        return self.augment_dir(run_id) / "proposed_examples.csv"

    def augment_candidate_csv(self, run_id: str) -> Path:
        return self.augment_dir(run_id) / "train_augment_candidate.csv"

    def augment_candidate_metrics_json(self, run_id: str) -> Path:
        return self.augment_dir(run_id) / "metrics_augment_candidate.json"
