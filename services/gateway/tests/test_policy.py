"""Unit tests for gateway apply_policy and _validate_job_id."""

from __future__ import annotations

import pytest

from app.main import apply_policy, _validate_job_id


class TestApplyPolicy:
    def test_model_unknown_returns_unknown(self):
        route, reason = apply_policy("unknown", {"search": 0.1, "unknown": 0.7})
        assert route == "unknown"
        assert reason == "model_unknown"

    def test_high_confidence_returns_route(self):
        route, reason = apply_policy(
            "search",
            {"search": 0.85, "image": 0.05, "ops": 0.05, "unknown": 0.05},
        )
        assert route == "search"
        assert reason is None

    def test_low_confidence_returns_unknown(self):
        route, reason = apply_policy(
            "search",
            {"search": 0.40, "image": 0.25, "ops": 0.25, "unknown": 0.10},
        )
        assert route == "unknown"
        assert "low_confidence" in reason

    def test_low_margin_returns_unknown(self):
        route, reason = apply_policy(
            "search",
            {"search": 0.56, "image": 0.52, "ops": 0.00, "unknown": 0.00},
        )
        assert route == "unknown"
        assert "low_margin" in reason

    def test_exact_threshold_passes(self):
        route, reason = apply_policy(
            "search",
            {"search": 0.55, "image": 0.44, "ops": 0.01, "unknown": 0.00},
        )
        assert route == "search"
        assert reason is None

    def test_exact_margin_passes(self):
        route, reason = apply_policy(
            "search",
            {"search": 0.56, "image": 0.46, "ops": 0.00, "unknown": 0.00},
        )
        assert route == "search"
        assert reason is None

    def test_no_non_unknown_routes(self):
        route, reason = apply_policy(
            "search",
            {"unknown": 1.0},
        )
        assert route == "unknown"
        assert reason == "no_routes"

    def test_empty_probabilities(self):
        route, reason = apply_policy("search", {})
        assert route == "unknown"
        assert reason == "no_routes"

    def test_single_route_above_threshold(self):
        route, reason = apply_policy(
            "ops",
            {"ops": 0.88, "unknown": 0.12},
        )
        assert route == "ops"
        assert reason is None

    def test_best_route_differs_from_raw(self):
        """When probabilities show a different best route than raw_route,
        apply_policy uses probabilities (best_route from sorted)."""
        route, reason = apply_policy(
            "image",
            {"search": 0.80, "image": 0.10, "ops": 0.05, "unknown": 0.05},
        )
        assert route == "search"
        assert reason is None


class TestValidateJobId:
    def test_valid_uuid(self):
        job_id = "550e8400-e29b-41d4-a716-446655440000"
        assert _validate_job_id(job_id) == job_id

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Invalid job_id format"):
            _validate_job_id("not-a-uuid")

    def test_path_traversal_raises(self):
        with pytest.raises(ValueError, match="Invalid job_id format"):
            _validate_job_id("../../etc/passwd")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="Invalid job_id format"):
            _validate_job_id("")
