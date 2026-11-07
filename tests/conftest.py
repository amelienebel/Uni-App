"""Gemeinsame Test-Hilfen."""

from __future__ import annotations

import pytest


@pytest.fixture
def old_system(monkeypatch):
    """Altes Karteikarten-/Quiz-System (LEARNING_V2 = False) – bleibt als Rückweg erhalten und getestet."""
    from utils import planner

    monkeypatch.setattr(planner, "LEARNING_V2", False)
