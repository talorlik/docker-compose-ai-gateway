"""Shared fixtures for gateway tests.

Handles the sys.modules cleanup needed when multiple services share
the `app` package name. Import this conftest before any gateway app imports.
"""

from __future__ import annotations

import os
import sys

# Ensure gateway's app package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
for k in list(sys.modules.keys()):
    if k == "app" or k.startswith("app."):
        sys.modules.pop(k, None)

os.environ.setdefault("T_ROUTE", "0.55")
os.environ.setdefault("T_MARGIN", "0.10")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def gateway_app():
    """Return the gateway FastAPI app instance."""
    return app


@pytest.fixture
def client():
    """Per-test TestClient (function scope to avoid mock leakage)."""
    with TestClient(app) as c:
        yield c
