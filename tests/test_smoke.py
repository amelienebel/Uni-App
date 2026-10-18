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


def test_learn_button_opens_focus_mode_and_enter_reveals():
    import json

    from utils import spaced_repetition as sr

    mid = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))["modules"][0]["id"]
    at = _run(AppTest.from_file(str(ROOT / "app.py"), default_timeout=120))
    chapter = (at.session_state[f"_module_{mid}"]["chapters"] or [{}])[0].get("id")
    at.session_state[f"_module_{mid}"]["cards"] = [sr.new_card(f"Frage {i}?", "- Antwort", chapter_id=chapter)
                                                   for i in range(3)]
    _run(at)
    at.button(key=f"learn_{mid}").click()
    _run(at)
    assert at.session_state["cc_session"]["return"] and not at.sidebar.button
    at.text_input[0].input("Antwort")
    at.button[[b.label for b in at.button].index("Auflösen")].click()
    _run(at)
    assert any(b.label.startswith("Gut") for b in at.button)
    at.button(key="cc_end").click()
    _run(at)
    assert "cc_session" not in at.session_state and at.title[0].value.startswith(":material/today:")
    from views.common import MODULE_TABS, PAGES

    at.session_state["nav"] = PAGES["week"]
    _run(at)
    today_chip = next(b for b in at.button if b.key and b.key.startswith("cardchip_"))
    today_chip.click()
    _run(at)
    assert at.session_state["cc_session"]["queue"]
    at.button(key="cc_end").click()
    _run(at)
    at.sidebar.button(key=f"navmod_{mid}").click()
    at.session_state[f"mtabs_{mid}"] = MODULE_TABS[1]
    _run(at)
    focus = [b for b in at.button if b.key and b.key.startswith("focus_learn_")]
    focus[0].click()
    _run(at)
    assert at.session_state["cc_session"]["return"]
