#!/usr/bin/env python3
# pylint: disable=import-error,pointless-statement,expression-not-assigned
from __future__ import annotations

import subprocess
from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.generic.compute import Rack
from diagrams.generic.storage import Storage
from diagrams.onprem.client import Users
from diagrams.onprem.compute import Server
from diagrams.onprem.container import Docker
from diagrams.onprem.inmemory import Redis

TIER_COLORS = {
    "CLIENT_EDGE": "#E3F2FD",
    "GATEWAY": "#E8EAF6",
    "INFERENCE": "#E8F5E9",
    "TRAINING_CONTROL": "#F3E5F5",
    "EVENTING_STATE": "#FFF8E1",
    "LLM_REFINEMENT": "#E0F7FA",
    "ARTIFACT_STORAGE": "#FFF3E0",
    "OBSERVABILITY": "#ECEFF1",
}


def cluster_attrs(bg: str) -> dict[str, str]:
    return {
        "style": "filled",
        "color": bg,
        "bgcolor": bg,
        "pencolor": "#607D8B",
    }


GRAPH_ATTR = {
    "splines": "ortho",
    "nodesep": "0.8",
    "ranksep": "1.2",
    "fontsize": "14",
    "bgcolor": "white",
    "pad": "0.5",
}


def convert_dot_to_drawio(dot_path: Path) -> None:
    drawio_path = dot_path.with_suffix(".drawio")
    subprocess.run(
        [
            "graphviz2drawio",
            str(dot_path),
            "-o",
            str(drawio_path),
        ],
        check=True,
    )


def build_unified_architecture_diagram(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = output_dir / "docker_compose_ai_gateway_unified"

    with Diagram(
        "docker-compose-ai-gateway Unified Architecture",
        filename=str(filename),
        outformat=["png", "dot"],
        show=False,
        direction="TB",
        graph_attr=GRAPH_ATTR,
    ):
        with Cluster(
            "BROWSER / CLI CLIENTS",
            graph_attr=cluster_attrs(TIER_COLORS["CLIENT_EDGE"]),
        ):
            browser = Users("Browser UI\n(/, #train, #refine)")
            cli = Users("CLI / Scripts\n(optional)")

        with Cluster(
            "LOCALHOST EXPOSED PORTS",
            graph_attr=cluster_attrs(TIER_COLORS["CLIENT_EDGE"]),
        ):
            port_gateway = Rack("127.0.0.1:8000\nGateway UI + API")
            port_router = Rack("127.0.0.1:8001\nai_router debug")
            port_ollama = Rack("127.0.0.1:11434\nOllama (profile active)")

        with Cluster(
            "CORE RUNTIME (DEFAULT PROFILE)",
            graph_attr=cluster_attrs(TIER_COLORS["INFERENCE"]),
        ):
            with Cluster(
                "API GATEWAY LAYER",
                graph_attr=cluster_attrs(TIER_COLORS["GATEWAY"]),
            ):
                gateway = Docker("gateway")

            with Cluster(
                "INFERENCE RUNTIME",
                graph_attr=cluster_attrs(TIER_COLORS["INFERENCE"]),
            ):
                ai_router = Server("ai_router")
                search_service = Server("search_service")
                image_service = Server("image_service")
                ops_service = Server("ops_service")

        with Cluster(
            "TRAIN/REFINE CONTROL PLANE",
            graph_attr=cluster_attrs(TIER_COLORS["TRAINING_CONTROL"]),
        ):
            training_api = Server("training-api")

            with Cluster(
                "EVENTING AND STATE",
                graph_attr=cluster_attrs(TIER_COLORS["EVENTING_STATE"]),
            ):
                redis = Redis("redis\n(internal only)")

        with Cluster(
            "OPTIONAL PROFILE SERVICES",
            graph_attr=cluster_attrs(TIER_COLORS["LLM_REFINEMENT"]),
        ):
            trainer = Docker("trainer\n(profile: train)")
            refiner = Docker("refiner\n(profile: refine)")
            ollama = Docker("ollama\n(profile: refine-container)")

        with Cluster(
            "SHARED VOLUMES",
            graph_attr=cluster_attrs(TIER_COLORS["ARTIFACT_STORAGE"]),
        ):
            model_artifacts = Storage("model_artifacts")
            ollama_data = Storage("ollama_data")

        with Cluster(
            "OBSERVABILITY AND OPS CONTEXT",
            graph_attr=cluster_attrs(TIER_COLORS["OBSERVABILITY"]),
        ):
            invariant = Rack(
                "INVARIANT\nGateway is the only public\napplication entrypoint"
            )
            env_cfg = Rack("PROJECT_CONFIG.yaml\n-> scripts/generate_env.py\n-> env/.env.dev")

        browser >> Edge(label="GET /, POST /api/request") >> gateway
        browser >> Edge(label="POST /api/train") >> gateway
        browser >> Edge(label="POST /api/refine/relabel") >> gateway
        browser >> Edge(label="POST /api/refine/augment") >> gateway
        browser >> Edge(label="POST /api/refine/promote") >> gateway
        browser >> Edge(label="EventSource\nGET /api/*/events/{job_id}") >> gateway
        cli >> Edge(label="curl / scripts") >> gateway

        port_gateway >> gateway
        port_router >> ai_router
        port_ollama >> ollama

        gateway >> Edge(label="POST /classify") >> ai_router
        gateway >> Edge(label="POST /handle\n(route=search)") >> search_service
        gateway >> Edge(label="POST /handle\n(route=image)") >> image_service
        gateway >> Edge(label="POST /handle\n(route=ops)") >> ops_service
        gateway >> Edge(label="proxy train/refine/promote\nand SSE") >> training_api

        training_api >> Edge(label="job state SET/GET\nRedis Pub/Sub") >> redis
        training_api >> Edge(label="docker compose run --rm") >> trainer
        training_api >> Edge(label="docker compose run --rm") >> refiner
        refiner >> Edge(label="LLM calls\nhttp://ollama:11434") >> ollama

        trainer >> Edge(label="write metrics/model") >> model_artifacts
        ai_router >> Edge(label="read model.joblib", style="dashed") >> model_artifacts
        refiner >> Edge(label="read/write datasets") >> model_artifacts
        training_api >> Edge(label="read artifacts\nfor results/promote") >> model_artifacts
        ollama >> Edge(label="persist models") >> ollama_data

        env_cfg >> Edge(label="env_file", style="dashed") >> gateway
        env_cfg >> Edge(style="dashed") >> ai_router
        env_cfg >> Edge(style="dashed") >> training_api
        env_cfg >> Edge(style="dashed") >> refiner
        env_cfg >> Edge(style="dashed") >> ollama

        invariant >> Edge(style="dashed") >> gateway

    return filename.with_suffix(".dot")


def main() -> int:
    diagrams_dir = Path(__file__).resolve().parent / "diagrams"
    dot_path = build_unified_architecture_diagram(diagrams_dir)
    convert_dot_to_drawio(dot_path)
    print(f"Generated: {dot_path}")
    print(f"Generated: {dot_path.with_suffix('.png')}")
    print(f"Generated: {dot_path.with_suffix('.drawio')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
