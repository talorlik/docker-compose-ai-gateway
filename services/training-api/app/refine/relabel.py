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
    stream_auto_claim_pending,
    stream_get_delivery_count,
    stream_read_group,
)
from app.refine.config import RefineConfig
from app.refine.ollama_pool import OllamaPool, get_ollama_pool
from app.refine.prompts import LABELS, SYSTEM_INSTRUCTIONS, relabel_misclassified_batch
from app.refine.training import train_candidate


def _parse_json_response(raw: str) -> list[dict[str, Any]] | None:
    text = (raw or "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


@dataclass(frozen=True)
class RelabelTask:
    run_id: str
    batch_id: str
    rows: list[dict[str, str]]


def _task_fields(task: RelabelTask) -> dict[str, Any]:
    return {
        "run_id": task.run_id,
        "batch_id": task.batch_id,
        "rows": task.rows,
    }


def _read_misclassified(artifacts_dir: str) -> list[dict[str, str]]:
    path = os.path.join(artifacts_dir, "misclassified.csv")
    if not os.path.exists(path):
        raise FileNotFoundError(f"misclassified.csv not found at {path}")
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows: list[dict[str, str]] = []
        for r in reader:
            rows.append(
                {
                    "text": str(r.get("text") or ""),
                    "true_label": str(r.get("true_label") or ""),
                    "pred_label": str(r.get("pred_label") or ""),
                }
            )
        return rows


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


def enqueue_relabel_batches(
    cfg: RefineConfig,
    *,
    run_id: str,
    misclassified_rows: list[dict[str, str]],
) -> int:
    batches: list[RelabelTask] = []
    bs = cfg.relabel_batch_size
    for i in range(0, len(misclassified_rows), bs):
        batch_rows = misclassified_rows[i : i + bs]
        batch_id = f"{i//bs:04d}"
        batches.append(RelabelTask(run_id=run_id, batch_id=batch_id, rows=batch_rows))

    for t in batches:
        stream_add(cfg.relabel_tasks_stream, _task_fields(t))

    return len(batches)


def _batch_output_path(cfg: RefineConfig, run_id: str, batch_id: str) -> Path:
    return cfg.relabel_dir(run_id) / "batches" / f"proposed_relabels.batch_{batch_id}.csv"


def _handle_task(
    *,
    cfg: RefineConfig,
    pool: OllamaPool,
    task: RelabelTask,
) -> list[dict[str, Any]]:
    _ = cfg  # reserved for future cfg-driven prompt options
    prompt = relabel_misclassified_batch(task.rows)
    raw = pool.generate(prompt=prompt, system=SYSTEM_INSTRUCTIONS)
    parsed = _parse_json_response(raw)
    if parsed is None:
        raise ValueError("Invalid JSON array from Ollama")

    out: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        suggested = str(item.get("suggested_label") or "").strip()
        reason = str(item.get("reason") or "").strip()
        try:
            conf = float(item.get("confidence") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        if suggested not in LABELS:
            continue
        if not text:
            continue
        out.append(
            {
                "text": text,
                "suggested_label": suggested,
                "reason": reason,
                "confidence": conf,
            }
        )
    return out


def run_relabel_workers(
    cfg: RefineConfig,
    *,
    run_id: str,
    expected_batches: int,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    group = f"{cfg.relabel_consumer_group}:{run_id}"
    stream_group_create(cfg.relabel_tasks_stream, group)

    def _mk_pool() -> OllamaPool:
        return OllamaPool(
            cfg.ollama_urls,
            model=cfg.ollama_model,
            timeout_seconds=cfg.ollama_timeout_seconds,
            max_inflight_per_instance=cfg.ollama_max_inflight_per_instance,
            num_ctx=cfg.ollama_num_ctx,
            num_predict=cfg.ollama_num_predict,
        )

    pool = get_ollama_pool(_mk_pool)

    done_lock = threading.Lock()
    done_batches: set[str] = set()

    max_retries = int(os.environ.get("REFINER_RELABEL_MAX_RETRIES", "3"))

    def _worker(worker_idx: int) -> None:
        consumer = f"{run_id[:8]}-{worker_idx}"
        while True:
            items = stream_read_group(
                cfg.relabel_tasks_stream,
                group,
                consumer,
                count=1,
                block_ms=1000,
            )
            if not items:
                # Nothing new; attempt to claim any idle pending entries so that
                # timeouts or crashed workers do not leave the job stuck.
                pending = stream_auto_claim_pending(
                    cfg.relabel_tasks_stream,
                    group,
                    consumer,
                    min_idle_ms=cfg.ollama_timeout_seconds * 1000,
                    count=1,
                )
                if not pending:
                    with done_lock:
                        if len(done_batches) >= expected_batches:
                            return
                    continue
                items = pending

            entry_id, fields = items[0]
            try:
                if fields.get("run_id") != run_id:
                    # Not for this run; leave unacked for other consumers.
                    continue
                batch_id = fields.get("batch_id") or entry_id.replace("-", "_")
                rows_raw = fields.get("rows") or "[]"
                rows = json.loads(rows_raw) if isinstance(rows_raw, str) else []
                task = RelabelTask(run_id=run_id, batch_id=str(batch_id), rows=rows)
                proposed = _handle_task(cfg=cfg, pool=pool, task=task)
                out_path = _batch_output_path(cfg, run_id, task.batch_id)
                _write_csv(
                    out_path,
                    proposed,
                    fieldnames=["text", "suggested_label", "reason", "confidence"],
                )
                stream_ack(cfg.relabel_tasks_stream, group, entry_id)
                with done_lock:
                    done_batches.add(task.batch_id)
                    completed = len(done_batches)
                evt = {
                    "status": "progress",
                    "phase": "relabel",
                    "detail": f"Relabel batch {completed}/{expected_batches} complete",
                    "batch_id": task.batch_id,
                }
                if progress:
                    progress(evt)
                publish_event(cfg.events_channel(run_id), evt)
            except (ValueError, json.JSONDecodeError, requests.RequestException, KeyError, TypeError) as e:
                err_evt = {
                    "status": "progress",
                    "phase": "relabel",
                    "detail": f"Relabel batch failed: {e}",
                    "error": str(e),
                    "entry_id": entry_id,
                    "batch_id": fields.get("batch_id"),
                }
                if progress:
                    progress(err_evt)
                publish_event(cfg.events_channel(run_id), err_evt)
                # Decide whether to leave pending for retry or mark permanently failed.
                deliveries = stream_get_delivery_count(
                    cfg.relabel_tasks_stream,
                    group,
                    entry_id,
                )
                if deliveries is not None and deliveries >= max_retries:
                    # Give up on this batch so the overall job can complete.
                    stream_ack(cfg.relabel_tasks_stream, group, entry_id)
                    with done_lock:
                        done_batches.add(str(fields.get("batch_id") or entry_id.replace("-", "_")))

    threads = []
    for i in range(cfg.relabel_max_parallel_batches):
        t = threading.Thread(target=_worker, args=(i,), daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()


def merge_relabel_outputs(
    cfg: RefineConfig,
    *,
    run_id: str,
    train_df: pd.DataFrame,
) -> pd.DataFrame:
    batches_dir = cfg.relabel_dir(run_id) / "batches"
    if not batches_dir.exists():
        return train_df
    relabel_rows: list[dict[str, Any]] = []
    for p in sorted(batches_dir.glob("proposed_relabels.batch_*.csv")):
        with open(p, encoding="utf-8", newline="") as f:
            relabel_rows.extend(list(csv.DictReader(f)))

    # Filter: valid labels, non-empty text, keep last suggestion per text
    latest: dict[str, dict[str, Any]] = {}
    for r in relabel_rows:
        text = str(r.get("text") or "").strip()
        suggested = str(r.get("suggested_label") or "").strip()
        if not text or suggested not in LABELS:
            continue
        latest[text] = r

    merged_rows = list(latest.values())
    _write_csv(
        cfg.relabel_merged_csv(run_id),
        merged_rows,
        fieldnames=["text", "suggested_label", "reason", "confidence"],
    )

    result = train_df.copy()
    proposed_map = {str(r["text"]).strip(): str(r["suggested_label"]).strip() for r in merged_rows}
    mask = result["text"].astype(str).str.strip().isin(proposed_map.keys())
    result.loc[mask, "label"] = result.loc[mask, "text"].astype(str).str.strip().map(proposed_map)
    cfg.relabel_dir(run_id).mkdir(parents=True, exist_ok=True)
    result.to_csv(cfg.relabel_candidate_csv(run_id), index=False)
    return result


def run_relabel_phase(
    cfg: RefineConfig,
    *,
    model_artifacts_path: str,
    promote_target_path: str,
    run_id: str,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    cfg.ensure_run_dir(run_id)
    cfg.relabel_dir(run_id).mkdir(parents=True, exist_ok=True)

    misclassified = _read_misclassified(model_artifacts_path)
    if not misclassified:
        raise RuntimeError("misclassified.csv is empty - nothing to relabel")

    metrics_before = _read_metrics(model_artifacts_path)
    cfg.metrics_before_path(run_id).parent.mkdir(parents=True, exist_ok=True)
    with open(cfg.metrics_before_path(run_id), "w", encoding="utf-8") as f:
        json.dump(metrics_before, f, ensure_ascii=False, indent=2)

    train_df = _read_train_csv(promote_target_path)
    # Create the consumer group BEFORE enqueueing so workers don't miss entries.
    # stream_group_create handles BUSYGROUP silently, so the redundant call
    # inside run_relabel_workers is harmless.
    stream_group_create(
        cfg.relabel_tasks_stream, f"{cfg.relabel_consumer_group}:{run_id}"
    )
    total_batches = enqueue_relabel_batches(cfg, run_id=run_id, misclassified_rows=misclassified)

    start_evt = {
        "status": "progress",
        "phase": "relabel",
        "detail": f"Enqueued {total_batches} relabel batches",
        "batches": total_batches,
    }
    if progress:
        progress(start_evt)
    publish_event(cfg.events_channel(run_id), start_evt)

    run_relabel_workers(cfg, run_id=run_id, expected_batches=total_batches, progress=progress)
    candidate_df = merge_relabel_outputs(cfg, run_id=run_id, train_df=train_df)

    # Train candidate and persist metrics for UI comparison
    compose_working_dir = os.environ.get("COMPOSE_WORKING_DIR", ".")
    metrics_after = train_candidate(
        compose_working_dir=compose_working_dir,
        candidate_csv=cfg.relabel_candidate_csv(run_id),
        metrics_out=cfg.relabel_candidate_metrics_json(run_id),
        timeout_seconds=int(os.environ.get("RUN_TRAIN_TIMEOUT_SECONDS", "3600")),
    )

    return {
        "run_id": run_id,
        "batches": total_batches,
        "train_relabel_candidate_rows": int(len(candidate_df)),
        "metrics_before": metrics_before,
        "metrics_after": metrics_after,
        "proposed_relabels": _read_csv_rows(cfg.relabel_merged_csv(run_id)),
    }
