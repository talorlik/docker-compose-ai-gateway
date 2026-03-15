"""CLI entrypoint for train, refine, promote (no Redis/HTTP).

Per TRAIN_AND_REFINE_GUI_PAGES_TECH §4.1: same Python code as HTTP handlers;
entrypoint e.g. python -m app.cli promote. Used by docker compose run
training-api train|refine|promote. Mounts (project dir, volume) are in Batch 7.
"""

from __future__ import annotations

import json
import sys

from app.jobs.runner import run_promote, run_refine, run_train


def _main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("server", "-h", "--help"):
        # Default: run HTTP server (for docker compose up)
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

    if subcommand == "promote":
        try:
            result = run_promote()
            print(json.dumps(result, indent=2))
            return 0
        except FileNotFoundError as e:
            print(str(e), file=sys.stderr)
            return 1
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            return 1

    print(f"Unknown subcommand: {subcommand}. Use train, refine, or promote.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(_main())
