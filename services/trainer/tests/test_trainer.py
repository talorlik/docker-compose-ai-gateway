"""Unit tests for trainer/train.py - model training pipeline."""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from train import (  # noqa: E402
    TrainConfig,
    _read_csv,
    _validate_labels,
    main,
    parse_args,
    train,
)


@pytest.fixture
def sample_csv(tmp_path):
    """Create a minimal training CSV with enough rows per label."""
    csv_path = tmp_path / "train.csv"
    rows = []
    for i in range(10):
        rows.append({"text": f"find information about topic {i}", "label": "search"})
        rows.append({"text": f"resize image number {i} to png", "label": "image"})
        rows.append({"text": f"kubectl get pods in cluster {i}", "label": "ops"})
        rows.append({"text": f"hello world random text {i}", "label": "unknown"})

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["text", "label"])
        w.writeheader()
        w.writerows(rows)
    return str(csv_path)


@pytest.fixture
def train_config(sample_csv, tmp_path):
    return TrainConfig(
        data_path=sample_csv,
        out_path=str(tmp_path / "model.joblib"),
        metrics_path=str(tmp_path / "metrics.json"),
        misclassified_path=str(tmp_path / "misclassified.csv"),
        test_size=0.2,
        random_state=42,
        min_df=1,
        max_df=1.0,
        ngram_min=1,
        ngram_max=2,
        max_features=5000,
        C=3.0,
        max_iter=2000,
        class_weight=None,
        label_order=["search", "image", "ops", "unknown"],
        lowercase=True,
    )


class TestReadCsv:
    def test_reads_valid_csv(self, sample_csv):
        texts, labels = _read_csv(sample_csv)
        assert len(texts) == 40
        assert len(labels) == 40
        assert set(labels) == {"search", "image", "ops", "unknown"}

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            _read_csv("/nonexistent/path.csv")

    def test_too_few_rows_raises(self, tmp_path):
        csv_path = tmp_path / "small.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["text", "label"])
            w.writeheader()
            for i in range(5):
                w.writerow({"text": f"text {i}", "label": "search"})
        with pytest.raises(ValueError, match="Too few training rows"):
            _read_csv(str(csv_path))

    def test_missing_headers_raises(self, tmp_path):
        csv_path = tmp_path / "bad_headers.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["col1", "col2"])
            w.writeheader()
            w.writerow({"col1": "a", "col2": "b"})
        with pytest.raises(ValueError, match="CSV must contain headers"):
            _read_csv(str(csv_path))

    def test_skips_empty_rows(self, tmp_path):
        csv_path = tmp_path / "with_empty.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["text", "label"])
            w.writeheader()
            for i in range(25):
                w.writerow({"text": f"text {i}", "label": "search"})
            w.writerow({"text": "", "label": "search"})
            w.writerow({"text": "text", "label": ""})
        texts, labels = _read_csv(str(csv_path))
        assert len(texts) == 25


class TestValidateLabels:
    def test_valid_labels(self):
        labels = ["search", "image", "ops", "unknown"]
        _validate_labels(labels, ["search", "image", "ops", "unknown"])

    def test_unexpected_label_raises(self):
        with pytest.raises(ValueError, match="unexpected labels"):
            _validate_labels(
                ["search", "badlabel"],
                ["search", "image", "ops", "unknown"],
            )

    def test_missing_label_raises(self):
        with pytest.raises(ValueError, match="Missing labels"):
            _validate_labels(
                ["search", "image"],
                ["search", "image", "ops", "unknown"],
            )


class TestTrain:
    def test_train_produces_artifact(self, train_config):
        artifact = train(train_config)
        assert "vectorizer" in artifact
        assert "model" in artifact
        assert "labels" in artifact
        assert "meta" in artifact
        assert "accuracy" in artifact["meta"]["metrics"]
        assert 0.0 <= artifact["meta"]["metrics"]["accuracy"] <= 1.0

    def test_train_labels_match_model_classes(self, train_config):
        artifact = train(train_config)
        assert set(artifact["labels"]) == {"search", "image", "ops", "unknown"}

    def test_train_produces_misclassified_csv(self, train_config, tmp_path):
        train(train_config)
        assert os.path.exists(train_config.misclassified_path)

    def test_train_no_misclassified(self, train_config, tmp_path):
        cfg = TrainConfig(
            data_path=train_config.data_path,
            out_path=train_config.out_path,
            metrics_path=train_config.metrics_path,
            misclassified_path=None,
            test_size=train_config.test_size,
            random_state=train_config.random_state,
            min_df=train_config.min_df,
            max_df=train_config.max_df,
            ngram_min=train_config.ngram_min,
            ngram_max=train_config.ngram_max,
            max_features=train_config.max_features,
            C=train_config.C,
            max_iter=train_config.max_iter,
            class_weight=train_config.class_weight,
            label_order=train_config.label_order,
            lowercase=train_config.lowercase,
        )
        artifact = train(cfg)
        assert artifact is not None


class TestParseArgs:
    def test_default_args(self):
        cfg = parse_args([])
        assert cfg.data_path == "./train.csv"
        assert cfg.test_size == 0.2
        assert cfg.random_state == 42

    def test_custom_args(self):
        cfg = parse_args([
            "--data", "/tmp/data.csv",
            "--out", "/tmp/model.joblib",
            "--test-size", "0.3",
            "--random-state", "123",
            "--C", "1.0",
        ])
        assert cfg.data_path == "/tmp/data.csv"
        assert cfg.test_size == 0.3
        assert cfg.random_state == 123
        assert cfg.C == 1.0

    def test_no_misclassified_flag(self):
        cfg = parse_args(["--no-misclassified"])
        assert cfg.misclassified_path is None

    def test_no_lowercase_flag(self):
        cfg = parse_args(["--no-lowercase"])
        assert cfg.lowercase is False


class TestMain:
    def test_main_end_to_end(self, sample_csv, tmp_path):
        out = str(tmp_path / "model.joblib")
        metrics = str(tmp_path / "metrics.json")
        misclassified = str(tmp_path / "misclassified.csv")
        exit_code = main([
            "--data", sample_csv,
            "--out", out,
            "--metrics", metrics,
            "--misclassified", misclassified,
            "--min-df", "1",
            "--max-df", "1.0",
        ])
        assert exit_code == 0
        assert os.path.exists(out)
        assert os.path.exists(metrics)

        with open(metrics, encoding="utf-8") as f:
            data = json.load(f)
        assert "accuracy" in data
        assert "classification_report" in data
        assert "confusion_matrix" in data
