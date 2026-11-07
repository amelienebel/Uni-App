"""Seite „Vorlesungs-Check“ (ersetzt Karteikarten): alle Vorlesungen aller Module mit Check-Status."""

from __future__ import annotations

import streamlit as st

from utils import mastery, planner, sessions, topics
from utils.config import get_module
from utils.storage import load_module, load_todos, today
from views import session_ui
from views.common import micon, open_unit
from views.module_tabs import nacharbeiten

MODULE_RANK = {"rewe": 0, "invfin": 0, "statistik": 1, "mathe": 1, "vwl": 2}


def session_active() -> bool:
    return session_ui.active() is not None


def _row(cfg: dict, module: dict, data: dict, lec: dict, state: dict) -> None:
    module_id = module["id"]
    mts = topics.minitopics(data, lec["id"])
    asked, total = mastery.coverage(data, mts)
    done = sessions.check_done(data, lec["id"])
    review_done = bool(state.get(planner.lecture_key(module_id, lec["date"], "nachbereitet")))
    due = planner.review_due(module, lec["date"])
    with st.container(border=True, key=f"ckrow_{module_id}_{lec['id'].replace(':', '_')}"):
        c1, c2 = st.columns([3, 2], vertical_alignment="center")
        c1.markdown(f"{micon(module)} **{sessions.check_label(module, lec)}**  \n"
                    f"<span class='small-muted'>{lec['topic'][:70]}</span>", unsafe_allow_html=True)
        if total:
            c1.progress(asked / total, text=f"{asked}/{total} Minithemen abgefragt")
        if not mts:
            c2.caption("Nacharbeiten offen" + (" · überfällig" if due < today() and not review_done else ""))
            c2.button("Nacharbeiten", key=f"cknach_{module_id}_{lec['id']}", icon=":material/edit_note:", width="stretch",
                      on_click=_open_lecture, args=(module_id, lec["id"], "nachbereitet"))
            return
        with c2.popover("Weiter" if sessions.running(data, "check", lec["id"]) else
                        ("Wiederholen" if done else "Check starten"),
                        icon=":material/play_arrow:", width="stretch"):
            nacharbeiten.check_panel(cfg, module_id, lec, key=f"cc_{module_id}_{lec['id']}")


def _open_lecture(module_id: str, lec_id: str, tab: str) -> None:
    from views.common import LECTURE_TAB

    st.session_state[f"ltab_next_{lec_id}"] = LECTURE_TAB[tab]
    open_unit(module_id, lec_id)


def render(cfg: dict) -> None:
    if session_active():
        session_ui.render(cfg)
        return
    st.title(":material/fact_check: Vorlesungs-Check")
    state = load_todos()
    modules = sorted(cfg["modules"], key=lambda m: MODULE_RANK.get(m["id"], 3))
    open_rows, done_rows = [], []
    for module in modules:
        data = load_module(module["id"])
        for lec in sessions.held_lectures(cfg, module["id"], data):
            if sessions.is_legacy(data, lec["id"]) and not sessions.finished(data, "check", lec["id"]):
                continue
            (done_rows if sessions.check_done(data, lec["id"]) else open_rows).append((module, data, lec))
    st.subheader(f"Offen ({len(open_rows)})")
    if not open_rows:
        st.caption("Alle Checks erledigt.")
    shown = None
    for module, data, lec in open_rows:
        if module["id"] != shown:
            shown = module["id"]
            with st.container(key=f"ckhead_{module['id']}"):
                st.markdown(f"#### {micon(module)} {module['name']}")
        _row(cfg, module, data, lec, state)
    if done_rows:
        st.subheader(f"Erledigt ({len(done_rows)})")
        for module in modules:
            rows = [r for r in done_rows if r[0]["id"] == module["id"]]
            if not rows:
                continue
            with st.expander(f"{module['short']} · {len(rows)} Checks", icon=micon(get_module(cfg, module["id"]))):
                for _, data, lec in rows:
                    _row(cfg, module, data, lec, state)
