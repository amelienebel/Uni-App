"""Dateien einer Vorlesung/Übung: Hochladen, Anzeigen, Herunterladen, Verschieben, Löschen."""

from __future__ import annotations

import streamlit as st

from utils import ai
from utils.learning import run_analysis
from utils.config import get_module, load_config
from utils.storage import IMAGE_TYPES, abs_data_path, add_file, delete_document, load_module, update_document
from utils.units import short_label
from views.common import doc_type_label


def unit_options(cfg: dict, module_id: str) -> tuple[list, dict]:
    """Auswahlliste „Gehört zu“: keine Zuordnung + alle Vorlesungen und Übungen des Moduls."""
    from utils.units import all_units

    lecs, exs = all_units(cfg, get_module(cfg, module_id), load_module(module_id))
    units = {u["id"]: u for u in lecs + exs}
    return [None] + list(units), units


def unit_label(units: dict, uid: str | None) -> str:
    if uid is None or uid not in units:
        return "Keine Zuordnung"
    u = units[uid]
    return f"{short_label(u)} – {u.get('topic') or u.get('title', '')}"[:90]


def _save_edit(cfg: dict, module_id: str, doc_id: str, key: str) -> None:
    new_mid = st.session_state[f"ed_mod_{key}"]
    unit_id = st.session_state.get(f"ed_unit_{key}_{new_mid}")
    _, units = unit_options(cfg, new_mid)
    unit = units.get(unit_id)
    update_document(module_id, doc_id, new_mid, st.session_state[f"ed_type_{key}"], unit["id"] if unit else None,
                    unit.get("chapter_id") if unit else None)
    st.session_state["files_msg"] = "Zuordnung gespeichert."


def doc_editor(cfg: dict, module_id: str, doc: dict, key: str) -> None:
    """Modul, Typ und Vorlesung/Übung einer Datei ändern oder sie löschen (im ⋯-Menü)."""
    ids = [m["id"] for m in cfg["modules"]]
    st.selectbox("Modul", ids, index=ids.index(module_id), key=f"ed_mod_{key}",
                 format_func=lambda mid: get_module(cfg, mid)["short"])
    new_mid = st.session_state.get(f"ed_mod_{key}", module_id)
    types = cfg["document_types"]
    st.selectbox("Typ", list(types), index=list(types).index(doc["doc_type"]) if doc["doc_type"] in types else 0,
                 key=f"ed_type_{key}", format_func=types.get)
    options, units = unit_options(cfg, new_mid)
    current = doc.get("unit") if new_mid == module_id and doc.get("unit") in units else None
    st.selectbox("Gehört zu", options, index=options.index(current), key=f"ed_unit_{key}_{new_mid}",
                 format_func=lambda uid: unit_label(units, uid))
    b1, b2 = st.columns(2)
    b1.button("Speichern", key=f"ed_save_{key}", type="primary", on_click=_save_edit,
              args=(cfg, module_id, doc["id"], key))
    if b2.button("Löschen", key=f"ed_del_{key}"):
        delete_document(module_id, doc["id"])
        st.rerun()


def file_list(module_id: str, docs: list[dict], key: str, all_units: list[dict] | None = None,
              empty: str = "Noch keine Dateien.", cfg: dict | None = None, show_unit: bool = False) -> None:
    if msg := st.session_state.pop("files_msg", None):
        st.success(msg)
    if not docs:
        st.caption(empty)
        return
    cfg = cfg or load_config()
    units = unit_options(cfg, module_id)[1] if show_unit else {}
    for doc in docs:
        try:
            content = abs_data_path(doc["path"]).read_bytes()
        except (ValueError, OSError, KeyError):
            content = None
        c1, c2, c3 = st.columns([6, 1.3, 1], vertical_alignment="center")
        extra = ""
        if show_unit:
            extra = f" · {unit_label(units, doc.get('unit'))}" if doc.get("unit") else " · nicht zugeordnet"
        elif not doc.get("unit"):
            extra = " · aus dem Kapitel"
        c1.markdown(f"**{doc['filename']}**  \n<span class='small-muted'>{doc_type_label(doc['doc_type'])}"
                    f"{' · ' + str(doc['n_pages']) + ' Seiten' if doc.get('n_pages') else ''}{extra}</span>",
                    unsafe_allow_html=True)
        if content is not None:
            c2.download_button("Öffnen", content, file_name=doc["filename"], key=f"dl_{key}_{doc['id']}",
                               mime=doc.get("mime", "application/pdf"), icon=":material/download:")
        with c3.popover("⋯", help="Zuordnung ändern oder löschen"):
            doc_editor(cfg, module_id, doc, f"{key}_{doc['id']}")
        if doc.get("kind") == "image" and content is not None:
            try:
                st.image(content, width=320)
            except Exception:  # noqa: BLE001 - beschädigtes/unbekanntes Bildformat
                st.caption("(Vorschau nicht möglich – Datei über Öffnen herunterladen)")


def all_files(cfg: dict, module_id: str) -> None:
    """Reiter „Dateien“ im Modul: alle Unterlagen, nicht zugeordnete zuerst."""
    data = load_module(module_id)
    docs = [d for d in data["documents"] if d["doc_type"] != "altklausur"]
    options, units = unit_options(cfg, module_id)
    order = {uid: i for i, uid in enumerate(options[1:])}
    unassigned = [d for d in docs if d.get("unit") not in units]
    assigned = sorted((d for d in docs if d.get("unit") in units), key=lambda d: order[d["unit"]])
    st.caption("Alle Dateien dieses Moduls. Über ⋯ kannst du Modul, Typ und Vorlesung/Übung ändern oder löschen. "
               "Altklausuren findest du unter „Lernen & Klausur“.")
    if unassigned:
        st.markdown(f"#### :material/help: Nicht zugeordnet ({len(unassigned)})")
        file_list(module_id, unassigned, key="allun", cfg=cfg, show_unit=True)
    st.markdown(f"#### :material/folder_open: Zugeordnet ({len(assigned)})")
    file_list(module_id, assigned, key="allas", cfg=cfg, show_unit=True, empty="Noch keine zugeordneten Dateien.")


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
