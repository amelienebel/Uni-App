"""Reiter: Syllabus & Kapitel."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from utils import planner
from utils.config import WEEKDAYS, WEEKDAYS_SHORT, get_module
from utils.storage import (CHAPTER_STATUS_FIELDS, chapter_label, delete_document, lecture_breaks, load_module,
                           load_todos, new_id, save_module, today)
from views.common import doc_type_label


def _ablauf(cfg: dict, module: dict, data: dict) -> None:
    """Ablauf laut Syllabus: Vorlesungstermine, Übungen und Aufgaben mit Erledigt-Status."""
    now = today()
    state = load_todos()
    breaks = lecture_breaks(cfg)
    lectures = planner.lectures_of(module)
    exercises = planner.exercises_of(module)
    tasks = planner.tasks_of(module)
    if not (lectures or exercises or tasks):
        return

    meta = [module.get("lecturer"), module.get("literature")]
    if any(meta):
        st.caption(" · ".join(f"📚 {m}" if i else f"👤 {m}" for i, m in enumerate(meta) if m))
    if module.get("exam_note"):
        st.warning(module["exam_note"], icon="📝")

    next_lec = next((lec for lec in lectures if lec["date"] >= now), None)
    if next_lec:
        st.info(f"Nächste Vorlesung: **{WEEKDAYS[next_lec['date'].weekday()]}, {next_lec['date']:%d.%m.%Y}** – "
                f"{next_lec['topic']}")

    def mark(key: str) -> str:
        return "✅" if state.get(key) else "⬜"

    if lectures:
        st.markdown("#### 🗓️ Vorlesungen")
        rows = []
        for i, lec in enumerate(lectures, start=1):
            rows.append({
                "Nr.": i,
                "Datum": f"{WEEKDAYS_SHORT[lec['date'].weekday()]}, {lec['date']:%d.%m.%Y}",
                "Kapitel": chapter_label(data, lec.get("chapter_id")) if lec.get("chapter_id") else "–",
                "Thema": lec["topic"] + (" (Ferien)" if planner.break_for(lec["date"], breaks) else ""),
                "Vorbereitet": mark(planner.lecture_key(module["id"], lec["date"], "vorbereitet")),
                "Nachbereitet": mark(planner.lecture_key(module["id"], lec["date"], "nachbereitet")),
                "": "⬅️ nächste" if lec is next_lec else "",
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if exercises:
        st.markdown("#### ✏️ Übungen & Tutorien")
        st.dataframe(pd.DataFrame([{
            "Woche ab": f"{ex['week_of']:%d.%m.%Y}",
            "Inhalt": ex["title"],
            "Kapitel": chapter_label(data, ex.get("chapter_id")) if ex.get("chapter_id") else "–",
            "Erledigt": mark(planner.exercise_key(module["id"], ex)),
        } for ex in exercises]), hide_index=True, width="stretch")
    if tasks:
        st.markdown("#### 📌 Weitere Termine")
        for t in tasks:
            task_key = f"{module['id']}:task:{t['index']}"
            st.markdown(f"- {mark(task_key)} **{t['title']}** "
                        f"({t['start']:%d.%m.} – {t['due']:%d.%m.%Y})")
    st.caption("Abhaken kannst du die Termine in der 🏠 Wochenübersicht – der Kapitelstatus unten wird automatisch "
               "aktualisiert.")


def render(cfg: dict, module_id: str) -> None:
    data = load_module(module_id)
    module = get_module(cfg, module_id)
    current = planner.current_chapter(cfg, module, data, today())

    st.subheader("📖 Vorlesungsverlauf")
    if current:
        st.info(f"Aktuelles Kapitel: **{chapter_label(data, current['id'])}**")
    _ablauf(cfg, module, data)

    st.markdown("#### 📚 Kapitel")

    st.caption("Kapitel, Wochen und Status direkt in der Tabelle bearbeiten. Neue Zeilen über ➕ hinzufügen.")
    df = pd.DataFrame([{
        "id": ch["id"],
        "Titel": ch["title"],
        "Woche": ch.get("week"),
        **{label: ch["status"][key] for key, label in CHAPTER_STATUS_FIELDS.items()},
    } for ch in data["chapters"]])
    edited = st.data_editor(
        df, key=f"syllabus_{module_id}", num_rows="dynamic", hide_index=True, width="stretch",
        column_config={
            "id": None,
            "Titel": st.column_config.TextColumn(required=True, width="large"),
            "Woche": st.column_config.NumberColumn(min_value=1, max_value=20, step=1),
        })
    if st.button("💾 Syllabus speichern", key=f"save_syllabus_{module_id}"):
        old = {ch["id"]: ch for ch in data["chapters"]}
        new_chapters = []
        for _, row in edited.iterrows():
            if pd.isna(row["Titel"]) or not str(row["Titel"]).strip():
                continue
            cid = row["id"] if isinstance(row["id"], str) and row["id"] else f"k{new_id()[:6]}"
            ch = old.get(cid, {"id": cid, "status": {}})
            ch["title"] = str(row["Titel"]).strip()
            ch["week"] = int(row["Woche"]) if pd.notna(row["Woche"]) else None
            ch["status"] = {key: bool(row[label]) if pd.notna(row[label]) else False for key, label in CHAPTER_STATUS_FIELDS.items()}
            new_chapters.append(ch)
        removed = set(old) - {ch["id"] for ch in new_chapters}
        data["removed_chapters"] = sorted(set(data.get("removed_chapters", [])) | removed)
        data["chapters"] = new_chapters
        save_module(module_id)
        st.success("Syllabus gespeichert.")
        st.rerun()

    st.subheader("📂 Unterlagen nach Kapitel")
    if not data["documents"]:
        st.caption("Noch keine Unterlagen. Lade PDFs im Reiter „Vorlesungsvorbereitung“ oder über den Bulk-Upload hoch.")
    for ch in data["chapters"] + [{"id": None, "title": "Ohne Kapitel"}]:
        docs = [d for d in data["documents"] if d.get("chapter_id") == ch["id"]]
        if not docs:
            continue
        with st.expander(f"{chapter_label(data, ch['id'])} – {len(docs)} Dokument(e)"):
            for doc in docs:
                c1, c2, c3, c4 = st.columns([5, 2, 2, 1])
                c1.markdown(f"📄 **{doc['filename']}**")
                c2.caption(doc_type_label(doc["doc_type"]))
                c3.caption(f"{doc['n_pages']} Seiten · {'✅ analysiert' if doc.get('analysis') else '—'}")
                if c4.button("🗑️", key=f"del_doc_{doc['id']}", help="Dokument löschen"):
                    delete_document(module_id, doc["id"])
                    st.rerun()
