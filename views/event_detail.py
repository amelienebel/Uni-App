"""Detailbereich einer Veranstaltung aus dem Stundenplan: Thema, Dateien, Vor- und Nachbereitung, Fragen."""

from __future__ import annotations

from datetime import date

import streamlit as st

from utils import ai, planner
from utils.config import WEEKDAYS, get_module, load_config
from utils.storage import (abs_data_path, chapter_label, get_notes, get_schedule, lecture_breaks, load_module,
                           load_todos, save_module, save_todos)
from views.common import open_module_tab

EXERCISE_TYPES = ("Übung", "Tutorium")


def toggle_todo(todo: dict, widget_key: str) -> None:
    value = st.session_state[widget_key]
    if todo.get("status_field"):
        data = load_module(todo["module_id"])
        for ch in data["chapters"]:
            if ch["id"] == todo["chapter_id"]:
                ch["status"][todo["status_field"]] = value
        save_module(todo["module_id"])
        return
    state = load_todos()
    state[todo["key"]] = value
    save_todos()
    if todo.get("sync") and todo.get("chapter_id"):
        data = load_module(todo["module_id"])
        planner.sync_chapter_status(get_module(load_config(), todo["module_id"]), data, todo["chapter_id"],
                                    todo["sync"], state)
        save_module(todo["module_id"])



def _download_docs(docs: list[dict], prefix: str) -> None:
    for doc in docs:
        try:
            path = abs_data_path(doc["path"])
            content = path.read_bytes()
        except (ValueError, OSError, KeyError):
            continue
        st.download_button(f"📄 {doc['filename']}", content, file_name=doc["filename"], mime="application/pdf",
                           key=f"dl_{prefix}_{doc['id']}")


def render(cfg: dict, ev: dict) -> None:
    """Detailbereich einer Veranstaltung (Vorlesung/Übung) – oben im Modul-Bereich."""
    mid = ev["module_id"]
    module = get_module(cfg, mid)
    data = load_module(mid)
    ev_date = date.fromisoformat(ev["date"])
    todo_state = load_todos()
    is_exercise = ev.get("type") in EXERCISE_TYPES

    with st.container(border=True):
        head, close = st.columns([8, 1])
        head.markdown(f"### {module['icon']} {module['name']} – {ev.get('type', '')}")
        close.button("✖", key="close_event", help="Schließen", on_click=lambda: st.session_state.pop("sel_event", None))
        st.caption(f"{WEEKDAYS[ev_date.weekday()]}, {ev_date:%d.%m.%Y} · {ev.get('start', '')}–{ev.get('end', '')} Uhr"
                   f" · {ev.get('room', '')}")

        chapter_id = None
        if is_exercise:
            monday = planner.monday_of(ev_date)
            exercises = planner.exercises_of(module)
            schedule = get_schedule(load_config())
            ex = next((e for e in exercises
                       if planner.exercise_session(mid, e, schedule, lecture_breaks(load_config())) == ev_date), None) \
                or next((e for e in exercises if e["week_of"] == monday), None)
            if ex:
                chapter_id = ex.get("chapter_id")
                st.markdown(f"**✏️ {ex['title']}**")
                key = planner.exercise_key(mid, ex)
                wkey = f"evx_{key}"
                st.session_state[wkey] = bool(todo_state.get(key))
                st.checkbox("Übung vorbereitet / Blatt gelöst", key=wkey, on_change=toggle_todo,
                            args=({"key": key, "module_id": mid, "chapter_id": chapter_id, "sync": "uebung"}, wkey))
            else:
                st.caption("Für diesen Termin ist im Kursplan kein Übungsblatt hinterlegt.")
        else:
            lecture = next((lec for lec in planner.lectures_of(module) if lec["date"] == ev_date), None)
            if lecture:
                chapter_id = lecture.get("chapter_id")
                st.markdown(f"**🎬 {lecture['topic']}**")
                c1, c2 = st.columns(2)
                for col, field, label in ((c1, "vorbereitet", "Vorbereitet"), (c2, "nachbereitet", "Nachbereitet")):
                    key = planner.lecture_key(mid, ev_date, field)
                    wkey = f"evl_{key}"
                    st.session_state[wkey] = bool(todo_state.get(key))
                    col.checkbox(label, key=wkey, on_change=toggle_todo,
                                 args=({"key": key, "module_id": mid, "chapter_id": chapter_id, "sync": field}, wkey))
            else:
                st.caption("Für dieses Datum steht im Kursplan keine Vorlesung (z. B. Ausfall oder Ferien).")
        if chapter_id:
            st.caption(f"Kapitel: {chapter_label(data, chapter_id)}")

        tab_files, tab_prep, tab_notes, tab_q = st.tabs(["📂 Dateien", "🎬 Vorbereitung", "📝 Nachbereitung",
                                                         "❓ Fragen fürs Tutorium"])
        docs = [d for d in data["documents"] if chapter_id and d.get("chapter_id") == chapter_id]
        with tab_files:
            if docs:
                _download_docs(docs, f"{mid}_{ev['date']}")
            else:
                st.caption("Noch keine Dateien für dieses Kapitel. Hochladen über 📂 Bulk-Upload.")
        with tab_prep:
            analysed = [d for d in docs if d.get("analysis")]
            if analysed:
                a = analysed[0]["analysis"]
                st.markdown(a.get("summary", ""))
                for i, q in enumerate(a.get("check_questions", [])[:3], start=1):
                    with st.expander(f"❓ {q['question']}"):
                        st.markdown(q["answer"])
            elif docs:
                st.caption("Die Folien sind noch nicht analysiert.")
                if st.button("✨ Folien jetzt analysieren", key=f"evd_an_{mid}_{ev['date']}"):
                    from views.module_tabs.preparation import _run_analysis

                    with st.spinner("Analysiere …"):
                        try:
                            _run_analysis(cfg, mid, docs[0])
                            st.rerun()
                        except ai.AIError as exc:
                            st.error(str(exc))
            else:
                st.caption("Lade zuerst die Folien hoch.")
            st.button("→ Reiter Vorbereitung öffnen", key=f"evd_prep_{mid}_{ev['date']}",
                      on_click=open_module_tab, args=(mid, "prep", chapter_id))
        with tab_notes:
            if chapter_id:
                notes = get_notes(data, chapter_id)
                with st.form(f"ev_notes_{mid}_{chapter_id}_{ev['date']}"):
                    text = st.text_area("Notizen", notes["text"], height=120)
                    emphasized = st.text_area("Vom Dozenten betont", notes["emphasized"], height=80)
                    examples = st.text_area("Beispiele", notes["examples"], height=80)
                    if st.form_submit_button("💾 Speichern"):
                        notes.update({"text": text, "emphasized": emphasized, "examples": examples})
                        save_module(mid)
                        st.success("Gespeichert.")
            st.button("→ Reiter Nachbereitung öffnen", key=f"evd_rev_{mid}_{ev['date']}",
                      on_click=open_module_tab, args=(mid, "review", chapter_id))
        with tab_q:
            from views.module_tabs.notes import question_list

            question_list(mid, data, key_prefix=f"evq_{ev['date']}")


