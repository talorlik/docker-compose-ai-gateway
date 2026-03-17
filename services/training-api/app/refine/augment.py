from __future__ import annotations

import csv
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd  # pylint: disable=import-error
import requests  # pylint: disable=import-error

from app.redis_client import (
    publish_event,
    stream_ack,
    stream_add,
    stream_group_create,
    stream_read_group,
)
from app.refine.config import RefineConfig
from app.refine.ollama_pool import OllamaPool, get_ollama_pool
from app.refine.prompts import LABELS, SYSTEM_INSTRUCTIONS, augment_examples
from app.refine.training import train_candidate


MIN_TEXT_LENGTH = 3


@dataclass(frozen=True)
class AugmentTask:
    run_id: str
    label: str
    n: int


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _read_train_csv(promote_target_dir: str) -> pd.DataFrame:
    train_path = os.path.join(promote_target_dir, "train.csv")
    if not os.path.exists(train_path):
        raise FileNotFoundError(f"train.csv not found at {train_path}")
    df = pd.read_csv(train_path)
    if "text" not in df.columns or "label" not in df.columns:
        raise ValueError("train.csv missing required columns: text,label")
    return df


def _read_metrics(artifacts_dir: str) -> dict[str, Any]:
    path = os.path.join(artifacts_dir, "metrics.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _labels_to_augment(metrics: dict[str, Any]) -> list[str]:
    # Keep the baseline behavior: augment any label present in metrics report
    # with low recall (<0.75). If metrics missing, augment all labels.
    report = metrics.get("classification_report", {})
    labels: list[str] = []
    for label in LABELS:
        if label in report and isinstance(report[label], dict):
            recall = report[label].get("recall")
            if recall is not None and float(recall) < 0.75:
                labels.append(label)
    return labels or LABELS


def enqueue_augment_tasks(cfg: RefineConfig, *, run_id: str, labels: list[str]) -> int:
    for label in labels:
        stream_add(
            cfg.augment_tasks_stream,
            {"run_id": run_id, "label": label, "n": cfg.augment_n_per_label},
        )
    return len(labels)


def _label_output_path(cfg: RefineConfig, run_id: str, label: str) -> Path:
    safe = label.replace("/", "_")
    return cfg.augment_dir(run_id) / "labels" / f"proposed_examples.label_{safe}.csv"


def _parse_json_array(raw: str) -> list[dict[str, Any]] | None:
    text = (raw or "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        t = str(item.get("text") or "").strip()
        l = str(item.get("label") or "").strip()
        if len(t) < MIN_TEXT_LENGTH or "\n" in t or l not in LABELS:
            continue
        out.append({"text": t, "label": l, "source_pattern": "augmentation"})
    return out


def run_augment_workers(
    cfg: RefineConfig,
    *,
    run_id: str,
    expected_labels: int,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    group = f"{cfg.augment_consumer_group}:{run_id}"
    stream_group_create(cfg.augment_tasks_stream, group)

    def _mk_pool() -> OllamaPool:
        return OllamaPool(
            cfg.ollama_urls,
            model=cfg.ollama_model,
            timeout_seconds=cfg.ollama_timeout_seconds,
            max_inflight_per_instance=cfg.ollama_max_inflight_per_instance,
        )

    pool = get_ollama_pool(_mk_pool)

    done_lock = threading.Lock()
    done_labels: set[str] = set()

    def _worker(worker_idx: int) -> None:
        consumer = f"{run_id[:8]}-{worker_idx}"
        while True:
            items = stream_read_group(
                cfg.augment_tasks_stream,
                group,
                consumer,
                count=1,
                block_ms=1000,
            )
            if not items:
                with done_lock:
                    if len(done_labels) >= expected_labels:
                        return
                continue

            entry_id, fields = items[0]
            try:
                if fields.get("run_id") != run_id:
                    continue
                label = str(fields.get("label") or "").strip()
                n = int(str(fields.get("n") or cfg.augment_n_per_label))
                if label not in LABELS:
                    raise ValueError(f"Invalid label: {label}")
                raw = pool.generate(prompt=augment_examples(label, n), system=SYSTEM_INSTRUCTIONS)
                parsed = _parse_json_array(raw)
                if parsed is None:
                    raise ValueError("Invalid JSON array from Ollama")

                out_path = _label_output_path(cfg, run_id, label)
                _write_csv(out_path, parsed, fieldnames=["text", "label", "source_pattern"])
                stream_ack(cfg.augment_tasks_stream, group, entry_id)
                with done_lock:
                    done_labels.add(label)
                    completed = len(done_labels)
                evt = {
                    "status": "progress",
                    "phase": "augment",
                    "detail": f"Augment {label} {completed}/{expected_labels} complete",
                    "label": label,
                }
                if progress:
                    progress(evt)
                publish_event(cfg.events_channel(run_id), evt)
            except (ValueError, json.JSONDecodeError, requests.RequestException) as e:
                err_evt = {
                    "status": "progress",
                    "phase": "augment",
                    "detail": f"Augment task failed: {e}",
                    "error": str(e),
                    "entry_id": entry_id,
                }
                if progress:
                    progress(err_evt)
                publish_event(cfg.events_channel(run_id), err_evt)

    threads = []
    max_workers = min(cfg.augment_max_parallel_labels, max(1, expected_labels))
    for i in range(max_workers):
        t = threading.Thread(target=_worker, args=(i,), daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()


def merge_augment_outputs(
    cfg: RefineConfig,
    *,
    run_id: str,
    train_df: pd.DataFrame,
) -> pd.DataFrame:
    labels_dir = cfg.augment_dir(run_id) / "labels"
    if not labels_dir.exists():
        return train_df
    example_rows: list[dict[str, Any]] = []
    for p in sorted(labels_dir.glob("proposed_examples.label_*.csv")):
        with open(p, encoding="utf-8", newline="") as f:
            example_rows.extend(list(csv.DictReader(f)))

    # Dedupe against existing texts; keep first occurrence.
    existing = set(train_df["text"].astype(str).str.strip())
    merged: list[dict[str, Any]] = []
    for r in example_rows:
        text = str(r.get("text") or "").strip()
        label = str(r.get("label") or "").strip()
        if not text or label not in LABELS:
            continue
        if text in existing:
            continue
        existing.add(text)
        merged.append({"text": text, "label": label, "source_pattern": r.get("source_pattern") or "augmentation"})

    _write_csv(cfg.augment_merged_csv(run_id), merged, fieldnames=["text", "label", "source_pattern"])

    result = pd.concat(
        [train_df, pd.DataFrame([{"text": r["text"], "label": r["label"]} for r in merged])],
        ignore_index=True,
    )
    cfg.augment_dir(run_id).mkdir(parents=True, exist_ok=True)
    result.to_csv(cfg.augment_candidate_csv(run_id), index=False)
    return result


def run_augment_phase(
    cfg: RefineConfig,
    *,
    model_artifacts_path: str,
    promote_target_path: str,
    run_id: str,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    cfg.ensure_run_dir(run_id)
    cfg.augment_dir(run_id).mkdir(parents=True, exist_ok=True)

    metrics_before = _read_metrics(model_artifacts_path)
    cfg.metrics_before_path(run_id).parent.mkdir(parents=True, exist_ok=True)
    with open(cfg.metrics_before_path(run_id), "w", encoding="utf-8") as f:
        json.dump(metrics_before, f, ensure_ascii=False, indent=2)

    labels = _labels_to_augment(metrics_before)
    total = enqueue_augment_tasks(cfg, run_id=run_id, labels=labels)

    start_evt = {
        "status": "progress",
        "phase": "augment",
        "detail": f"Enqueued {total} augmentation label tasks",
        "labels": labels,
    }
    if progress:
        progress(start_evt)
    publish_event(cfg.events_channel(run_id), start_evt)

    train_df = _read_train_csv(promote_target_path)
    run_augment_workers(cfg, run_id=run_id, expected_labels=total, progress=progress)
    candidate_df = merge_augment_outputs(cfg, run_id=run_id, train_df=train_df)

    compose_working_dir = os.environ.get("COMPOSE_WORKING_DIR", ".")
    metrics_after = train_candidate(
        compose_working_dir=compose_working_dir,
        candidate_csv=cfg.augment_candidate_csv(run_id),
        metrics_out=cfg.augment_candidate_metrics_json(run_id),
        timeout_seconds=int(os.environ.get("RUN_TRAIN_TIMEOUT_SECONDS", "3600")),
    )

    return {
        "run_id": run_id,
        "labels": labels,
        "train_augment_candidate_rows": int(len(candidate_df)),
        "metrics_before": metrics_before,
        "metrics_after": metrics_after,
        "proposed_examples": _read_csv_rows(cfg.augment_merged_csv(run_id)),
    }
