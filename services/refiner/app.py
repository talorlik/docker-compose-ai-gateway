#!/usr/bin/env python3
"""
Refiner service: analyze misclassified.csv via local LLM (Ollama), produce
proposals, and write a candidate dataset. Only data that improves results
is promoted to train.csv (via the promote script).

The refiner writes train_candidate.csv (merged relabels + examples). Run
scripts/promote.sh to retrain with the candidate and promote to train.csv
only if metrics improve.

Reads (from shared volume model_artifacts:/data):
  - misclassified.csv (identify mistakes to analyze)
  - metrics.json (detect weak labels, confusion patterns; NOT used to change
    labels directly; see docs/auxiliary/reference/METRICS_JSON.md)
Reads (from host mount):
  - train.csv (canonical dataset)
Writes:
  - /data/proposed_relabels.csv, /data/proposed_examples.csv (audit)
  - /data/refinement_report.json (summary counts and quality stats)
  - /data/train_candidate.csv (candidate for promotion)
  - /data/metrics_before.json (snapshot for promote comparison)
"""

from __future__ import annotations

import json
import os
import re
import sys

import pandas as pd
import requests

from prompts import (
    LABELS,
    SYSTEM_INSTRUCTIONS,
    augment_examples,
    connectivity_check,
    relabel_misclassified,
)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "phi3:mini")
OLLAMA_TIMEOUT = 300


def _get_row_limit() -> int:
    """Limit misclassified rows for initial runs (e.g. REFINER_LIMIT=20). 0 = no limit."""
    limit = os.getenv("REFINER_LIMIT", "0")
    try:
        return max(0, int(limit))
    except ValueError:
        return 0

# Paths configurable via env so refiner can be run from training-api (no Docker).
_REFINER_DATA_DIR = os.environ.get("REFINER_DATA_DIR", "/data")
_REFINER_TRAIN_PATH = os.environ.get("REFINER_TRAIN_PATH", os.path.join(_REFINER_DATA_DIR, "train.csv"))

TRAIN_PATH = _REFINER_TRAIN_PATH
MISCLASSIFIED_PATH = os.path.join(_REFINER_DATA_DIR, "misclassified.csv")
METRICS_PATH = os.path.join(_REFINER_DATA_DIR, "metrics.json")
OUT_RELABELS = os.path.join(_REFINER_DATA_DIR, "proposed_relabels.csv")
OUT_EXAMPLES = os.path.join(_REFINER_DATA_DIR, "proposed_examples.csv")
OUT_REPORT = os.path.join(_REFINER_DATA_DIR, "refinement_report.json")
TRAIN_CANDIDATE_PATH = os.path.join(_REFINER_DATA_DIR, "train_candidate.csv")
METRICS_BEFORE_PATH = os.path.join(_REFINER_DATA_DIR, "metrics_before.json")

TRAIN_REQUIRED = {"text", "label"}
MISCLASSIFIED_REQUIRED = {"text", "true_label", "pred_label"}
MIN_TEXT_LENGTH = 3


def _get_banned_patterns() -> list[str]:
    """Configurable banned substrings (REFINER_BANNED_PATTERNS=foo,bar)."""
    raw = os.getenv("REFINER_BANNED_PATTERNS", "")
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def _log(level: str, msg: str, **kwargs: object) -> None:
    """Structured log line (JSON) for progress and audit."""
    record = {"level": level, "message": msg, **kwargs}
    print(json.dumps(record), file=sys.stderr)


AUGMENT_MIN_PER_LABEL = 5
AUGMENT_MAX_ATTEMPTS = 2
AUGMENT_SKIP_THRESHOLD = 150
WEAK_RECALL_THRESHOLD = 0.75
CONFUSION_COUNT_THRESHOLD = 10


def _validate_columns(df: pd.DataFrame, path: str, required: set[str]) -> None:
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path}: missing required columns: {sorted(missing)}")


def ask_ollama(prompt: str, system: str | None = None) -> str:
    """POST to Ollama /api/generate; return response text. Raises RequestException on failure."""
    url = f"{OLLAMA_HOST}/api/generate"
    payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}
    if system is not None:
        payload["system"] = system
    r = requests.post(url, json=payload, timeout=OLLAMA_TIMEOUT)
    r.raise_for_status()
    return r.json()["response"]


def _parse_json_response(raw: str) -> dict | list | None:
    """Parse JSON from LLM response; strip markdown code fences if present."""
    text = raw.strip()
    # Strip markdown code fences
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        text = match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def ingest() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load and validate train.csv and misclassified.csv."""
    if not os.path.exists(TRAIN_PATH):
        raise FileNotFoundError(f"train.csv not found at {TRAIN_PATH}")

    if not os.path.exists(MISCLASSIFIED_PATH):
        raise FileNotFoundError(f"misclassified.csv not found at {MISCLASSIFIED_PATH}")

    train_df = pd.read_csv(TRAIN_PATH)
    _validate_columns(train_df, TRAIN_PATH, TRAIN_REQUIRED)

    misclassified_df = pd.read_csv(MISCLASSIFIED_PATH)
    _validate_columns(misclassified_df, MISCLASSIFIED_PATH, MISCLASSIFIED_REQUIRED)

    return train_df, misclassified_df


def _load_metrics() -> dict | None:
    """Load metrics.json if present. Returns None if missing or invalid."""
    if not os.path.exists(METRICS_PATH):
        return None
    try:
        with open(METRICS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _get_labels_to_augment(
    misclassified_df: pd.DataFrame,
    metrics: dict | None,
) -> set[str]:
    """
    Determine which labels need augmentation from misclassified.csv and
    metrics.json. metrics.json is the evaluation signal: it identifies weak
    labels (low recall) and confusion patterns. It is NOT used to change
    labels directly.
    """
    labels = set(misclassified_df["true_label"].astype(str).str.strip())

    if metrics is None:
        return labels

    # 1. Weak labels: recall < threshold
    report = metrics.get("classification_report", {})
    for label in LABELS:
        if label in report and isinstance(report[label], dict):
            recall = report[label].get("recall")
            if recall is not None and recall < WEAK_RECALL_THRESHOLD:
                labels.add(label)

    # 2. Confusion patterns: true_label A often predicted as B -> augment A
    cm = metrics.get("confusion_matrix", [])
    if cm and len(cm) == len(LABELS):
        for i, true_label in enumerate(LABELS):
            if i >= len(cm):
                break
            row = cm[i]
            for j, pred_label in enumerate(LABELS):
                if j >= len(row) or i == j:
                    continue
                if row[j] >= CONFUSION_COUNT_THRESHOLD:
                    labels.add(true_label)

    return labels


def _filter_relabels(
    relabels: list[dict],
    train_df: pd.DataFrame,
    banned_patterns: list[str] | None = None,
) -> list[dict]:
    """
    Apply deterministic filters: min length, dedupe against train and within
    proposals, banned-pattern check.
    """
    existing = set(
        zip(
            train_df["text"].astype(str).str.strip(),
            train_df["label"].astype(str).str.strip(),
        )
    )
    banned = banned_patterns or _get_banned_patterns()
    seen_proposals: set[tuple[str, str]] = set()
    filtered: list[dict] = []
    for r in relabels:
        text = str(r.get("text", "")).strip()
        label = str(r.get("suggested_label", "")).strip()
        if len(text) < MIN_TEXT_LENGTH:
            continue
        if (text, label) in existing:
            continue
        if (text, label) in seen_proposals:
            continue
        if banned and any(b in text for b in banned):
            continue
        seen_proposals.add((text, label))
        filtered.append(r)
    return filtered


def merge_into_train(
    train_df: pd.DataFrame,
    relabels: list[dict],
    examples: list[dict],
) -> pd.DataFrame:
    """Merge relabels (update) and examples (append) into train dataframe."""
    result = train_df.copy()

    text_to_idx: dict[str, list[int]] = {}
    for idx, val in enumerate(result["text"].astype(str).str.strip()):
        text_to_idx.setdefault(val, []).append(idx)

    for r in relabels:
        text = str(r["text"]).strip()
        label = str(r["suggested_label"]).strip()
        indices = text_to_idx.get(text, [])
        if indices:
            result.loc[indices, "label"] = label

    existing_texts = set(result["text"].astype(str).str.strip())
    new_rows: list[dict] = []
    for ex in examples:
        text = str(ex.get("text", "")).strip()
        label = str(ex.get("label", "")).strip()
        if len(text) >= MIN_TEXT_LENGTH and text not in existing_texts:
            new_rows.append({"text": text, "label": label})
            existing_texts.add(text)

    if new_rows:
        result = pd.concat(
            [result, pd.DataFrame(new_rows)],
            ignore_index=True,
        )

    return result


def main() -> int:
    if not os.path.exists(MISCLASSIFIED_PATH):
        print("misclassified.csv not found - nothing to refine", file=sys.stderr)
        return 0

    try:
        train_df, misclassified_df = ingest()
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 1
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    if misclassified_df.empty:
        print("misclassified.csv is empty - nothing to refine", file=sys.stderr)
        return 0

    try:
        _ = ask_ollama(connectivity_check(), system=SYSTEM_INSTRUCTIONS)
    except requests.RequestException as e:
        _log("error", "ollama_unreachable", host=OLLAMA_HOST, detail=str(e))
        print("Ollama is not available. Ensure the stack is running with Ollama.", file=sys.stderr)
        print(f"Ollama unreachable at {OLLAMA_HOST}: {e}", file=sys.stderr)
        return 1

    metrics = _load_metrics()
    _log("info", "ingest complete", train_rows=len(train_df), misclassified_rows=len(misclassified_df))
    if metrics and "accuracy" in metrics:
        _log("info", "metrics loaded", accuracy=round(metrics["accuracy"], 2))
    _log("info", "ollama reachable", host=OLLAMA_HOST)

    relabel_rows: list[dict] = []
    example_rows: list[dict] = []
    rows_skipped = 0
    errors = 0

    row_limit = _get_row_limit()
    rows_to_process = misclassified_df.head(row_limit) if row_limit else misclassified_df
    if row_limit:
        _log("info", "row limit applied", limit=row_limit, rows_to_process=len(rows_to_process))

    for idx, (_, row) in enumerate(rows_to_process.iterrows(), 1):
        text = str(row["text"])
        true_label = str(row["true_label"])
        pred_label = str(row["pred_label"])
        _log("info", "processing row", idx=idx, total=len(rows_to_process), text_preview=text[:50])

        try:
            response = ask_ollama(
                relabel_misclassified(text, true_label, pred_label),
                system=SYSTEM_INSTRUCTIONS,
            )
            data = _parse_json_response(response)
            if not isinstance(data, dict):
                rows_skipped += 1
                continue
            suggested = str(data.get("suggested_label", "")).strip()
            reason = str(data.get("reason", ""))
            confidence = float(data.get("confidence", 0.0))
            if suggested not in LABELS:
                rows_skipped += 1
                continue

            relabel_rows.append({
                "text": text,
                "current_label": true_label,
                "suggested_label": suggested,
                "reason": reason,
                "confidence": confidence,
            })
        except (requests.RequestException, KeyError, ValueError, TypeError) as e:
            _log("warn", "row skipped", idx=idx, error=str(e))
            errors += 1

    # Augmentation: generate examples per label that needs it.
    # Uses metrics.json to detect weak labels (recall < 0.75) and confusion
    # patterns; metrics.json is NOT used to change labels directly.
    # Labels with >= AUGMENT_SKIP_THRESHOLD existing examples are skipped.
    labels_to_augment = _get_labels_to_augment(misclassified_df, metrics)
    label_counts = train_df["label"].astype(str).str.strip().value_counts().to_dict()
    existing_texts = set(train_df["text"].astype(str).str.strip())
    banned = _get_banned_patterns()
    for label in labels_to_augment:
        if label not in LABELS:
            continue
        current_count = label_counts.get(label, 0)
        if current_count >= AUGMENT_SKIP_THRESHOLD:
            _log("info", "augmentation skipped", label=label, current_count=current_count,
                 threshold=AUGMENT_SKIP_THRESHOLD)
            continue
        _log("info", "augmenting label", label=label, min_per_label=AUGMENT_MIN_PER_LABEL,
             current_count=current_count)
        collected: list[dict] = []
        attempts = 0
        while len(collected) < AUGMENT_MIN_PER_LABEL and attempts < AUGMENT_MAX_ATTEMPTS:
            attempts += 1
            try:
                needed = AUGMENT_MIN_PER_LABEL - len(collected)
                response = ask_ollama(
                    augment_examples(label, n=needed),
                    system=SYSTEM_INSTRUCTIONS,
                )
                data = _parse_json_response(response)
                if not isinstance(data, list):
                    continue
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    text = str(item.get("text", "")).strip()
                    lbl = str(item.get("label", label)).strip()
                    if (
                        len(text) >= MIN_TEXT_LENGTH
                        and text not in existing_texts
                        and not (banned and any(b in text for b in banned))
                    ):
                        collected.append({
                            "text": text,
                            "label": lbl,
                            "source_pattern": "augmentation",
                            "generator_model": OLLAMA_MODEL,
                        })
                        existing_texts.add(text)
                        example_rows.append(collected[-1])
            except (requests.RequestException, KeyError, ValueError, TypeError) as e:
                _log("warn", "augmentation attempt failed", label=label, attempt=attempts, error=str(e))
                errors += 1
                break
        _log("info", "augmentation complete", label=label, collected=len(collected))

    relabel_rows = _filter_relabels(relabel_rows, train_df)
    pd.DataFrame(relabel_rows).to_csv(OUT_RELABELS, index=False)
    pd.DataFrame(example_rows).to_csv(OUT_EXAMPLES, index=False)

    merged = merge_into_train(train_df, relabel_rows, example_rows)
    merged.to_csv(TRAIN_CANDIDATE_PATH, index=False)

    # Save metrics snapshot for promote script to compare
    metrics_to_save = metrics
    if metrics_to_save:
        with open(METRICS_BEFORE_PATH, "w", encoding="utf-8") as f:
            json.dump(metrics_to_save, f, indent=2)

    rows_processed = len(rows_to_process)
    report = {
        "rows_processed": rows_processed,
        "relabels_proposed": len(relabel_rows),
        "examples_proposed": len(example_rows),
        "rows_skipped": rows_skipped,
        "errors": errors,
    }
    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    _log("info", "files written", relabels=OUT_RELABELS, examples=OUT_EXAMPLES, report=OUT_REPORT)
    _log("info", "refinement complete", **report)
    print("Run scripts/promote.sh to retrain and promote only if metrics improve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
