from __future__ import annotations

import csv
import json
import os
import random
import threading
from collections import defaultdict
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
from app.refine.prompts import (
    LABELS,
    SYSTEM_INSTRUCTIONS,
    augment_examples,
    relabel_misclassified_batch,
)
from app.refine.training import train_candidate
from app.refine.parser import parse_json_response


MIN_TEXT_LENGTH = 3
FUZZY_DEDUP_JACCARD_THRESHOLD = 0.85


@dataclass(frozen=True)
class AugmentTask:
    run_id: str
    label: str
    n: int


def _char_trigrams(text: str) -> set[str]:
    t = text.strip()
    if len(t) < 3:
        return {t} if t else set()
    return {t[i : i + 3] for i in range(len(t) - 2)}


def _trigram_jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _is_fuzzy_duplicate(
    text: str, reference_sets: list[set[str]], threshold: float = FUZZY_DEDUP_JACCARD_THRESHOLD
) -> bool:
    tset = _char_trigrams(text)
    for ref in reference_sets:
        if _trigram_jaccard(tset, ref) > threshold:
            return True
    return False


def _compute_augment_counts(
    train_df: pd.DataFrame,
    labels: list[str],
    base_n: int,
) -> dict[str, int]:
    """Weight per-label N by class frequency: rarer classes get more synthetic rows."""
    counts: dict[str, int] = {}
    if train_df.empty or "label" not in train_df.columns:
        return {lab: base_n for lab in labels}
    vc = train_df["label"].astype(str).str.strip().value_counts()
    max_c = int(vc.max()) if len(vc) else 1
    max_c = max(max_c, 1)
    cap = 3 * base_n
    for lab in labels:
        this_c = int(vc.get(lab, 0)) if lab in vc.index else 0
        denom = max(this_c, 1)
        n = int(round(base_n * (max_c / denom)))
        n = max(base_n, min(cap, n))
        counts[lab] = n
    return counts


def _sample_seed_texts(
    train_df: pd.DataFrame,
    label: str,
    k: int,
    rng: random.Random,
) -> list[str]:
    if k <= 0:
        return []
    sub = train_df[train_df["label"].astype(str).str.strip() == label]
    texts = [str(x).strip() for x in sub["text"].astype(str).tolist() if str(x).strip()]
    if not texts:
        return []
    if len(texts) <= k:
        return texts
    return rng.sample(texts, k)


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content or "")


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


def enqueue_augment_tasks(
    cfg: RefineConfig,
    *,
    run_id: str,
    labels: list[str],
    label_counts: dict[str, int] | None = None,
) -> int:
    for label in labels:
        n = (
            int(label_counts.get(label, cfg.augment_n_per_label))
            if label_counts
            else cfg.augment_n_per_label
        )
        stream_add(
            cfg.augment_tasks_stream,
            {"run_id": run_id, "label": label, "n": str(max(1, n))},
        )
    return len(labels)


def _label_output_path(cfg: RefineConfig, run_id: str, label: str) -> Path:
    safe = label.replace("/", "_")
    return cfg.augment_dir(run_id) / "labels" / f"proposed_examples.label_{safe}.csv"


def _label_raw_output_path(cfg: RefineConfig, run_id: str, label: str) -> Path:
    safe = label.replace("/", "_")
    return cfg.augment_dir(run_id) / "labels" / f"raw_augment.label_{safe}.txt"


def _label_prompt_output_path(cfg: RefineConfig, run_id: str, label: str) -> Path:
    safe = label.replace("/", "_")
    return cfg.augment_dir(run_id) / "labels" / f"prompt_augment.label_{safe}.txt"


def _label_validation_output_path(cfg: RefineConfig, run_id: str, label: str) -> Path:
    safe = label.replace("/", "_")
    return cfg.augment_dir(run_id) / "labels" / f"augment.label_{safe}.validation.json"


def _label_rejected_output_path(cfg: RefineConfig, run_id: str, label: str) -> Path:
    safe = label.replace("/", "_")
    return cfg.augment_dir(run_id) / "labels" / f"augment.label_{safe}.rejected_items.csv"


def _parse_json_array(raw: str) -> list[dict[str, Any]] | None:
    data = parse_json_response(raw)
    if not data:
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


def _parse_json_array_etl(
    *,
    raw: str,
    expected_label: str,
    max_text_length: int,
) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]], dict[str, Any]]:
    data = parse_json_response(raw)

    if data is None:
        return (
            None,
            [],
            {
                "error_code": "INVALID_JSON_ARRAY",
                "error_message": "Invalid JSON array from Ollama",
            },
        )

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            rejected.append({"idx": idx, "error_code": "INVALID_ITEM_TYPE"})
            continue

        t = str(item.get("text") or "").strip()
        l = str(item.get("label") or "").strip()

        # Preserve current acceptance semantics (order of checks matters).
        if len(t) < MIN_TEXT_LENGTH:
            rejected.append(
                {"idx": idx, "error_code": "TEXT_TOO_SHORT", "text": t, "label": l}
            )
            continue
        if "\n" in t:
            rejected.append(
                {
                    "idx": idx,
                    "error_code": "TEXT_CONTAINS_NEWLINE",
                    "text": t,
                    "label": l,
                }
            )
            continue
        if l not in LABELS:
            rejected.append(
                {"idx": idx, "error_code": "INVALID_LABEL", "text": t, "label": l}
            )
            continue
        if l != expected_label:
            rejected.append(
                {
                    "idx": idx,
                    "error_code": "LABEL_MISMATCH",
                    "text": t,
                    "label": l,
                }
            )
            continue
        if len(t) > max_text_length:
            rejected.append(
                {
                    "idx": idx,
                    "error_code": "TEXT_TOO_LONG",
                    "text": t,
                    "label": l,
                }
            )
            continue

        accepted.append({"text": t, "label": l, "source_pattern": "augmentation"})

    validation: dict[str, Any] = {
        "error_code": None,
        "parsed_items_count": int(len(data)),
        "accepted_items_count": int(len(accepted)),
        "rejected_items_count": int(len(rejected)),
        "rejected_items": rejected,
    }
    return accepted, rejected, validation


def _verify_augmented_examples(
    cfg: RefineConfig,
    *,
    intended_label: str,
    accepted: list[dict[str, Any]],
    pool: OllamaPool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Re-label generated rows; keep rows that match intended_label with enough confidence."""
    if not cfg.augment_verify_labels or not accepted:
        return accepted, [], {"verified_count": len(accepted), "verification_rejected_count": 0}

    verified: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    batch_size = max(1, cfg.relabel_batch_size)

    for i in range(0, len(accepted), batch_size):
        chunk = accepted[i : i + batch_size]
        rows = [
            {"text": ex["text"], "true_label": intended_label, "pred_label": intended_label}
            for ex in chunk
        ]
        prompt = relabel_misclassified_batch(rows)
        raw = pool.generate(prompt=prompt, system=SYSTEM_INSTRUCTIONS)
        parsed = parse_json_response(raw)
        if not parsed or len(parsed) != len(chunk):
            for ex in chunk:
                rejected.append(
                    {
                        **ex,
                        "error_code": "VERIFICATION_FAILED",
                        "reason": "invalid_verify_response",
                    }
                )
            continue
        for ex, obj in zip(chunk, parsed):
            sugg = str(obj.get("suggested_label") or "").strip()
            conf_raw = obj.get("confidence", 0.0)
            try:
                conf = float(conf_raw)
            except (TypeError, ValueError):
                conf = 0.0
            if sugg != intended_label or conf < cfg.augment_verify_min_confidence:
                rejected.append(
                    {
                        **ex,
                        "error_code": "VERIFICATION_FAILED",
                        "suggested_label": sugg,
                        "confidence": conf,
                    }
                )
            else:
                verified.append(ex)

    stats = {
        "verified_count": len(verified),
        "verification_rejected_count": len(rejected),
    }
    return verified, rejected, stats


def run_augment_workers(
    cfg: RefineConfig,
    *,
    run_id: str,
    expected_labels: int,
    train_df: pd.DataFrame,
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
            num_ctx=cfg.ollama_num_ctx,
            num_predict=cfg.ollama_num_predict,
            temperature=cfg.refiner_temperature,
            seed=cfg.refiner_seed,
            structured_output_enabled=cfg.structured_output_enabled,
        )

    pool = get_ollama_pool(_mk_pool)
    rng = random.Random(cfg.refiner_seed)

    done_lock = threading.Lock()
    done_labels: set[str] = set()

    max_retries = int(os.environ.get("REFINER_AUGMENT_MAX_RETRIES", "3"))

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
                # Nothing new; attempt to claim any idle pending entries so that
                # timeouts or crashed workers do not leave the job stuck.
                pending = stream_auto_claim_pending(
                    cfg.augment_tasks_stream,
                    group,
                    consumer,
                    min_idle_ms=cfg.ollama_timeout_seconds * 1000,
                    count=1,
                )
                if not pending:
                    with done_lock:
                        if len(done_labels) >= expected_labels:
                            return
                    continue
                items = pending

            entry_id, fields = items[0]
            try:
                if fields.get("run_id") != run_id:
                    continue
                label = str(fields.get("label") or "").strip()
                n = int(str(fields.get("n") or cfg.augment_n_per_label))
                if label not in LABELS:
                    raise ValueError(f"Invalid label: {label}")

                seeds = _sample_seed_texts(
                    train_df, label, cfg.augment_seed_examples, rng
                )
                prompt = augment_examples(label, n, seeds)
                raw = pool.generate(prompt=prompt, system=SYSTEM_INSTRUCTIONS)

                _write_text(_label_raw_output_path(cfg, run_id, label), raw)
                _write_text(_label_prompt_output_path(cfg, run_id, label), prompt)

                accepted, rejected, validation = _parse_json_array_etl(
                    raw=raw,
                    expected_label=label,
                    max_text_length=cfg.augment_max_text_length,
                )
                validation.update({"label": label, "n": int(n)})

                if accepted is None:
                    raise ValueError("Invalid JSON array from Ollama")

                verify_rejected: list[dict[str, Any]] = []
                if accepted:
                    verified, verify_rejected, vstats = _verify_augmented_examples(
                        cfg,
                        intended_label=label,
                        accepted=accepted,
                        pool=pool,
                    )
                    accepted = verified
                    validation.update(vstats)
                else:
                    validation.update(
                        {"verified_count": 0, "verification_rejected_count": 0}
                    )

                all_rejected = list(rejected) + verify_rejected
                _write_json(_label_validation_output_path(cfg, run_id, label), validation)

                if all_rejected:
                    rej_fields = [
                        "idx",
                        "error_code",
                        "text",
                        "label",
                        "reason",
                        "suggested_label",
                        "confidence",
                    ]
                    norm_rejected = [
                        {
                            "idx": r.get("idx", ""),
                            "error_code": r.get("error_code", ""),
                            "text": r.get("text", ""),
                            "label": r.get("label", ""),
                            "reason": r.get("reason", ""),
                            "suggested_label": r.get("suggested_label", ""),
                            "confidence": r.get("confidence", ""),
                        }
                        for r in all_rejected
                    ]
                    _write_csv(
                        _label_rejected_output_path(cfg, run_id, label),
                        norm_rejected,
                        fieldnames=rej_fields,
                    )

                out_path = _label_output_path(cfg, run_id, label)
                _write_csv(
                    out_path, accepted, fieldnames=["text", "label", "source_pattern"]
                )
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
                    "label": fields.get("label"),
                }
                if progress:
                    progress(err_evt)
                publish_event(cfg.events_channel(run_id), err_evt)
                deliveries = stream_get_delivery_count(
                    cfg.augment_tasks_stream,
                    group,
                    entry_id,
                )
                if deliveries is not None and deliveries >= max_retries:
                    # Give up on this label so the overall job can complete.
                    stream_ack(cfg.augment_tasks_stream, group, entry_id)
                    with done_lock:
                        label_done = str(fields.get("label") or "").strip()
                        if label_done:
                            done_labels.add(label_done)

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

    refs_by_label: dict[str, list[set[str]]] = defaultdict(list)
    for _, row in train_df.iterrows():
        lab = str(row.get("label") or "").strip()
        tx = str(row.get("text") or "").strip()
        if lab in LABELS and tx:
            refs_by_label[lab].append(_char_trigrams(tx))

    # Dedupe against existing texts; keep first occurrence.
    existing = set(train_df["text"].astype(str).str.strip())
    merged: list[dict[str, Any]] = []
    invalid_rows_count = 0
    duplicate_existing_count = 0
    fuzzy_duplicate_count = 0
    for r in example_rows:
        text = str(r.get("text") or "").strip()
        label = str(r.get("label") or "").strip()
        if not text or label not in LABELS:
            invalid_rows_count += 1
            continue
        if text in existing:
            duplicate_existing_count += 1
            continue
        refs = refs_by_label.get(label, [])
        if _is_fuzzy_duplicate(text, refs):
            fuzzy_duplicate_count += 1
            continue
        existing.add(text)
        merged.append(
            {
                "text": text,
                "label": label,
                "source_pattern": r.get("source_pattern") or "augmentation",
            }
        )
        refs_by_label[label].append(_char_trigrams(text))

    _write_json(
        cfg.augment_dir(run_id) / "merge_augment.validation.json",
        {
            "input_rows_count": int(len(example_rows)),
            "accepted_rows_count": int(len(merged)),
            "invalid_rows_count": int(invalid_rows_count),
            "duplicate_existing_count": int(duplicate_existing_count),
            "fuzzy_duplicate_count": int(fuzzy_duplicate_count),
        },
    )

    _write_csv(
        cfg.augment_merged_csv(run_id), merged, fieldnames=["text", "label", "source_pattern"]
    )

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
    train_df = _read_train_csv(promote_target_path)
    label_counts = _compute_augment_counts(train_df, labels, cfg.augment_n_per_label)
    # Create the consumer group BEFORE enqueueing so workers don't miss entries.
    stream_group_create(
        cfg.augment_tasks_stream, f"{cfg.augment_consumer_group}:{run_id}"
    )
    total = enqueue_augment_tasks(
        cfg, run_id=run_id, labels=labels, label_counts=label_counts
    )

    start_evt = {
        "status": "progress",
        "phase": "augment",
        "detail": f"Enqueued {total} augmentation label tasks",
        "labels": labels,
        "label_counts": label_counts,
    }
    if progress:
        progress(start_evt)
    publish_event(cfg.events_channel(run_id), start_evt)

    run_augment_workers(
        cfg,
        run_id=run_id,
        expected_labels=total,
        train_df=train_df,
        progress=progress,
    )
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
