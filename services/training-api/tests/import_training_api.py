from __future__ import annotations

import contextlib
import os
import sys
from types import ModuleType
from typing import Iterator


@contextlib.contextmanager
def training_api_imported() -> Iterator[None]:
    """Temporarily make training-api's `app` package importable as `app`.

    This repo has multiple services that use a top-level `app` package
    (gateway, training-api). During a full pytest run, whichever imports first
    can "win" in sys.modules. This context manager swaps the `app` modules so
    tests can reliably import training-api modules without breaking other
    service tests.
    """
    training_api_root = os.path.join(os.path.dirname(__file__), "..")

    saved: dict[str, ModuleType] = {}
    for k in list(sys.modules.keys()):
        if k == "app" or k.startswith("app."):
            saved[k] = sys.modules.pop(k)  # type: ignore[assignment]

    sys.path.insert(0, training_api_root)
    try:
        yield
    finally:
        # Remove training-api `app` modules imported during the context.
        for k in list(sys.modules.keys()):
            if k == "app" or k.startswith("app."):
                sys.modules.pop(k, None)

        # Restore prior `app` modules (e.g. gateway).
        sys.modules.update(saved)

        # Remove our sys.path entry if still present.
        try:
            sys.path.remove(training_api_root)
        except ValueError:
            pass
