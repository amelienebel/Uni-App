"""Schnelltest: Jede Seite und jedes Modul der App lässt sich ohne Fehler öffnen.

Start: python -m pytest tests -q
Legt Testdaten in data/ an und räumt sie danach wieder weg (nur wenn data/ vorher leer war).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


@pytest.fixture(autouse=True)
def clean_data():
    def content():
        return [p for p in DATA.iterdir() if not p.name.startswith(".")] if DATA.exists() else []

    was_empty = not content()
    yield
    if was_empty:
        for path in content():
            shutil.rmtree(path) if path.is_dir() else path.unlink()


def _run(at: AppTest) -> AppTest:
    at.run(timeout=120)
    assert not at.exception, [e.message for e in at.exception]
    return at


def test_all_pages_and_modules_open():
    from views.common import PAGES

    at = _run(AppTest.from_file(str(ROOT / "app.py"), default_timeout=120))
    for label in PAGES.values():
        at.session_state["nav"] = label
        _run(at)
    import json

    modules = [m["id"] for m in json.loads((ROOT / "config.json").read_text(encoding="utf-8"))["modules"]]
    for mid in modules:
        at.sidebar.button(key=f"navmod_{mid}").click()
        _run(at)
        assert at.title, f"Modulseite {mid} ohne Titel"
