"""CLI entrypoint for train, refine, promote (no Redis/HTTP).

Per TRAIN_AND_REFINE_GUI_PAGES_TECH §4.1: same Python code as HTTP handlers;
entrypoint e.g. python -m app.cli promote. Used by docker compose run
training-api train|refine|promote. Mounts (project dir, volume) are in Batch 7.
"""

from __future__ import annotations

import json
import os
import sys
import uuid

from app.jobs.runner import run_promote, run_refine, run_train
from app.refine.augment import run_augment_phase
from app.refine.config import RefineConfig
from app.refine.relabel import run_relabel_phase


def _main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] == "server":
        try:
            import uvicorn
            uvicorn.run(
                "app.main:app",
                host="0.0.0.0",
                port=8000,
            )
            return 0
        except ImportError:
            print("Usage: python -m app.cli train | refine | promote | server", file=sys.stderr)
            return 1

    if argv[0] in ("-h", "--help"):
        print(
            "Usage: python -m app.cli <subcommand>\n\n"
            "Subcommands:\n"
            "  server    Run HTTP server (default)\n"
            "  train     Run training job\n"
            "  refine    Run legacy refiner subprocess\n"
            "  relabel   Run relabel phase\n"
            "  augment   Run augment phase\n"
            "  promote   Promote candidate dataset",
        )
        return 0

    subcommand = argv[0].lower()

    if subcommand == "train":
        try:
            result = run_train()
            print(json.dumps(result, indent=2))
            return 0
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            return 1

    if subcommand == "refine":
        try:
            result = run_refine()
            print(json.dumps(result, indent=2))
            return 0
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            return 1

    if subcommand == "relabel":
        try:
            artifacts_dir = os.environ.get("MODEL_ARTIFACTS_PATH", "/model")
            promote_dir = os.environ.get("PROMOTE_TARGET_PATH", "/promote_target")
            cfg = RefineConfig.from_env(artifacts_dir)
            run_id = os.environ.get("REFINER_RUN_ID") or str(uuid.uuid4())
            result = run_relabel_phase(
                cfg,
                model_artifacts_path=artifacts_dir,
                promote_target_path=promote_dir,
                run_id=run_id,
            )
            print(json.dumps(result, indent=2))
            return 0
        except (RuntimeError, FileNotFoundError, ValueError) as e:
            print(str(e), file=sys.stderr)
            return 1

    if subcommand == "augment":
        try:
            artifacts_dir = os.environ.get("MODEL_ARTIFACTS_PATH", "/model")
            promote_dir = os.environ.get("PROMOTE_TARGET_PATH", "/promote_target")
            cfg = RefineConfig.from_env(artifacts_dir)
            run_id = os.environ.get("REFINER_RUN_ID") or str(uuid.uuid4())
            result = run_augment_phase(
                cfg,
                model_artifacts_path=artifacts_dir,
                promote_target_path=promote_dir,
                run_id=run_id,
            )
            print(json.dumps(result, indent=2))
            return 0
        except (RuntimeError, FileNotFoundError, ValueError) as e:
            print(str(e), file=sys.stderr)
            return 1

    if subcommand == "promote":
        try:
            result = run_promote()
            print(json.dumps(result, indent=2))
            return 0
        except (FileNotFoundError, RuntimeError) as e:
            print(str(e), file=sys.stderr)
            return 1

    print(
        f"Unknown subcommand: {subcommand}. Use train, refine, "
        "relabel, augment, or promote.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(_main())
