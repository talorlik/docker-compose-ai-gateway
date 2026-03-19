"""Unit tests for RefineConfig."""

from __future__ import annotations

import pytest

from import_training_api import training_api_imported

with training_api_imported():
    from app.refine.config import RefineConfig, _get_float, _get_int, _get_str


class TestGetInt:
    def test_returns_default_when_env_missing(self, monkeypatch):
        monkeypatch.delenv("TEST_INT", raising=False)
        assert _get_int("TEST_INT", 42) == 42

    def test_returns_env_value(self, monkeypatch):
        monkeypatch.setenv("TEST_INT", "100")
        assert _get_int("TEST_INT", 42) == 100

    def test_returns_default_on_invalid(self, monkeypatch):
        monkeypatch.setenv("TEST_INT", "not_a_number")
        assert _get_int("TEST_INT", 42) == 42

    def test_applies_min_value(self, monkeypatch):
        monkeypatch.setenv("TEST_INT", "0")
        assert _get_int("TEST_INT", 42, min_value=5) == 5

    def test_empty_string_returns_default(self, monkeypatch):
        monkeypatch.setenv("TEST_INT", "  ")
        assert _get_int("TEST_INT", 42) == 42


class TestGetFloat:
    def test_returns_default_when_env_missing(self, monkeypatch):
        monkeypatch.delenv("TEST_FLOAT", raising=False)
        assert _get_float("TEST_FLOAT", 0.5) == 0.5

    def test_returns_env_value(self, monkeypatch):
        monkeypatch.setenv("TEST_FLOAT", "0.75")
        assert _get_float("TEST_FLOAT", 0.5) == 0.75

    def test_applies_min_value(self, monkeypatch):
        monkeypatch.setenv("TEST_FLOAT", "-1.0")
        assert _get_float("TEST_FLOAT", 0.5, min_value=0.0) == 0.0


class TestGetStr:
    def test_returns_default_when_env_missing(self, monkeypatch):
        monkeypatch.delenv("TEST_STR", raising=False)
        assert _get_str("TEST_STR", "default") == "default"

    def test_returns_env_value(self, monkeypatch):
        monkeypatch.setenv("TEST_STR", "custom")
        assert _get_str("TEST_STR", "default") == "custom"

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("TEST_STR", "  trimmed  ")
        assert _get_str("TEST_STR", "default") == "trimmed"


class TestRefineConfig:
    def test_from_env_defaults(self, monkeypatch, tmp_path):
        monkeypatch.delenv("OLLAMA_URLS", raising=False)
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        monkeypatch.delenv("REFINER_RELABEL_BATCH_SIZE", raising=False)
        cfg = RefineConfig.from_env(str(tmp_path))
        assert cfg.relabel_batch_size == 25
        assert cfg.augment_n_per_label == 3
        assert cfg.ollama_model == "phi3:mini"
        assert cfg.ollama_urls == ["http://ollama:11434"]

    def test_from_env_with_ollama_urls(self, monkeypatch, tmp_path):
        monkeypatch.setenv(
            "OLLAMA_URLS", "http://host1:11434,http://host2:11434"
        )
        cfg = RefineConfig.from_env(str(tmp_path))
        assert cfg.ollama_urls == ["http://host1:11434", "http://host2:11434"]

    def test_from_env_custom_batch_size(self, monkeypatch, tmp_path):
        monkeypatch.setenv("REFINER_RELABEL_BATCH_SIZE", "50")
        monkeypatch.delenv("OLLAMA_URLS", raising=False)
        cfg = RefineConfig.from_env(str(tmp_path))
        assert cfg.relabel_batch_size == 50

    def test_run_dir(self, monkeypatch, tmp_path):
        monkeypatch.delenv("OLLAMA_URLS", raising=False)
        cfg = RefineConfig.from_env(str(tmp_path))
        run_id = "550e8400-e29b-41d4-a716-446655440000"
        rd = cfg.run_dir(run_id)
        assert str(rd).endswith(run_id)

    def test_validate_run_id_valid(self):
        rid = "550e8400-e29b-41d4-a716-446655440000"
        assert RefineConfig.validate_run_id(rid) == rid

    def test_validate_run_id_invalid(self):
        with pytest.raises(ValueError, match="Invalid run_id"):
            RefineConfig.validate_run_id("../../../etc/passwd")

    def test_ensure_run_dir_creates_directory(self, monkeypatch, tmp_path):
        monkeypatch.delenv("OLLAMA_URLS", raising=False)
        cfg = RefineConfig.from_env(str(tmp_path))
        run_id = cfg.new_run_id()
        path = cfg.ensure_run_dir(run_id)
        assert path.exists()

    def test_artifact_paths(self, monkeypatch, tmp_path):
        monkeypatch.delenv("OLLAMA_URLS", raising=False)
        cfg = RefineConfig.from_env(str(tmp_path))
        run_id = "550e8400-e29b-41d4-a716-446655440000"

        assert cfg.metrics_before_path(run_id).name == "metrics_before.json"
        assert cfg.relabel_merged_csv(run_id).name == "proposed_relabels.csv"
        assert cfg.relabel_candidate_csv(run_id).name == "train_relabel_candidate.csv"
        assert cfg.augment_merged_csv(run_id).name == "proposed_examples.csv"
        assert cfg.augment_candidate_csv(run_id).name == "train_augment_candidate.csv"

    def test_events_channel(self, monkeypatch, tmp_path):
        monkeypatch.delenv("OLLAMA_URLS", raising=False)
        cfg = RefineConfig.from_env(str(tmp_path))
        run_id = "550e8400-e29b-41d4-a716-446655440000"
        ch = cfg.events_channel(run_id)
        assert ch == f"refine:events:{run_id}"

    def test_relabel_min_confidence_clamped(self, monkeypatch, tmp_path):
        monkeypatch.setenv("REFINER_RELABEL_MIN_CONFIDENCE", "2.0")
        monkeypatch.delenv("OLLAMA_URLS", raising=False)
        cfg = RefineConfig.from_env(str(tmp_path))
        assert cfg.relabel_min_confidence == 1.0

    def test_structured_output_parsing(self, monkeypatch, tmp_path):
        monkeypatch.delenv("OLLAMA_URLS", raising=False)

        for val in ("true", "1", "yes", "on"):
            monkeypatch.setenv("REFINER_STRUCTURED_OUTPUT_ENABLED", val)
            cfg = RefineConfig.from_env(str(tmp_path))
            assert cfg.structured_output_enabled is True

        for val in ("false", "0", "no", "off"):
            monkeypatch.setenv("REFINER_STRUCTURED_OUTPUT_ENABLED", val)
            cfg = RefineConfig.from_env(str(tmp_path))
            assert cfg.structured_output_enabled is False
