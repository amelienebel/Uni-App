"""Reiter: Syllabus & Kapitel."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from utils import planner
from utils.storage import (CHAPTER_STATUS_FIELDS, chapter_label, delete_document, load_module, new_id, save_module,
                           today)
from views.common import doc_type_label


def render(cfg: dict, module_id: str) -> None:
    data = load_module(module_id)
    current_week = planner.current_lecture_week(cfg, today())
    current = planner.chapter_for_week(data["chapters"], current_week)

    st.subheader("📖 Vorlesungsverlauf")
    if current:
        st.info(f"Aktuell (Vorlesungswoche {current_week}): **{chapter_label(data, current['id'])}**")

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
