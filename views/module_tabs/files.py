"""Dateien einer Vorlesung/Übung: Hochladen, Anzeigen, Herunterladen, Verschieben, Löschen."""

from __future__ import annotations

import streamlit as st

from utils import ai
from utils.learning import run_analysis
from utils.storage import IMAGE_TYPES, abs_data_path, add_file, delete_document, load_module, save_module
from utils.units import short_label
from views.common import doc_type_label


def _move(module_id: str, doc_id: str, widget_key: str, units_by_id: dict) -> None:
    data = load_module(module_id)
    target = units_by_id.get(st.session_state[widget_key])
    for doc in data["documents"]:
        if doc["id"] == doc_id and target:
            doc["unit"] = target["id"]
            doc["chapter_id"] = target.get("chapter_id")
    save_module(module_id)


def file_list(module_id: str, docs: list[dict], key: str, all_units: list[dict] | None = None,
              empty: str = "Noch keine Dateien.") -> None:
    if not docs:
        st.caption(empty)
        return
    units_by_id = {u["id"]: u for u in all_units or []}
    for doc in docs:
        try:
            path = abs_data_path(doc["path"])
            content = path.read_bytes()
        except (ValueError, OSError, KeyError):
            content = None
        c1, c2, c3 = st.columns([6, 1, 1], vertical_alignment="center")
        legacy = "" if doc.get("unit") else " · aus dem Kapitel"
        c1.markdown(f"**{doc['filename']}**  \n<span class='small-muted'>{doc_type_label(doc['doc_type'])}"
                    f"{' · ' + str(doc['n_pages']) + ' Seiten' if doc.get('n_pages') else ''}{legacy}</span>",
                    unsafe_allow_html=True)
        if content is not None:
            c2.download_button("Download", content, file_name=doc["filename"], key=f"dl_{key}_{doc['id']}",
                               mime=doc.get("mime", "application/pdf"), help="Herunterladen / öffnen")
        with c3.popover("⋯", help="Verschieben oder löschen"):
            if units_by_id:
                options = list(units_by_id)
                wkey = f"mv_{key}_{doc['id']}"
                current = doc.get("unit") if doc.get("unit") in units_by_id else options[0]
                st.selectbox("Gehört zu", options, index=options.index(current), key=wkey,
                             format_func=lambda uid: f"{short_label(units_by_id[uid])} – "
                                                     f"{units_by_id[uid].get('topic') or units_by_id[uid].get('title', '')}"[:80])
                st.button("Verschieben", key=f"mvb_{key}_{doc['id']}", on_click=_move,
                          args=(module_id, doc["id"], wkey, units_by_id))
            if st.button("Löschen", key=f"del_{key}_{doc['id']}", type="primary"):
                delete_document(module_id, doc["id"])
                st.rerun()
        if doc.get("kind") == "image" and content is not None:
            try:
                st.image(content, width=320)
            except Exception:  # noqa: BLE001 - beschädigtes/unbekanntes Bildformat
                st.caption("(Vorschau nicht möglich – Datei über öffnen)")


def uploader(cfg: dict, module_id: str, unit: dict, doc_type: str, label: str, key: str,
             allow_images: bool = False, analyse: bool = False) -> None:
    """Upload-Feld für einen Dateityp. Folien werden direkt nach dem Hochladen zusammengefasst."""
    counter_key = f"upround_{key}"
    types = ["pdf"] + (list(IMAGE_TYPES) if allow_images else [])
    files = st.file_uploader(label, type=types, accept_multiple_files=True,
                             key=f"up_{key}_{st.session_state.get(counter_key, 0)}")
    if not files:
        return
    messages = []
    for f in files:
        with st.spinner(f"Speichere {f.name} …"):
            doc = add_file(module_id, f.name, f.getvalue(), doc_type, unit.get("chapter_id"), unit["id"])
        if doc.get("kind") != "image" and doc["n_chars"] < 50:
            messages.append(("warning", f"{f.name}: kaum Text gefunden (gescanntes PDF?)."))
        if analyse and doc.get("kind") != "image":
            with st.spinner(f"Erstelle Zusammenfassung von {f.name} …" + (" (KI)" if ai.is_available() else "")):
                try:
                    messages.append(("success", f"{f.name}: {run_analysis(cfg, module_id, doc)}"))
                except ai.AIError as exc:
                    messages.append(("error", f"{f.name}: Zusammenfassung fehlgeschlagen – {exc}"))
    st.session_state[counter_key] = st.session_state.get(counter_key, 0) + 1
    st.session_state[f"upmsg_{module_id}"] = messages or [("success", f"{len(files)} Datei(en) gespeichert.")]
    st.rerun()


def show_messages(module_id: str) -> None:
    for kind, text in st.session_state.pop(f"upmsg_{module_id}", []):
        getattr(st, kind)(text)
