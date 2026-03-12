#!/usr/bin/env python3
"""
train.py - Train intent router model (TF-IDF + Logistic Regression) and export model.joblib

Inputs:
  - train.csv (columns: text,label)

Outputs:
  - model.joblib (dict containing vectorizer, model, labels, metadata)
  - metrics.json (basic evaluation metrics + confusion matrix)
  - (optional) misclassified.csv (samples that failed on validation split)

Run:
  python train.py --data ./train.csv --out ./model.joblib

Notes:
  - Deterministic: fixed random_state
  - Multi-class: search/image/ops/unknown
  - Confidence: model.predict_proba available
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import train_test_split


DEFAULT_LABEL_ORDER = ["search", "image", "ops", "unknown"]


@dataclass(frozen=True)
class TrainConfig:
    data_path: str
    out_path: str
    metrics_path: str
    misclassified_path: str | None
    test_size: float
    random_state: int
    min_df: int
    max_df: float
    ngram_min: int
    ngram_max: int
    max_features: int | None
    C: float
    max_iter: int
    class_weight: str | None
    label_order: List[str]
    lowercase: bool


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_csv(path: str) -> Tuple[List[str], List[str]]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Training data not found: {path}")

    texts: List[str] = []
    labels: List[str] = []

    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if "text" not in reader.fieldnames or "label" not in reader.fieldnames:
            raise ValueError("CSV must contain headers: text,label")

        for row in reader:
            t = (row.get("text") or "").strip()
            l = (row.get("label") or "").strip()
            if not t or not l:
                continue
            texts.append(t)
            labels.append(l)

    if len(texts) < 20:
        raise ValueError(f"Too few training rows after cleaning: {len(texts)}")

    return texts, labels


def _validate_labels(labels: List[str], label_order: List[str]) -> None:
    allowed = set(label_order)
    seen = set(labels)
    unknown = sorted(seen - allowed)
    missing = sorted(allowed - seen)

    if unknown:
        raise ValueError(f"Found unexpected labels in data: {unknown}. Allowed: {sorted(allowed)}")
    if missing:
        raise ValueError(f"Missing labels in data: {missing}. Present: {sorted(seen)}")


def _build_vectorizer(cfg: TrainConfig) -> TfidfVectorizer:
    return TfidfVectorizer(
        lowercase=cfg.lowercase,
        ngram_range=(cfg.ngram_min, cfg.ngram_max),
        min_df=cfg.min_df,
        max_df=cfg.max_df,
        max_features=cfg.max_features,
        strip_accents="unicode",
        sublinear_tf=True,
    )


def _build_model(cfg: TrainConfig) -> LogisticRegression:
    # lbfgs with multinomial is the default from sklearn 1.5+; random_state for reproducibility
    return LogisticRegression(
        C=cfg.C,
        max_iter=cfg.max_iter,
        solver="lbfgs",
        class_weight=cfg.class_weight,
        n_jobs=None,
        random_state=cfg.random_state,
    )


def _save_misclassified(
    path: str,
    X_text: List[str],
    y_true: np.ndarray,
    y_pred: np.ndarray,
    probs: np.ndarray,
    labels_order: List[str],
) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["text", "true_label", "pred_label", "pred_confidence", "probs_json"])
        for text, t, p, pr in zip(X_text, y_true, y_pred, probs):
            if t == p:
                continue
            conf = float(np.max(pr))
            probs_map = {labels_order[i]: float(pr[i]) for i in range(len(labels_order))}
            writer.writerow([text, t, p, f"{conf:.6f}", json.dumps(probs_map, ensure_ascii=False)])


def train(cfg: TrainConfig) -> Dict:
    texts, labels = _read_csv(cfg.data_path)
    _validate_labels(labels, cfg.label_order)

    X_train_text, X_val_text, y_train, y_val = train_test_split(
        texts,
        labels,
        test_size=cfg.test_size,
        random_state=cfg.random_state,
        stratify=labels,
    )

    vectorizer = _build_vectorizer(cfg)
    X_train = vectorizer.fit_transform(X_train_text)
    X_val = vectorizer.transform(X_val_text)

    model = _build_model(cfg)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_val)
    acc = float(accuracy_score(y_val, y_pred))

    # Confusion matrix in stable label order for easy reading
    cm = confusion_matrix(y_val, y_pred, labels=cfg.label_order).tolist()

    report = classification_report(
        y_val,
        y_pred,
        labels=cfg.label_order,
        output_dict=True,
        zero_division=0,
    )

    # Probabilities for misclassified export + later threshold tuning
    probs = model.predict_proba(X_val)

    if cfg.misclassified_path:
        _save_misclassified(
            cfg.misclassified_path, X_val_text, np.array(y_val), np.array(y_pred), probs, cfg.label_order
        )

    artifact = {
        "vectorizer": vectorizer,
        "model": model,
        "labels": cfg.label_order,
        "meta": {
            "created_utc": _utc_now_iso(),
            "data_path": os.path.basename(cfg.data_path),
            "rows_total": len(texts),
            "rows_train": len(X_train_text),
            "rows_val": len(X_val_text),
            "random_state": cfg.random_state,
            "test_size": cfg.test_size,
            "vectorizer": {
                "ngram_range": [cfg.ngram_min, cfg.ngram_max],
                "min_df": cfg.min_df,
                "max_df": cfg.max_df,
                "max_features": cfg.max_features,
                "lowercase": cfg.lowercase,
                "sublinear_tf": True,
            },
            "model": {
                "type": "LogisticRegression",
                "C": cfg.C,
                "max_iter": cfg.max_iter,
                "solver": "lbfgs",
                "class_weight": cfg.class_weight,
            },
            "metrics": {
                "accuracy": acc,
                "confusion_matrix": cm,
                "classification_report": report,
            },
        },
    }

    return artifact


def parse_args(argv: List[str]) -> TrainConfig:
    p = argparse.ArgumentParser(description="Train TF-IDF + LogisticRegression intent router model.")
    p.add_argument("--data", default="./train.csv", help="Path to CSV with columns text,label")
    p.add_argument("--out", default="./model.joblib", help="Output model artifact path")
    p.add_argument("--metrics", default="./metrics.json", help="Output metrics JSON path")
    p.add_argument("--misclassified", default="./misclassified.csv", help="Output misclassified CSV path (optional)")
    p.add_argument("--no-misclassified", action="store_true", help="Disable misclassified export")

    p.add_argument("--test-size", type=float, default=0.2, help="Validation split size")
    p.add_argument("--random-state", type=int, default=42, help="Random seed for split")

    p.add_argument("--min-df", type=int, default=2, help="Min document frequency for TF-IDF vocab")
    p.add_argument("--max-df", type=float, default=0.95, help="Max document frequency for TF-IDF vocab")
    p.add_argument("--ngram-min", type=int, default=1, help="Min n-gram size")
    p.add_argument("--ngram-max", type=int, default=2, help="Max n-gram size")
    p.add_argument("--max-features", type=int, default=50000, help="Max TF-IDF features (0 disables)")
    p.add_argument("--no-lowercase", action="store_true", help="Disable lowercasing in vectorizer")

    p.add_argument("--C", type=float, default=3.0, help="Inverse regularization strength")
    p.add_argument("--max-iter", type=int, default=2000, help="Max iterations for LogisticRegression")
    p.add_argument(
        "--class-weight",
        choices=["balanced", "none"],
        default="none",
        help="Use class_weight=balanced or none",
    )

    p.add_argument(
        "--label-order",
        default=",".join(DEFAULT_LABEL_ORDER),
        help="Comma-separated label order (must match dataset labels)",
    )

    a = p.parse_args(argv)

    max_features = None if a.max_features == 0 else int(a.max_features)
    class_weight = None if a.class_weight == "none" else "balanced"
    misclassified_path = None if a.no_misclassified else a.misclassified

    return TrainConfig(
        data_path=a.data,
        out_path=a.out,
        metrics_path=a.metrics,
        misclassified_path=misclassified_path,
        test_size=a.test_size,
        random_state=a.random_state,
        min_df=a.min_df,
        max_df=a.max_df,
        ngram_min=a.ngram_min,
        ngram_max=a.ngram_max,
        max_features=max_features,
        C=a.C,
        max_iter=a.max_iter,
        class_weight=class_weight,
        label_order=[x.strip() for x in a.label_order.split(",") if x.strip()],
        lowercase=not a.no_lowercase,
    )


def main(argv: List[str]) -> int:
    cfg = parse_args(argv)

    os.makedirs(os.path.dirname(cfg.out_path) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(cfg.metrics_path) or ".", exist_ok=True)
    if cfg.misclassified_path:
        os.makedirs(os.path.dirname(cfg.misclassified_path) or ".", exist_ok=True)

    artifact = train(cfg)

    joblib.dump(artifact, cfg.out_path)

    metrics = artifact["meta"]["metrics"]
    with open(cfg.metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    acc = metrics["accuracy"]
    rows = artifact["meta"]["rows_total"]
    print(f"trained model saved: {cfg.out_path}")
    print(f"metrics saved: {cfg.metrics_path}")
    if cfg.misclassified_path:
        print(f"misclassified saved: {cfg.misclassified_path}")
    print(f"rows={rows} accuracy={acc:.4f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))