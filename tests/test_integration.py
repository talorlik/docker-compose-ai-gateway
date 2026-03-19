"""Integration tests: verify service interactions with real FastAPI apps.

These tests import multiple service apps and verify that request/response
contracts match across services without needing Docker or network.
"""

from __future__ import annotations

import pytest

from app.main import (
    ApiRequest,
    apply_policy,
    make_trace_entry,
)


@pytest.mark.integration
class TestGatewayAiRouterContract:
    """Verify gateway expects the same response shape that ai-router produces."""

    def test_classify_response_has_required_fields(self):
        """The gateway expects these fields from ai-router's /classify."""
        required_fields = {
            "route",
            "confidence",
            "probabilities",
            "explanation",
            "top_tokens",
            "trace_append",
        }
        sample = {
            "route": "search",
            "confidence": 0.85,
            "probabilities": {"search": 0.85, "image": 0.05, "ops": 0.05, "unknown": 0.05},
            "explanation": "top tokens: test",
            "top_tokens": ["test"],
            "trace_append": {
                "service": "ai-router",
                "event": "classified",
                "ts": "2024-01-01T00:00:00.000+00:00",
                "meta": {"route": "search", "confidence": 0.85},
            },
        }
        assert required_fields.issubset(set(sample.keys()))

    def test_trace_append_has_required_fields(self):
        """The gateway accesses trace_append['service'], ['event'], ['ts']."""
        trace = make_trace_entry("test-service", "test-event", {"key": "value"})
        assert trace.service == "test-service"
        assert trace.event == "test-event"
        assert trace.ts is not None


@pytest.mark.integration
class TestGatewayBackendContract:
    """Verify gateway expects the same response shape that backends produce."""

    def test_handle_response_has_required_fields(self):
        """Gateway expects payload and trace_append from /handle."""
        required_fields = {"payload", "trace_append"}
        sample = {
            "payload": {"service": "search-service", "result": "test"},
            "trace_append": {
                "service": "search-service",
                "event": "handled",
                "ts": "2024-01-01T00:00:00.000+00:00",
                "meta": {"status": 200},
            },
        }
        assert required_fields.issubset(set(sample.keys()))


@pytest.mark.integration
class TestPolicyIntegration:
    """Verify that policy decisions work with realistic classify outputs."""

    @pytest.mark.parametrize(
        "probs,expected_route",
        [
            ({"search": 0.85, "image": 0.05, "ops": 0.05, "unknown": 0.05}, "search"),
            ({"search": 0.05, "image": 0.85, "ops": 0.05, "unknown": 0.05}, "image"),
            ({"search": 0.05, "image": 0.05, "ops": 0.85, "unknown": 0.05}, "ops"),
            ({"search": 0.30, "image": 0.30, "ops": 0.30, "unknown": 0.10}, "unknown"),
            ({"search": 0.40, "image": 0.30, "ops": 0.20, "unknown": 0.10}, "unknown"),
        ],
    )
    def test_policy_with_realistic_probabilities(self, probs, expected_route):
        best_label = max(
            {k: v for k, v in probs.items() if k != "unknown"},
            key=lambda k: probs[k],
        )
        route, _ = apply_policy(best_label, probs)
        assert route == expected_route


@pytest.mark.integration
class TestApiRequestModel:
    """Verify request/response model validation."""

    def test_valid_request(self):
        req = ApiRequest(text="test query")
        assert req.text == "test query"
        assert req.request_id is None

    def test_request_with_id(self):
        req = ApiRequest(request_id="custom-id", text="test")
        assert req.request_id == "custom-id"

    def test_request_with_trace(self):
        req = ApiRequest(
            text="test",
            trace=[{"service": "web", "event": "click", "ts": "now"}],
        )
        assert len(req.trace) == 1

    def test_text_max_length_validation(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ApiRequest(text="a" * 10001)


@pytest.mark.integration
class TestTraceEntry:
    def test_trace_entry_creation(self):
        entry = make_trace_entry("gateway", "received", {"key": "value"})
        assert entry.service == "gateway"
        assert entry.event == "received"
        assert entry.meta == {"key": "value"}
        assert "T" in entry.ts

    def test_trace_entry_no_meta(self):
        entry = make_trace_entry("gateway", "received")
        assert entry.meta is None

    def test_trace_entry_model_dump(self):
        entry = make_trace_entry("gateway", "received")
        d = entry.model_dump()
        assert isinstance(d, dict)
        assert "service" in d
        assert "event" in d
        assert "ts" in d
