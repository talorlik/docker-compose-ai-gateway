"""Run train/refine/promote by executing trainer/refiner Python code (no Docker).

Per TRAIN_AND_REFINE_GUI_PAGES_TECH §2, §4: background tasks run the trainer and
refiner as Python scripts (subprocess) and read artifacts from MODEL_ARTIFACTS_PATH.
Bash scripts (e.g. scripts/promote.sh) run shell commands; this module runs Python.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

RUN_TRAIN_TIMEOUT_SECONDS = int(os.environ.get("RUN_TRAIN_TIMEOUT_SECONDS", "3600"))
RUN_REFINE_TIMEOUT_SECONDS = int(os.environ.get("RUN_REFINE_TIMEOUT_SECONDS", "600"))

# Allowed base paths for env-derived dirs (volume mounts); plus cwd for local CLI.
_ALLOWED_PATH_PREFIXES = ("/model", "/promote_target", "/workspace")


def _validate_dir_under_allowed(path: str) -> str:
    """Resolve path to realpath and ensure it is under an allowed base. Raises if not."""
    real = os.path.realpath(path)
    if not os.path.isdir(real):
        raise ValueError(f"Not a directory: {path}")
    cwd = os.path.realpath(os.getcwd())
    allowed = list(_ALLOWED_PATH_PREFIXES) + [cwd]
    if not any(
        real == base or real.startswith(base + os.sep) for base in allowed
    ):
        raise ValueError(f"Path not under allowed base: {real}")
    return real


def _safe_file_under_dir(base_dir: str, filename: str) -> str:
    """Return a safe file path constrained to base_dir."""
    base = Path(base_dir).resolve()
    target = (base / filename).resolve()
    if target.parent != base:
        raise ValueError(f"Unsafe file path outside base directory: {target}")
    return str(target)


def run_train(
    compose_working_dir: str | None = None,
    model_artifacts_path: str | None = None,
    promote_target_path: str | None = None,
    timeout_seconds: int = RUN_TRAIN_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run trainer by executing its Python script; on success read metrics and misclassified.

    Args:
        compose_working_dir: Repo root (COMPOSE_WORKING_DIR); used to find
            services/trainer/train.py.
        model_artifacts_path: Where to write model.joblib, metrics.json,
            misclassified.csv (MODEL_ARTIFACTS_PATH or /model).
        promote_target_path: Directory containing train.csv (PROMOTE_TARGET_PATH).
        timeout_seconds: Max time for the run (default 1h).

    Returns:
        Dict with keys: accuracy, classification_report, confusion_matrix,
        misclassified.

    Raises:
        RuntimeError: When trainer script fails or artifacts cannot be read.
    """
    work_dir = _validate_dir_under_allowed(
        compose_working_dir or os.environ.get("COMPOSE_WORKING_DIR", ".")
    )
    artifacts_dir = _validate_dir_under_allowed(
        model_artifacts_path or os.environ.get("MODEL_ARTIFACTS_PATH", "/model")
    )
    promote_dir = _validate_dir_under_allowed(
        promote_target_path or os.environ.get("PROMOTE_TARGET_PATH", "/promote_target")
    )
    train_csv = _safe_file_under_dir(promote_dir, "train.csv")
    train_py = str((Path(work_dir) / "services" / "trainer" / "train.py").resolve())
    if not os.path.isfile(train_py):
        raise RuntimeError(f"Trainer script not found: {train_py}")
    if not os.path.isfile(train_csv):
        raise RuntimeError(f"Training data not found: {train_csv}")

    cmd = [
        sys.executable,
        train_py,
        "--data",
        train_csv,
        "--out",
        _safe_file_under_dir(artifacts_dir, "model.joblib"),
        "--metrics",
        _safe_file_under_dir(artifacts_dir, "metrics.json"),
        "--misclassified",
        _safe_file_under_dir(artifacts_dir, "misclassified.csv"),
    ]

    result = subprocess.run(
        cmd,
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )

    if result.returncode != 0:
        msg = result.stderr or result.stdout or f"exit code {result.returncode}"
        raise RuntimeError(f"Trainer failed: {msg.strip()}")

    return _read_train_artifacts(artifacts_dir)


def _read_train_artifacts(artifacts_dir: str) -> dict[str, Any]:
    """Read metrics.json and misclassified.csv from artifacts dir."""
    metrics_path = _safe_file_under_dir(artifacts_dir, "metrics.json")
    if not os.path.exists(metrics_path):
        raise RuntimeError(f"Artifacts missing: {metrics_path}")

    with open(metrics_path, encoding="utf-8") as f:
        metrics = json.load(f)

    accuracy = metrics.get("accuracy")
    classification_report = metrics.get("classification_report", {})
    confusion_matrix = metrics.get("confusion_matrix", [])

    misclassified_path = _safe_file_under_dir(artifacts_dir, "misclassified.csv")
    misclassified: list[dict[str, Any]] = []
    if os.path.exists(misclassified_path):
        with open(misclassified_path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                misclassified.append(dict(row))

    return {
        "accuracy": accuracy,
        "classification_report": classification_report,
        "confusion_matrix": confusion_matrix,
        "misclassified": misclassified,
    }


def get_last_train_result(
    model_artifacts_path: str | None = None,
) -> dict[str, Any] | None:
    """Read last train run from artifacts dir (metrics.json + misclassified.csv).

    Returns same shape as run_train() result, or None if metrics.json absent.
    Used by GET /train/last. Fixed path: MODEL_ARTIFACTS_PATH or /model.
    """
    artifacts_dir = model_artifacts_path or os.environ.get("MODEL_ARTIFACTS_PATH", "/model")
    metrics_path = _safe_file_under_dir(artifacts_dir, "metrics.json")
    if not os.path.exists(metrics_path):
        return None
    try:
        return _read_train_artifacts(artifacts_dir)
    except (OSError, json.JSONDecodeError):
        return None


def _refiner_error_short_message(full_msg: str) -> str:
    """Return a short user-facing message for refiner failures; full details go to logs."""
    lower = full_msg.lower()
    if "ollama" in lower and ("unreachable" in lower or "resolve" in lower or "connection" in lower):
        return "Refinement failed: Ollama is not available. Ensure the stack is running with Ollama."
    if "not found" in lower and ("train" in lower or "misclassified" in lower):
        return "Refinement failed: Required data files (train.csv or misclassified.csv) not found."
    if "refiner failed:" in lower:
        first_line = full_msg.strip().split("\n")[0].strip()
        if len(first_line) > 120:
            return first_line[:117] + "..."
        return first_line
    return "Refinement failed. Check server logs for details."


def _parse_refiner_progress(line: str) -> Optional[dict]:
    """Parse a JSON log line from the refiner and return a progress dict, or None."""
    try:
        data = json.loads(line.strip())
    except (json.JSONDecodeError, ValueError):
        return None
    msg = data.get("message", "")
    if msg == "processing row":
        idx = data.get("idx", "?")
        total = data.get("total", "?")
        return {"step": "relabel", "detail": f"Processing row {idx}/{total}"}
    if msg == "augmenting label":
        label = data.get("label", "?")
        return {"step": "augment", "detail": f"Augmenting label: {label}"}
    if msg == "augmentation complete":
        label = data.get("label", "?")
        collected = data.get("collected", 0)
        return {"step": "augment", "detail": f"Augmented {label}: {collected} examples"}
    if msg == "augmentation skipped":
        label = data.get("label", "?")
        count = data.get("current_count", "?")
        return {"step": "augment", "detail": f"Skipped {label} ({count} examples already)"}
    if msg == "ingest complete":
        rows = data.get("misclassified_rows", "?")
        return {"step": "ingest", "detail": f"Loaded {rows} misclassified rows"}
    if msg == "refinement complete":
        return {"step": "done", "detail": "Refinement complete, retraining candidate..."}
    return None


def run_refine(
    compose_working_dir: str | None = None,
    model_artifacts_path: str | None = None,
    promote_target_path: str | None = None,
    timeout_seconds: int = RUN_REFINE_TIMEOUT_SECONDS,
    train_candidate_sample_size: int = 100,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """Run refiner by executing its Python script; on success read report, CSVs, run trainer for metrics_after.

    Args:
        compose_working_dir: Repo root (COMPOSE_WORKING_DIR).
        model_artifacts_path: Artifacts dir (refiner reads/writes here via REFINER_DATA_DIR).
        promote_target_path: Directory containing train.csv (REFINER_TRAIN_PATH).
        timeout_seconds: Max time for refiner run (default 1h).
        train_candidate_sample_size: Max rows to return in train_candidate_sample.
        progress_callback: Optional callable invoked with a progress detail string
            as the refiner runs. Used to publish SSE progress events.

    Returns:
        Dict with report, metrics_before, metrics_after, proposed_relabels,
        proposed_examples, train_candidate_sample.

    Raises:
        RuntimeError: When refiner or trainer run fails.
    """
    work_dir = _validate_dir_under_allowed(
        compose_working_dir or os.environ.get("COMPOSE_WORKING_DIR", ".")
    )
    artifacts_dir = _validate_dir_under_allowed(
        model_artifacts_path or os.environ.get("MODEL_ARTIFACTS_PATH", "/model")
    )
    promote_dir = _validate_dir_under_allowed(
        promote_target_path or os.environ.get("PROMOTE_TARGET_PATH", "/promote_target")
    )
    refiner_app = str((Path(work_dir) / "services" / "refiner" / "app.py").resolve())
    refiner_cwd = str((Path(work_dir) / "services" / "refiner").resolve())
    if not os.path.isfile(refiner_app):
        raise RuntimeError(f"Refiner script not found: {refiner_app}")

    _ALLOWED_ENV_KEYS = {
        "PATH", "HOME", "PYTHONDONTWRITEBYTECODE", "PYTHONUNBUFFERED",
        "OLLAMA_HOST", "OLLAMA_MODEL", "REFINER_LIMIT",
        "REFINER_BANNED_PATTERNS", "REFINER_DATA_DIR", "REFINER_TRAIN_PATH",
        "LOG_LEVEL",
    }
    env = {k: v for k, v in os.environ.items() if k in _ALLOWED_ENV_KEYS}
    env["REFINER_DATA_DIR"] = artifacts_dir
    env["REFINER_TRAIN_PATH"] = _safe_file_under_dir(promote_dir, "train.csv")
    refiner_limit = os.environ.get("REFINER_LIMIT")
    if refiner_limit is not None and str(refiner_limit).strip() != "":
        env["REFINER_LIMIT"] = str(refiner_limit).strip()

    proc = subprocess.Popen(
        [sys.executable, refiner_app],
        cwd=refiner_cwd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )

    stderr_lines: list[str] = []
    try:
        if proc.stderr is None:
            raise RuntimeError("Failed to capture refiner stderr")
        for line in proc.stderr:
            stderr_lines.append(line)
            if progress_callback:
                progress = _parse_refiner_progress(line)
                if progress:
                    progress_callback(progress["detail"])
        proc.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise
    except Exception:
        proc.kill()
        proc.wait()
        raise

    if proc.returncode != 0:
        msg = "".join(stderr_lines) or f"exit code {proc.returncode}"
        full_msg = msg.strip()
        short_msg = _refiner_error_short_message(full_msg)
        err = RuntimeError(full_msg)
        err.short_message = short_msg  # type: ignore[attr-defined]
        raise err

    if progress_callback:
        progress_callback("Retraining on candidate dataset...")

    report, metrics_before, proposed_relabels, proposed_examples, train_candidate_sample = (
        _read_refine_artifacts(artifacts_dir, train_candidate_sample_size)
    )

    _run_trainer_on_candidate(
        work_dir, artifacts_dir, promote_dir, timeout_seconds
    )
    metrics_after = _read_metrics_only(_safe_file_under_dir(artifacts_dir, "metrics_candidate.json"))

    return {
        "report": report,
        "metrics_before": metrics_before,
        "metrics_after": metrics_after,
        "proposed_relabels": proposed_relabels,
        "proposed_examples": proposed_examples,
        "train_candidate_sample": train_candidate_sample,
    }


def _read_refine_artifacts(
    artifacts_dir: str,
    train_candidate_sample_size: int,
) -> tuple[dict[str, Any], dict[str, Any], list[dict], list[dict], list[dict]]:
    """Read refinement_report.json, CSVs, metrics_before; sample of train_candidate."""
    report_path = _safe_file_under_dir(artifacts_dir, "refinement_report.json")
    if not os.path.exists(report_path):
        raise RuntimeError(f"Refiner artifacts missing: {report_path}")

    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    metrics_before = _read_metrics_only(_safe_file_under_dir(artifacts_dir, "metrics_before.json"))

    def _read_csv_rows(path: str) -> list[dict[str, Any]]:
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    proposed_relabels = _read_csv_rows(_safe_file_under_dir(artifacts_dir, "proposed_relabels.csv"))
    proposed_examples = _read_csv_rows(_safe_file_under_dir(artifacts_dir, "proposed_examples.csv"))
    train_candidate_path = _safe_file_under_dir(artifacts_dir, "train_candidate.csv")
    all_candidate = _read_csv_rows(train_candidate_path)
    train_candidate_sample = all_candidate[:train_candidate_sample_size] if all_candidate else []

    return report, metrics_before, proposed_relabels, proposed_examples, train_candidate_sample


def get_last_refine_result(
    model_artifacts_path: str | None = None,
    train_candidate_sample_size: int = 100,
) -> dict[str, Any] | None:
    """Read last refine run from artifacts dir (refinement_report.json + CSVs + metrics).

    Returns same shape as run_refine() result, or None if refinement_report.json
    absent. Used by GET /refine/last.
    """
    artifacts_dir = model_artifacts_path or os.environ.get("MODEL_ARTIFACTS_PATH", "/model")
    report_path = _safe_file_under_dir(artifacts_dir, "refinement_report.json")
    if not os.path.exists(report_path):
        return None
    try:
        report, metrics_before, proposed_relabels, proposed_examples, train_candidate_sample = (
            _read_refine_artifacts(artifacts_dir, train_candidate_sample_size)
        )
    except (OSError, json.JSONDecodeError, RuntimeError):
        return None
    metrics_after = _read_metrics_only(_safe_file_under_dir(artifacts_dir, "metrics_candidate.json"))
    return {
        "report": report,
        "metrics_before": metrics_before,
        "metrics_after": metrics_after,
        "proposed_relabels": proposed_relabels,
        "proposed_examples": proposed_examples,
        "train_candidate_sample": train_candidate_sample,
    }


def _read_metrics_only(path: str) -> dict[str, Any]:
    """Read a metrics JSON file; return empty dict if missing or invalid."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _per_label_recall_delta(
    metrics_before: dict[str, Any], metrics_after: dict[str, Any]
) -> dict[str, dict[str, float | None]]:
    """Compare per-label recall between two sklearn classification_report payloads."""
    rb = metrics_before.get("classification_report") or {}
    ra = metrics_after.get("classification_report") or {}
    skip = {"accuracy", "macro avg", "weighted avg"}
    labels = (
        set(rb) | set(ra)
    ) - skip
    out: dict[str, dict[str, float | None]] = {}
    for lab in sorted(labels):
        b_ent = rb.get(lab) if isinstance(rb.get(lab), dict) else None
        a_ent = ra.get(lab) if isinstance(ra.get(lab), dict) else None
        b_rec = b_ent.get("recall") if b_ent else None
        a_rec = a_ent.get("recall") if a_ent else None
        try:
            bf = float(b_rec) if b_rec is not None else None
        except (TypeError, ValueError):
            bf = None
        try:
            af = float(a_rec) if a_rec is not None else None
        except (TypeError, ValueError):
            af = None
        delta = None if bf is None or af is None else af - bf
        out[lab] = {
            "recall_before": bf,
            "recall_after": af,
            "delta": delta,
        }
    return out


def _run_trainer_on_candidate(
    work_dir: str,
    artifacts_dir: str,
    _promote_dir: str,
    timeout_seconds: int,
) -> None:
    """Run trainer Python script with train_candidate.csv to produce metrics_candidate.json and model_candidate.joblib."""
    candidate_csv = _safe_file_under_dir(artifacts_dir, "train_candidate.csv")
    if not os.path.isfile(candidate_csv):
        raise RuntimeError(f"train_candidate.csv not found: {candidate_csv}")
    train_py = str((Path(work_dir) / "services" / "trainer" / "train.py").resolve())
    if not os.path.isfile(train_py):
        raise RuntimeError(f"Trainer script not found: {train_py}")

    cmd = [
        sys.executable,
        train_py,
        "--data",
        candidate_csv,
        "--out",
        _safe_file_under_dir(artifacts_dir, "model_candidate.joblib"),
        "--metrics",
        _safe_file_under_dir(artifacts_dir, "metrics_candidate.json"),
        "--no-misclassified",
    ]

    result = subprocess.run(
        cmd,
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )

    if result.returncode != 0:
        msg = result.stderr or result.stdout or f"exit code {result.returncode}"
        raise RuntimeError(f"Trainer on candidate failed: {msg.strip()}")


def _find_latest_run_with_subdir(
    artifacts_dir: str,
    subdir: str,
    marker_file: str,
) -> tuple[str, Path] | None:
    """Find the most recent refine run that contains *subdir/marker_file*.

    Scans ``{artifacts_dir}/refine_runs/*/`` directories, filters those that
    have the expected artifact, and returns ``(run_id, run_path)`` for the
    newest (by mtime) match - or ``None`` if nothing qualifies.
    """
    runs_root = Path(artifacts_dir) / "refine_runs"
    if not runs_root.is_dir():
        return None

    candidates: list[tuple[float, str, Path]] = []
    for entry in runs_root.iterdir():
        if not entry.is_dir():
            continue
        marker = entry / subdir / marker_file
        if marker.exists():
            candidates.append((entry.stat().st_mtime, entry.name, entry))

    if not candidates:
        return None

    candidates.sort(key=lambda c: c[0], reverse=True)
    _, run_id, run_path = candidates[0]
    return run_id, run_path


def get_last_relabel_result(
    model_artifacts_path: str | None = None,
) -> dict[str, Any] | None:
    """Read the last relabel run from ``refine_runs/{run_id}/relabel/``.

    Returns the same shape as ``run_relabel_phase()`` or ``None`` when no
    previous relabel run is found on disk.
    """
    artifacts_dir = model_artifacts_path or os.environ.get("MODEL_ARTIFACTS_PATH", "/model")
    match = _find_latest_run_with_subdir(artifacts_dir, "relabel", "proposed_relabels.csv")
    if match is None:
        return None

    run_id, run_path = match
    try:
        relabel_dir = run_path / "relabel"

        proposed_path = relabel_dir / "proposed_relabels.csv"
        proposed_relabels: list[dict[str, Any]] = []
        if proposed_path.exists():
            with open(proposed_path, encoding="utf-8", newline="") as f:
                proposed_relabels = list(csv.DictReader(f))

        batches_dir = relabel_dir / "batches"
        batches = 0
        if batches_dir.is_dir():
            batches = len(list(batches_dir.glob("proposed_relabels.batch_*.csv")))

        candidate_path = relabel_dir / "train_relabel_candidate.csv"
        train_relabel_candidate_rows = 0
        if candidate_path.exists():
            with open(candidate_path, encoding="utf-8", newline="") as f:
                train_relabel_candidate_rows = sum(1 for _ in csv.reader(f)) - 1

        metrics_before = _read_metrics_only(str(run_path / "metrics_before.json"))
        metrics_after = _read_metrics_only(str(relabel_dir / "metrics_relabel_candidate.json"))

        return {
            "run_id": run_id,
            "batches": batches,
            "train_relabel_candidate_rows": train_relabel_candidate_rows,
            "metrics_before": metrics_before,
            "metrics_after": metrics_after,
            "proposed_relabels": proposed_relabels,
        }
    except (OSError, json.JSONDecodeError):
        return None


def get_last_augment_result(
    model_artifacts_path: str | None = None,
) -> dict[str, Any] | None:
    """Read the last augment run from ``refine_runs/{run_id}/augment/``.

    Returns the same shape as ``run_augment_phase()`` or ``None`` when no
    previous augment run is found on disk.
    """
    artifacts_dir = model_artifacts_path or os.environ.get("MODEL_ARTIFACTS_PATH", "/model")
    match = _find_latest_run_with_subdir(artifacts_dir, "augment", "proposed_examples.csv")
    if match is None:
        return None

    run_id, run_path = match
    try:
        augment_dir = run_path / "augment"

        proposed_path = augment_dir / "proposed_examples.csv"
        proposed_examples: list[dict[str, Any]] = []
        if proposed_path.exists():
            with open(proposed_path, encoding="utf-8", newline="") as f:
                proposed_examples = list(csv.DictReader(f))

        labels = list(dict.fromkeys(
            str(r.get("label", "")).strip()
            for r in proposed_examples
            if str(r.get("label", "")).strip()
        ))

        candidate_path = augment_dir / "train_augment_candidate.csv"
        train_augment_candidate_rows = 0
        if candidate_path.exists():
            with open(candidate_path, encoding="utf-8", newline="") as f:
                train_augment_candidate_rows = sum(1 for _ in csv.reader(f)) - 1

        metrics_before = _read_metrics_only(str(run_path / "metrics_before.json"))
        metrics_after = _read_metrics_only(str(augment_dir / "metrics_augment_candidate.json"))

        return {
            "run_id": run_id,
            "labels": labels,
            "train_augment_candidate_rows": train_augment_candidate_rows,
            "metrics_before": metrics_before,
            "metrics_after": metrics_after,
            "proposed_examples": proposed_examples,
        }
    except (OSError, json.JSONDecodeError):
        return None


def run_promote(
    model_artifacts_path: str | None = None,
    promote_target_path: str | None = None,
    compose_working_dir: str | None = None,
    timeout_seconds: int = RUN_TRAIN_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Require train_candidate; run trainer on candidate, compare metrics; if improved, copy to promote target.

    Args:
        model_artifacts_path: Path to volume (train_candidate.csv, metrics_before.json, etc.).
        promote_target_path: Path to directory where train.csv should be written (e.g. /promote_target).
        compose_working_dir: Repo root (COMPOSE_WORKING_DIR).
        timeout_seconds: Timeout for trainer run.

    Returns:
        Dict with promoted (bool), message (str), acc_before (float), acc_after (float),
        promote_accuracy_tolerance, used_tolerance, per_label_recall (when metrics exist).
        Caller may return 400 if train_candidate missing; 200 with promoted: false if no improvement.
    """
    artifacts_dir = _validate_dir_under_allowed(
        model_artifacts_path or os.environ.get("MODEL_ARTIFACTS_PATH", "/model")
    )
    promote_dir = _validate_dir_under_allowed(
        promote_target_path or os.environ.get("PROMOTE_TARGET_PATH", "/promote_target")
    )
    work_dir = _validate_dir_under_allowed(
        compose_working_dir or os.environ.get("COMPOSE_WORKING_DIR", ".")
    )

    candidate_path = _safe_file_under_dir(artifacts_dir, "train_candidate.csv")
    if not os.path.exists(candidate_path):
        raise FileNotFoundError(
            "train_candidate.csv not found. Run refiner first."
        )

    metrics_before = _read_metrics_only(_safe_file_under_dir(artifacts_dir, "metrics_before.json"))
    acc_before = float(metrics_before.get("accuracy") or 0.0)

    _run_trainer_on_candidate(work_dir, artifacts_dir, promote_dir, timeout_seconds)
    metrics_after_path = _safe_file_under_dir(artifacts_dir, "metrics_candidate.json")
    if not os.path.exists(metrics_after_path):
        return {
            "promoted": False,
            "message": "Trainer did not produce metrics_candidate.json.",
            "acc_before": acc_before,
            "acc_after": 0.0,
        }

    with open(metrics_after_path, encoding="utf-8") as f:
        metrics_after = json.load(f)
    acc_after = float(metrics_after.get("accuracy") or 0.0)

    tolerance = float(os.environ.get("REFINER_PROMOTE_ACCURACY_TOLERANCE", "0.01"))
    promote_ok = acc_before == 0 or acc_after >= acc_before - tolerance

    recall_comparison = _per_label_recall_delta(metrics_before, metrics_after)
    used_tolerance = (
        acc_before > 0 and acc_after < acc_before and acc_after >= acc_before - tolerance
    )
    if used_tolerance:
        logger.info(
            "Promote within accuracy tolerance: before=%.4f after=%.4f tolerance=%.4f",
            acc_before,
            acc_after,
            tolerance,
        )
        for lab, row in recall_comparison.items():
            logger.info(
                "Per-label recall %s: before=%s after=%s delta=%s",
                lab,
                row.get("recall_before"),
                row.get("recall_after"),
                row.get("delta"),
            )

    if promote_ok:
        # Promote: copy train_candidate to promote target as train.csv
        os.makedirs(promote_dir, exist_ok=True)
        dest_train = _safe_file_under_dir(promote_dir, "train.csv")
        shutil.copy2(candidate_path, dest_train)
        # Copy model_candidate to model.joblib and metrics_candidate to metrics.json in artifacts
        model_candidate = _safe_file_under_dir(artifacts_dir, "model_candidate.joblib")
        model_final = _safe_file_under_dir(artifacts_dir, "model.joblib")
        if os.path.exists(model_candidate):
            shutil.copy2(model_candidate, model_final)
        metrics_final = _safe_file_under_dir(artifacts_dir, "metrics.json")
        with open(metrics_final, "w", encoding="utf-8") as f:
            json.dump(metrics_after, f, indent=2)
        msg = f"Promoted. Accuracy {acc_before:.4f} -> {acc_after:.4f}."
        if used_tolerance:
            msg = (
                f"Promoted within tolerance ({tolerance:.4f}). "
                f"Accuracy {acc_before:.4f} -> {acc_after:.4f}."
            )
        return {
            "promoted": True,
            "message": msg,
            "acc_before": acc_before,
            "acc_after": acc_after,
            "promote_accuracy_tolerance": tolerance,
            "used_tolerance": used_tolerance,
            "per_label_recall": recall_comparison,
        }

    return {
        "promoted": False,
        "message": (
            f"Metrics did not improve ({acc_before:.4f} -> {acc_after:.4f}); "
            f"threshold with tolerance {tolerance:.4f} is {acc_before - tolerance:.4f}. "
            "Candidate discarded."
        ),
        "acc_before": acc_before,
        "acc_after": acc_after,
        "promote_accuracy_tolerance": tolerance,
        "used_tolerance": False,
        "per_label_recall": recall_comparison,
    }
