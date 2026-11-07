"""Seite „Wochentraining“ (ersetzt Quiz): Klausursimulation über alle bisherigen Vorlesungen eines Moduls."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from utils import ai, mastery, sessions, topics
from utils.config import get_module, module_label
from views.common import micon
from utils.storage import load_module
from views import progress, session_ui
from views.check_center import MODULE_RANK
from views.module_tabs import nacharbeiten


def session_active() -> bool:
    return session_ui.active() is not None


def legacy_without_topics(cfg: dict, module_id: str, data: dict) -> list[dict]:
    """Vorlesungen vor dem neuen System mit Unterlagen, aber noch ohne Minithemen."""
    return [lec for lec in sessions.held_lectures(cfg, module_id, data)
            if sessions.is_legacy(data, lec["id"]) and not topics.lecture_topics(data, lec["id"])
            and topics.material_docs(data, lec)]


def _prepare_legacy(cfg: dict, module_id: str, lecs: list[dict]) -> None:
    all_lecs = sessions.lectures(cfg, module_id)
    bar = st.progress(0.0, text="Lege Minithemen an …")
    errors = []
    for i, lec in enumerate(lecs, start=1):
        bar.progress((i - 1) / len(lecs), text=f"Vorlesung {lec['nr']}: Folien lesen und Minithemen anlegen …")
        try:
            data = load_module(module_id)
            topics.ensure_suggestions(module_id, data, lec, all_lecs)
            topics.read_all(cfg, module_id, lec)
            topics.create_topics(cfg, module_id, lec, all_lecs)
        except ai.AIError as exc:
            errors.append(f"Vorlesung {lec['nr']}: {exc}")
    bar.progress(1.0, text="Fertig")
    st.session_state["tr_msg"] = ("error", " · ".join(errors)) if errors else \
        ("success", f"Minithemen für {len(lecs)} frühere Vorlesung(en) angelegt.")


def _history(data: dict) -> None:
    done = sessions.finished(data, "training")
    if not done:
        return
    st.subheader(":material/history: Bisherige Trainings")
    for s in reversed(done[-8:]):
        res = sessions.summary(s)
        when = datetime.fromisoformat(s["finished_at"]).strftime("%d.%m.")
        with st.container(key=f"row_{data['module_id']}_tr_{s['id']}"):
            st.markdown(f"**{s['label']}** · {when} · {res['right']} von {res['total']} richtig"
                        + (f", {res['partial']} teilweise" if res["partial"] else ""))


def render(cfg: dict) -> None:
    if session_active():
        session_ui.render(cfg)
        return
    st.title(":material/fitness_center: Wochentraining")
    if msg := st.session_state.pop("tr_msg", None):
        getattr(st, msg[0])(msg[1])
    ids = [m["id"] for m in sorted(cfg["modules"], key=lambda m: MODULE_RANK.get(m["id"], 3))]
    if st.session_state.get("tr_module") not in ids:
        st.session_state["tr_module"] = ids[0]
    module_id = st.segmented_control("Modul", ids, key="tr_module", label_visibility="collapsed",
                                     format_func=lambda m: f"{micon(get_module(cfg, m))} {module_label(cfg, m, short=True)}"
                                     ) or ids[0]
    module = get_module(cfg, module_id)
    data = load_module(module_id)
    held = sessions.held_lectures(cfg, module_id, data)
    lec_ids = {lec["id"] for lec in held}
    stats = progress.module_stats(data, lec_ids)

    with st.container(key=f"trhead_{module_id}"):
        st.markdown(f"### {micon(module)} {module['name']}")
        st.caption(f"Nächstes: Wochentraining {sessions.next_training_number(data)} {module['short']}")
    with st.container(key="kpis"):
        c1, c2, c3 = st.columns(3)
        c1.metric("Vorlesungen bisher", len(held))
        c2.metric("Abgedeckt", f"{stats['asked']}/{stats['total']}", help="Minithemen, die schon abgefragt wurden")
        c3.metric("Sicher", stats["counts"]["sicher"])
    progress.render_status(data, lec_ids)

    missing = legacy_without_topics(cfg, module_id, data)
    if missing:
        with st.container(border=True, key="legacybox"):
            st.markdown(f":material/account_tree: **{len(missing)} frühere Vorlesung(en) ohne Minithemen:** "
                        + ", ".join(f"VL {lec['nr']}" for lec in missing))
            if st.button("Minithemen anlegen", key="tr_legacy", type="primary",
                         icon=":material/auto_awesome:", disabled=not ai.is_available()):
                _prepare_legacy(cfg, module_id, missing)
                st.rerun()
    no_topics = [lec for lec in held if not topics.lecture_topics(data, lec["id"])
                 and not sessions.is_legacy(data, lec["id"])]
    if no_topics:
        st.caption("Noch nicht nachgearbeitet: " + ", ".join(f"VL {lec['nr']}" for lec in no_topics))

    run = sessions.running(data, "training")
    if run:
        i = sessions.current_index(run)
        with st.container(border=True, key="trrun"):
            st.markdown(f"**{run['label']}** läuft · Frage {i + 1} von {len(run['items'])}")
            c1, c2 = st.columns(2)
            if c1.button("Weitermachen", key="tr_resume", type="primary", icon=":material/play_arrow:",
                         width="stretch"):
                session_ui.open_session(module_id, run["id"])
                st.rerun()
            c2.button("Verwerfen", key="tr_discard", width="stretch", on_click=sessions.discard,
                      args=(module_id, run["id"]))
    else:
        with st.container(border=True, key="trstart"):
            settings = nacharbeiten.settings_inputs("tr", with_n=True)
            n = settings.pop("n")
            mandatory = len([m for m in sessions.open_from_checks(data) if m["lecture_id"] in lec_ids])
            flagged = len([m for m in topics.minitopics(data) if mastery.has_open_flag(data, m)])
            due = len(mastery.next_due(data, [m for m in topics.minitopics(data) if m["lecture_id"] in lec_ids]))
            facts = [f"{mandatory} offen aus Checks", f"{flagged} aus Übungen", f"{due} fällig"]
            st.caption(" · ".join(facts))
            if mandatory > n:
                st.warning(f"Noch {mandatory} offene Minithemen aus Vorlesungs-Checks – mit 15 Fragen kommt mehr "
                           "davon dran, der Rest folgt im nächsten Training.", icon=":material/info:")
            slots = sessions.plan_training(data, held, n, settings)
            new = sessions.new_questions_needed(data, slots, settings)
            label = f"Wochentraining {sessions.next_training_number(data)} starten"
            if st.button(label, key="tr_go", type="primary", icon=":material/play_arrow:", width="stretch",
                         disabled=not slots or (not ai.is_available() and new > 0)):
                with st.spinner("Stelle dein Wochentraining zusammen …"):
                    try:
                        session = sessions.start_training(cfg, module_id, n, settings)
                    except ai.AIError as exc:
                        st.error(str(exc))
                        return
                session_ui.open_session(module_id, session["id"])
                st.rerun()
            if not slots:
                st.caption("Noch keine Minithemen – erst eine Vorlesung nacharbeiten.")
    _history(data)
