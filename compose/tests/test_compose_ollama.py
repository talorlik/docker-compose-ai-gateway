"""Tests for Ollama configuration in docker-compose.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]

COMPOSE_FILE = Path(__file__).resolve().parent.parent / "docker-compose.yaml"


def _load_compose() -> dict:
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))


def test_ollama_service_exists():
    compose = _load_compose()
    assert "ollama" in compose["services"], "ollama service not found"


def test_ollama_image():
    compose = _load_compose()
    svc = compose["services"]["ollama"]
    assert svc["image"].startswith("ollama/ollama:")


def test_ollama_port_mapping():
    compose = _load_compose()
    svc = compose["services"]["ollama"]
    ports = svc.get("ports", [])
    assert len(ports) == 1, "ollama should expose exactly one port"
    port_str = str(ports[0])
    assert "11434" in port_str


def test_ollama_has_volume():
    compose = _load_compose()
    svc = compose["services"]["ollama"]
    vols = svc.get("volumes", [])
    assert len(vols) >= 1, "ollama must have a volume for /root/.ollama"
    assert any("ollama_data" in str(v) for v in vols)


def test_ollama_volume_declared_top_level():
    compose = _load_compose()
    top_volumes = compose.get("volumes", {})
    assert "ollama_data" in top_volumes


def test_ollama_pulls_model():
    compose = _load_compose()
    svc = compose["services"]["ollama"]
    cmd = svc.get("command", "")
    assert "ollama pull" in str(cmd), "ollama must pull a model"


def test_ollama_healthcheck_present():
    compose = _load_compose()
    svc = compose["services"]["ollama"]
    hc = svc.get("healthcheck", {})
    assert "test" in hc, "ollama must have a healthcheck"


def test_ollama_has_restart_policy():
    compose = _load_compose()
    svc = compose["services"]["ollama"]
    assert svc.get("restart") == "unless-stopped"


def test_ollama_in_refine_profile():
    compose = _load_compose()
    svc = compose["services"]["ollama"]
    profiles = svc.get("profiles", [])
    assert "refine-container" in profiles


def test_redis_service_exists():
    compose = _load_compose()
    assert "redis" in compose["services"]


def test_redis_healthcheck():
    compose = _load_compose()
    svc = compose["services"]["redis"]
    hc = svc.get("healthcheck", {})
    test_cmd = " ".join(str(t) for t in hc.get("test", []))
    assert "redis-cli" in test_cmd and "ping" in test_cmd


def test_training_api_depends_on_redis():
    compose = _load_compose()
    training_api = compose["services"]["training-api"]
    deps = training_api.get("depends_on", {})
    assert "redis" in deps
    assert deps["redis"].get("condition") == "service_healthy"


def test_gateway_depends_on_core_services():
    compose = _load_compose()
    gw = compose["services"]["gateway"]
    deps = gw.get("depends_on", {})
    for svc in ("ai_router", "search_service", "image_service", "ops_service"):
        assert svc in deps, f"gateway must depend on {svc}"


def test_all_services_have_healthchecks():
    compose = _load_compose()
    for name, svc in compose["services"].items():
        profiles = svc.get("profiles", [])
        if "train" in profiles:
            continue
        if "refine" in profiles and name != "training-api":
            continue
        if name in ("ollama", "redis"):
            assert "healthcheck" in svc, f"{name} missing healthcheck"
            continue
        assert "healthcheck" in svc, f"{name} missing healthcheck"


def test_all_services_have_logging():
    compose = _load_compose()
    for name, svc in compose["services"].items():
        assert "logging" in svc, f"{name} missing logging config"


def test_model_artifacts_volume_exists():
    compose = _load_compose()
    top_volumes = compose.get("volumes", {})
    assert "model_artifacts" in top_volumes
