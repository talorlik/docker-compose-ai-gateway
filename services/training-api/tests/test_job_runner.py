"""Unit tests for job runner helper functions."""

from __future__ import annotations

import csv
import json
import os

import pytest

from import_training_api import training_api_imported

with training_api_imported():
    from app.jobs.runner import (
        _read_metrics_only,
        _read_train_artifacts,
        _refiner_error_short_message,
        _safe_file_under_dir,
        _validate_dir_under_allowed,
        get_last_train_result,
    )


class TestSafeFileUnderDir:
    def test_valid_path(self, tmp_path):
        result = _safe_file_under_dir(str(tmp_path), "test.csv")
        assert result.endswith("test.csv")
        assert str(tmp_path) in result

    def test_traversal_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="Unsafe file path"):
            _safe_file_under_dir(str(tmp_path), "../etc/passwd")

    def test_nested_path_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="Unsafe file path"):
            _safe_file_under_dir(str(tmp_path), "subdir/file.csv")


class TestValidateDirUnderAllowed:
    def test_valid_dir_under_cwd(self):
        """cwd is always allowed; use a subdir of cwd for testing."""
        cwd = os.getcwd()
        result = _validate_dir_under_allowed(cwd)
        assert result == os.path.realpath(cwd)

    def test_nonexistent_dir_raises(self):
        with pytest.raises(ValueError, match="Not a directory"):
            _validate_dir_under_allowed("/nonexistent/path/xyz")


class TestReadMetricsOnly:
    def test_reads_valid_metrics(self, tmp_path):
        metrics_path = tmp_path / "metrics.json"
        metrics_path.write_text(json.dumps({"accuracy": 0.95}))
        result = _read_metrics_only(str(metrics_path))
        assert result["accuracy"] == 0.95

    def test_missing_file_returns_empty(self, tmp_path):
        result = _read_metrics_only(str(tmp_path / "nonexistent.json"))
        assert result == {}

    def test_invalid_json_returns_empty(self, tmp_path):
        bad_path = tmp_path / "bad.json"
        bad_path.write_text("not json")
        result = _read_metrics_only(str(bad_path))
        assert result == {}


class TestReadTrainArtifacts:
    def test_reads_artifacts(self, tmp_path):
        metrics = {
            "accuracy": 0.90,
            "classification_report": {"search": {"precision": 0.9}},
            "confusion_matrix": [[5, 1], [0, 4]],
        }
        (tmp_path / "metrics.json").write_text(json.dumps(metrics))

        with open(tmp_path / "misclassified.csv", "w", newline="") as f:
            w = csv.DictWriter(
                f, fieldnames=["text", "true_label", "pred_label"]
            )
            w.writeheader()
            w.writerow(
                {"text": "test", "true_label": "search", "pred_label": "ops"}
            )

        result = _read_train_artifacts(str(tmp_path))
        assert result["accuracy"] == 0.90
        assert len(result["misclassified"]) == 1
        assert result["misclassified"][0]["text"] == "test"

    def test_missing_metrics_raises(self, tmp_path):
        with pytest.raises(RuntimeError, match="Artifacts missing"):
            _read_train_artifacts(str(tmp_path))


class TestGetLastTrainResult:
    def test_returns_none_when_no_metrics(self, tmp_path):
        result = get_last_train_result(str(tmp_path))
        assert result is None

    def test_returns_result_when_metrics_exist(self, tmp_path):
        metrics = {
            "accuracy": 0.85,
            "classification_report": {},
            "confusion_matrix": [],
        }
        (tmp_path / "metrics.json").write_text(json.dumps(metrics))
        result = get_last_train_result(str(tmp_path))
        assert result is not None
        assert result["accuracy"] == 0.85


class TestRefinerErrorShortMessage:
    def test_ollama_unreachable(self):
        msg = _refiner_error_short_message("Ollama unreachable: connection refused")
        assert "Ollama" in msg and "not available" in msg

    def test_ollama_resolve(self):
        msg = _refiner_error_short_message("Failed to resolve ollama host")
        assert "Ollama" in msg

    def test_missing_data_files(self):
        msg = _refiner_error_short_message("train.csv not found at /model/train.csv")
        assert "data files" in msg.lower()

    def test_refiner_failed_prefix(self):
        msg = _refiner_error_short_message("Refiner failed: some error\nStacktrace")
        assert msg.startswith("Refiner failed:")
        assert "\n" not in msg

    def test_long_refiner_failed_truncated(self):
        long_msg = "Refiner failed: " + "x" * 200
        msg = _refiner_error_short_message(long_msg)
        assert len(msg) <= 120

    def test_generic_error(self):
        msg = _refiner_error_short_message("Something unexpected happened")
        assert "Check server logs" in msg
