"""Seite einer einzelnen Übung (inkl. Tutorium): Blatt, Musterlösung, Rückmeldung, Minithemen."""

from __future__ import annotations

import streamlit as st

from utils import planner
from utils.config import WEEKDAYS_SHORT, get_module
from utils.storage import chapter_label, get_schedule, lecture_breaks, load_module, load_todos, save_module
from utils.storage import now_iso
from utils.units import exercise_feedback, related_lectures, session_text, short_label, unit_docs
from views.common import done_button, open_unit
from views.module_tabs.files import file_list, show_messages, uploader

def _set_chapter(module_id: str, unit_id: str, widget_key: str) -> None:
    data = load_module(module_id)
    data.setdefault("exercise_chapters", {})[unit_id] = st.session_state[widget_key]
    save_module(module_id)


def _feedback(module_id: str, ex: dict) -> None:
    """Rückmeldung aus der Übung (gut / ging so / schlecht) → wird den Minithemen zugeordnet."""
    data = load_module(module_id)
    fb = exercise_feedback(data, ex["id"])
    with st.container(border=True, key=f"fbbox_{ex['id'].replace(':', '_')}"):
        st.markdown("#### :material/forum: Rückmeldung zum Blatt")
        with st.form(f"exfb_{module_id}_{ex['id']}", border=False):
            c1, c2, c3 = st.columns(3)
            good = c1.text_area(":green[:material/thumb_up:] Lief gut", fb["good"], height=150)
            mid = c2.text_area(":orange[:material/thumbs_up_down:] Ging so", fb["mid"], height=150)
            bad = c3.text_area(":red[:material/thumb_down:] Lief schlecht", fb["bad"], height=150)
            if st.form_submit_button("Speichern", type="primary", width="stretch"):
                fb.update({"good": good.strip(), "mid": mid.strip(), "bad": bad.strip(), "updated_at": now_iso()})
                save_module(module_id)
                if _map_feedback(module_id, ex):
                    st.toast("Rückmeldung gespeichert und zugeordnet", icon=":material/check:")
        if fb.get("updated_at"):
            st.caption(f"Gespeichert am {fb['updated_at'][:16].replace('T', ' um ')}")


def _map_feedback(module_id: str, ex: dict) -> bool:
    """Rückmeldung gleich den Minithemen zuordnen (fürs Wochentraining); klappt es nicht, beim Trainingsstart."""
    from utils import ai, planner, sessions
    from utils.config import load_config

    if not planner.LEARNING_V2:
        return True
    if not ai.is_available():
        st.warning("Gespeichert – zugeordnet wird, sobald die KI verfügbar ist.")
        return False
    try:
        with st.spinner("Ordne Blatt und Rückmeldung den Minithemen zu …"):
            sessions.map_feedback(load_config(), module_id, ex)
    except ai.AIError as exc:
        st.error(f"Zuordnen hat nicht geklappt: {exc}")
        return False
    return True


def _remap(module_id: str, ex: dict) -> None:
    from utils import ai, sessions
    from utils.config import load_config

    with st.spinner("Ordne das Blatt den Minithemen zu …"):
        try:
            sessions.map_feedback(load_config(), module_id, ex)
        except ai.AIError as exc:
            st.error(str(exc))


def _sheet_topics(cfg: dict, module_id: str, ex: dict, lecs: list[dict]) -> None:
    """Welche Minithemen (auch aus früheren Vorlesungen) im Blatt dran kamen und wie es dabei lief."""
    from utils import ai, mastery, sessions, topics
    from views import progress

    if not planner.LEARNING_V2:
        return
    data = load_module(module_id)
    hits = {m["id"]: tasks for m, tasks in sessions.exercise_minitopics(cfg, module_id, data, ex)}
    rated = {m["id"]: r for m in topics.minitopics(data) if (r := mastery.exercise_rating(data, m, ex["id"]))}
    pending = sessions.needs_exercise_mapping(data, ex)
    fb = (data.get("exercise_feedback") or {}).get(ex["id"]) or {}
    mts = [m for m in topics.minitopics(data) if m["id"] in hits or m["id"] in rated]
    if not mts and not pending:
        return
    names = {lec["id"]: f"VL {lec['nr']} · {lec['topic']}" for lec in lecs}
    with st.container(border=True, key=f"sheettopics_{ex['id'].replace(':', '_')}"):
        h1, h2 = st.columns([4, 1], vertical_alignment="center")
        h1.markdown(f"#### :material/hub: Kommt im Blatt dran · {len(mts)} Minithemen")
        if h2.button("Neu zuordnen" if mts else "Zuordnen", key=f"remap_{ex['id']}", icon=":material/auto_awesome:",
                     type="secondary" if mts and not pending else "primary", width="stretch",
                     disabled=not ai.is_available()):
            _remap(module_id, ex)
            st.rerun()
        if fb.get("mapped_at") and not fb.get("sheet_read", True) and sessions.sheet_docs(data, ex):
            st.warning("Text des Blatts nicht lesbar (Foto?) – als PDF hochladen, dann neu zuordnen.")
        if not mts:
            return
        counts = {k: sum(1 for r in rated.values() if r == k) for k in mastery.EXERCISE_KINDS}
        st.markdown(" ".join(f"<span class='mt-dot' style='background:{mastery.EXERCISE_COLORS[k]}'></span>"
                             f"{label} {counts[k]}" for k, label in mastery.EXERCISE_KINDS.items()),
                    unsafe_allow_html=True)
        by_lec: dict[str, list] = {}
        for mt in mts:
            by_lec.setdefault(mt["lecture_id"], []).append(mt)
        for lec_id in sorted(by_lec, key=lambda lid: next((x["date"] for x in lecs if x["id"] == lid), lid)):
            st.markdown(f"<div class='small-muted'>{names.get(lec_id, lec_id)}</div>", unsafe_allow_html=True)
            items = by_lec[lec_id]
            st.markdown(progress.chips_html(data, items), unsafe_allow_html=True)
            for mt in items:
                rating = rated.get(mt["id"])
                color = mastery.EXERCISE_COLORS.get(rating, "#9AA3AF")
                texts = [f["text"] for f in mastery.peek(data, mt["id"])["exercise_flags"]
                         if f.get("exercise_id") == ex["id"] and f["kind"] == rating and f.get("text")]
                tasks = ", ".join(t.split(":")[0] for t in hits.get(mt["id"], []))
                line = f"**{mt['title']}**" + (f" · {tasks}" if tasks else "")
                if rating:
                    line += f" · {mastery.EXERCISE_KINDS[rating]}" + (f": {' | '.join(texts)}" if texts else "")
                st.markdown(f"<span class='mt-dot' style='background:{color}'></span>{line}",
                            unsafe_allow_html=True)


def render(cfg: dict, module_id: str, ex: dict, lecs: list[dict], exs: list[dict]) -> None:
    data = load_module(module_id)
    state = load_todos()
    nav = st.columns([2, 1, 1])
    nav[0].button("Zum Ablauf", key=f"back_{ex['id']}", on_click=open_unit, args=(module_id, None))
    idx = exs.index(ex)
    if idx > 0:
        nav[1].button("vorige Übung", icon=":material/chevron_left:", key=f"prev_{ex['id']}", on_click=open_unit,
                      args=(module_id, exs[idx - 1]["id"]), width="stretch")
    if idx < len(exs) - 1:
        nav[2].button("nächste Übung", icon=":material/chevron_right:", key=f"next_{ex['id']}", on_click=open_unit,
                      args=(module_id, exs[idx + 1]["id"]), width="stretch")

    st.markdown(f"## :material/edit_note: {ex['title']}")
    st.caption(f"Besprechung: {session_text(ex)}")

    wkey = f"exdone_{module_id}_{ex['id']}"
    due = planner.exercise_due(get_module(cfg, module_id), ex, get_schedule(cfg), lecture_breaks(cfg))
    done_button(st.columns([1, 2])[0], f"Blatt gelöst (bis {WEEKDAYS_SHORT[due.weekday()]} {due:%d.%m.})",
                bool(state.get(ex["plan_key"])), {"key": ex["plan_key"], "module_id": module_id,
                                                  "chapter_id": ex.get("chapter_id"), "sync": "uebung"}, wkey)

    c1, c2 = st.columns([4, 1], vertical_alignment="center")
    lectures = related_lectures(ex, lecs)
    if ex.get("chapter_id"):
        c1.markdown(f"**Bezieht sich auf:** {chapter_label(data, ex['chapter_id'])}"
                    + (" _(automatisch: Stoff der letzten Vorlesung davor)_" if ex.get("chapter_auto") else ""))
    else:
        c1.markdown("**Bezieht sich auf:** noch nicht zugeordnet")
    with c2.popover("Ändern"):
        options = [ch["id"] for ch in data["chapters"]]
        ckey = f"exch_{module_id}_{ex['id']}"
        st.selectbox("Kapitel", options, index=options.index(ex["chapter_id"]) if ex.get("chapter_id") in options else 0,
                     key=ckey, format_func=lambda cid: chapter_label(data, cid))
        st.button("Übernehmen", key=f"exchb_{ex['id']}", on_click=_set_chapter, args=(module_id, ex["id"], ckey))
    for lec in lectures:
        st.button(f"{short_label(lec)} – {lec['topic']}", key=f"tolec_{ex['id']}_{lec['id']}", type="tertiary",
                  on_click=open_unit, args=(module_id, lec["id"]))

    show_messages(module_id)
    all_units = lecs + exs
    docs = unit_docs(data, ex)
    cols = st.columns(2)
    for col, doc_type, title in ((cols[0], "uebung", "Übungsblatt"), (cols[1], "loesung", "Musterlösung")):
        with col.container(border=True):
            st.markdown(f"**{title}**")
            file_list(module_id, [d for d in docs if d["doc_type"] == doc_type], key=f"{ex['id']}_{doc_type}",
                      all_units=all_units, empty="Noch nichts hochgeladen.")
            uploader(cfg, module_id, ex, doc_type, "Hochladen (PDF oder Foto)", key=f"{ex['id']}_{doc_type}",
                     allow_images=True)

    _feedback(module_id, ex)
    _sheet_topics(cfg, module_id, ex, lecs)
