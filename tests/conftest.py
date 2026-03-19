"""Shared conftest for integration and e2e tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "gateway"))

os.environ.setdefault("T_ROUTE", "0.55")
os.environ.setdefault("T_MARGIN", "0.10")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
