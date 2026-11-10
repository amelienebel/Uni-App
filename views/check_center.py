"""Seite „Checks“ (ersetzt Karteikarten): Check 1 und Check 2 aller Vorlesungen aller Module."""

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


def _row(cfg: dict, module: dict, data: dict, lec: dict, state: dict, part: int) -> None:
    module_id = module["id"]
    has = bool(topics.minitopics(data, lec["id"]))
    mts = sessions.part_minitopics(data, lec["id"], part) if has else []
    asked, total = mastery.coverage(data, mts)
    done = sessions.check_done(data, lec["id"], part)
    review_done = bool(state.get(planner.lecture_key(module_id, lec["date"], "nachbereitet")))
    due = planner.review_due(module, lec["date"])
    with st.container(border=True, key=f"ckrow_{module_id}_{lec['id'].replace(':', '_')}_{part}"):
        c1, c2 = st.columns([3, 2], vertical_alignment="center")
        c1.markdown(f"{micon(module)} **{sessions.check_label(module, lec, part)}**  \n"
                    f"<span class='small-muted'>{lec['topic'][:70]}</span>", unsafe_allow_html=True)
        if total:
            c1.progress(asked / total, text=f"{asked}/{total} Minithemen abgefragt")
        if not has:
            c2.caption("Upload offen" + (" · überfällig" if due < today() and not review_done else ""))
            c2.button("Upload", key=f"cknach_{module_id}_{lec['id']}_{part}", icon=":material/upload_file:",
                      width="stretch", on_click=_open_lecture, args=(module_id, lec["id"], "nachbereitet"))
            return
        with c2.popover("Weiter" if sessions.running_check(data, lec["id"], part) else
                        ("Wiederholen" if done else f"Check {part} starten"),
                        icon=":material/play_arrow:", width="stretch"):
            nacharbeiten.check_panel(cfg, module_id, lec, key=f"cc{part}_{module_id}_{lec['id']}", part=part)


def _open_lecture(module_id: str, lec_id: str, tab: str) -> None:
    from views.common import LECTURE_TAB

    st.session_state[f"ltab_next_{lec_id}"] = LECTURE_TAB[tab]
    open_unit(module_id, lec_id)


def render(cfg: dict) -> None:
    if session_active():
        session_ui.render(cfg)
        return
    st.title(":material/fact_check: Checks")
    state = load_todos()
    modules = sorted(cfg["modules"], key=lambda m: MODULE_RANK.get(m["id"], 3))
    open_rows, done_rows = [], []
    for module in modules:
        data = load_module(module["id"])
        for lec in sessions.held_lectures(cfg, module["id"], data):
            if sessions.is_legacy(data, lec["id"]) and not sessions.finished(data, "check", lec["id"]):
                continue
            parts = [1] if sessions.single_check(data, lec["id"]) or not sessions.halves(data, lec["id"])[1] \
                else [1, 2]
            for part in parts:
                (done_rows if sessions.check_done(data, lec["id"], part) else open_rows).append(
                    (module, data, lec, part))
    st.subheader(f"Offen ({len(open_rows)})")
    if not open_rows:
        st.caption("Alle Checks erledigt.")
    shown = None
    for module, data, lec, part in open_rows:
        if module["id"] != shown:
            shown = module["id"]
            with st.container(key=f"ckhead_{module['id']}"):
                st.markdown(f"#### {micon(module)} {module['name']}")
        _row(cfg, module, data, lec, state, part)
    if done_rows:
        st.subheader(f"Erledigt ({len(done_rows)})")
        for module in modules:
            rows = [r for r in done_rows if r[0]["id"] == module["id"]]
            if not rows:
                continue
            with st.expander(f"{module['short']} · {len(rows)} Checks", icon=micon(get_module(cfg, module["id"]))):
                for _, data, lec, part in rows:
                    _row(cfg, module, data, lec, state, part)
