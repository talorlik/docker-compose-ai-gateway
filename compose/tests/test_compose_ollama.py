"""Tests for Ollama instance configuration in docker-compose.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]

COMPOSE_FILE = Path(__file__).resolve().parent.parent / "docker-compose.yaml"


def _load_compose() -> dict:
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))


def test_three_ollama_services_exist():
    compose = _load_compose()
    services = compose["services"]
    for name in ("ollama_1", "ollama_2", "ollama_3"):
        assert name in services, f"{name} not found in services"


def test_ollama_image_is_latest():
    compose = _load_compose()
    for name in ("ollama_1", "ollama_2", "ollama_3"):
        svc = compose["services"][name]
        assert svc["image"] == "ollama/ollama:latest"


def test_ollama_ports_are_unique():
    compose = _load_compose()
    host_ports: list[str] = []
    for name in ("ollama_1", "ollama_2", "ollama_3"):
        svc = compose["services"][name]
        ports = svc.get("ports", [])
        assert len(ports) == 1, f"{name} should expose exactly one port"
        host_port = str(ports[0]).split(":")[0]
        host_ports.append(host_port)
    assert len(set(host_ports)) == 3, "Ollama host ports must be unique"
    assert set(host_ports) == {"11434", "11435", "11436"}


def test_ollama_internal_port_is_11434():
    compose = _load_compose()
    for name in ("ollama_1", "ollama_2", "ollama_3"):
        svc = compose["services"][name]
        container_port = str(svc["ports"][0]).split(":")[1]
        assert container_port == "11434", f"{name} container port should be 11434"


def test_ollama_volumes_are_separate():
    compose = _load_compose()
    volume_names: list[str] = []
    for name in ("ollama_1", "ollama_2", "ollama_3"):
        svc = compose["services"][name]
        vols = svc.get("volumes", [])
        assert len(vols) >= 1, f"{name} must have a volume for /root/.ollama"
        vol_src = str(vols[0]).split(":")[0]
        volume_names.append(vol_src)
    assert len(set(volume_names)) == 3, "Each Ollama instance must use a separate volume"
    assert set(volume_names) == {"ollama_data_1", "ollama_data_2", "ollama_data_3"}


def test_ollama_volumes_declared_top_level():
    compose = _load_compose()
    top_volumes = compose.get("volumes", {})
    for vol in ("ollama_data_1", "ollama_data_2", "ollama_data_3"):
        assert vol in top_volumes, f"Top-level volume {vol} must be declared"


def test_ollama_pulls_phi3_mini():
    compose = _load_compose()
    for name in ("ollama_1", "ollama_2", "ollama_3"):
        svc = compose["services"][name]
        cmd = svc.get("command", "")
        assert "phi3:mini" in str(cmd), f"{name} must pull phi3:mini"


def test_ollama_healthcheck_verifies_model():
    compose = _load_compose()
    for name in ("ollama_1", "ollama_2", "ollama_3"):
        svc = compose["services"][name]
        hc = svc.get("healthcheck", {})
        test_cmd = " ".join(str(t) for t in hc.get("test", []))
        assert "phi3:mini" in test_cmd, f"{name} healthcheck must verify phi3:mini"


def test_ollama_has_restart_policy():
    compose = _load_compose()
    for name in ("ollama_1", "ollama_2", "ollama_3"):
        svc = compose["services"][name]
        assert svc.get("restart") == "unless-stopped", (
            f"{name} must have restart: unless-stopped"
        )


def test_training_api_depends_on_all_ollama_instances():
    compose = _load_compose()
    training_api = compose["services"]["training-api"]
    deps = training_api.get("depends_on", {})
    for name in ("ollama_1", "ollama_2", "ollama_3"):
        assert name in deps, f"training-api must depend on {name}"
        assert deps[name].get("condition") == "service_healthy"
