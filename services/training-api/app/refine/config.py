from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path


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
            relabel_batch_size=_get_int("REFINER_RELABEL_BATCH_SIZE", 10, min_value=1),
            relabel_max_parallel_batches=_get_int(
                "REFINER_RELABEL_MAX_PARALLEL_BATCHES", 4, min_value=1
            ),
            augment_n_per_label=_get_int("REFINER_AUGMENT_N_PER_LABEL", 5, min_value=1),
            augment_max_parallel_labels=_get_int(
                "REFINER_AUGMENT_MAX_PARALLEL_LABELS", 4, min_value=1
            ),
            ollama_urls=urls,
            ollama_model=_get_str("OLLAMA_MODEL", "phi3:mini"),
            ollama_timeout_seconds=_get_int("OLLAMA_TIMEOUT_SECONDS", 300, min_value=1),
            ollama_max_inflight_per_instance=_get_int(
                "OLLAMA_MAX_INFLIGHT_PER_INSTANCE", 2, min_value=1
            ),
            relabel_tasks_stream=_get_str("REFINE_RELABEL_TASKS_STREAM", "refine:relabel:tasks"),
            augment_tasks_stream=_get_str("REFINE_AUGMENT_TASKS_STREAM", "refine:augment:tasks"),
            relabel_consumer_group=_get_str("REFINE_RELABEL_CONSUMER_GROUP", "relabel-workers"),
            augment_consumer_group=_get_str("REFINE_AUGMENT_CONSUMER_GROUP", "augment-workers"),
            events_channel_prefix=_get_str("REFINE_EVENTS_CHANNEL_PREFIX", "refine:events:"),
        )

    def new_run_id(self) -> str:
        return str(uuid.uuid4())

    def run_dir(self, run_id: str) -> Path:
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
