from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _read_metrics(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def train_candidate(
    *,
    compose_working_dir: str,
    candidate_csv: Path,
    metrics_out: Path,
    model_out: Path | None = None,
    timeout_seconds: int = 3600,
) -> dict[str, Any]:
    """Run trainer/train.py on a specific candidate CSV and return metrics dict."""
    train_py = Path(compose_working_dir) / "services" / "trainer" / "train.py"
    if not train_py.exists():
        raise RuntimeError(f"Trainer script not found: {train_py}")
    if not candidate_csv.exists():
        raise RuntimeError(f"Candidate CSV not found: {candidate_csv}")

    metrics_out.parent.mkdir(parents=True, exist_ok=True)
    if model_out is not None:
        model_out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(train_py),
        "--data",
        str(candidate_csv),
        "--metrics",
        str(metrics_out),
        "--no-misclassified",
    ]
    if model_out is not None:
        cmd.extend(["--out", str(model_out)])
    else:
        # trainer requires --out, keep it in run dir even if unused
        tmp_model = metrics_out.parent / "model_candidate.joblib"
        cmd.extend(["--out", str(tmp_model)])

    result = subprocess.run(
        cmd,
        cwd=compose_working_dir,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if result.returncode != 0:
        msg = result.stderr or result.stdout or f"exit code {result.returncode}"
        raise RuntimeError(f"Trainer failed: {msg.strip()}")

    return _read_metrics(metrics_out)
