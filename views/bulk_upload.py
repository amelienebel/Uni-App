"""Bulk-Upload: viele PDFs (oder ZIP-Ordner) automatisch Modul, Vorlesung bzw. Übung zuordnen."""

from __future__ import annotations

import hashlib
import zipfile

import pandas as pd
import streamlit as st

from utils import ai, units
from utils.config import get_module, module_label
from utils.learning import run_analysis
from utils.pdf_parser import (extract_pdf, guess_chapter_from_plan, guess_chapter_index,
                              guess_doc_type, guess_module,
                              pdfs_from_zip)
from utils.storage import add_document, load_module, save_module


def _collect(files) -> tuple[list[dict], list[str]]:
    items, errors = [], []
    for f in files:
        content = f.getvalue()
        if f.name.lower().endswith(".zip"):
            try:
                for inner_path, inner_bytes in pdfs_from_zip(content):
                    items.append({"path": f"{f.name}/{inner_path}", "name": inner_path.split("/")[-1],
                                  "content": inner_bytes})
            except zipfile.BadZipFile:
                errors.append(f"{f.name}: kein gültiges ZIP-Archiv")
        else:
            items.append({"path": f.name, "name": f.name, "content": content})
    return items, errors


def render(cfg: dict) -> None:
    st.title("Bulk-Upload")
    _upload_tab(cfg)


def _upload_tab(cfg: dict) -> None:
    st.markdown(
        "Lade ganze Wochenordner hoch – einzelne PDFs oder den **ZIP-Download eines Moodle-Ordners**. "
        "Die App ordnet jede Datei anhand von Dateiname, Ordnerpfad und Inhalt automatisch **Modul**, "
        "**Dokumenttyp** (Folien, Übungsblatt, Musterlösung, Altklausur) und **Kapitel** zu – und damit der "
        "passenden **Vorlesung bzw. Übung**. Du kannst die Zuordnung vor dem Import korrigieren. "
        "Von Folien wird direkt die Zusammenfassung erstellt.")
    if result := st.session_state.pop("bulk_result", None):
        st.success(f"✓ {result[0]} Datei(en) importiert"
                   + (f", {result[1]} Duplikat(e) übersprungen." if result[1] else "."))
        for err in result[2]:
            st.error(err)

    files = st.file_uploader("PDFs oder ZIP-Archive", type=["pdf", "zip"], accept_multiple_files=True,
                             key=f"bulk_files_{st.session_state.get('bulk_round', 0)}")
    if not files:
        with st.expander("Tipps für eine gute automatische Zuordnung"):
            st.markdown(
                "- Dateinamen wie `Mathe_VL03_Folien.pdf`, `ReWe_Uebungsblatt_4.pdf`, `IuF_Loesung_Blatt2.pdf`\n"
                "- Ordnerpfade aus Moodle werden mit ausgewertet, z. B. `Statistik/Woche 5/…`\n"
                "- Kapitelnummern werden aus `Kap`, `Kapitel`, `VL`, `Vorlesung`, `Blatt`, `Woche` … erkannt\n"
                "- Schlüsselwörter pro Modul lassen sich in `config.json` (Feld `keywords`) erweitern")
        return

    items, errors = _collect(files)
    for err in errors:
        st.error(err)
    if not items:
        st.warning("Keine PDFs gefunden.")
        return

    ids = [m["id"] for m in cfg["modules"]]
    module_names = {mid: module_label(cfg, mid, short=True) for mid in ids}
    type_names = cfg["document_types"]
    rows = []
    progress = st.progress(0.0, text="Analysiere Dateien …")
    for i, item in enumerate(items):
        extracted = extract_pdf(item["content"])
        item["extracted"] = extracted
        text = "\n".join(extracted["pages"])
        module_id, score = guess_module(item["path"], text, cfg["modules"])
        module_id = module_id or ids[0]
        chapters = load_module(module_id)["chapters"]
        planned_chapter = guess_chapter_from_plan(item["path"], get_module(cfg, module_id))
        chapter_ids = [ch["id"] for ch in chapters]
        chapter_nr = (chapter_ids.index(planned_chapter) + 1 if planned_chapter in chapter_ids
                      else guess_chapter_index(item["path"], text, chapters))
        rows.append({
            "Importieren": True,
            "Datei": item["path"],
            "Modul": module_names[module_id],
            "Typ": type_names[guess_doc_type(item["path"], text)],
            "Kapitel-Nr.": chapter_nr,
            "Seiten": len(extracted["pages"]),
            "Sicherheit": "hoch" if score >= 5 else "mittel" if score >= 2 else "niedrig – bitte prüfen",
            "_hash": hashlib.sha1(item["content"]).hexdigest(),
        })
        progress.progress((i + 1) / len(items), text=f"Analysiere {item['name']} …")
    progress.empty()

    st.markdown(f"#### Vorgeschlagene Zuordnung ({len(rows)} Datei(en))")
    st.caption("Kapitel-Nr. 0 = keinem Kapitel zuordnen. Doppelte Dateien (gleicher Inhalt) werden übersprungen.")
    edited = st.data_editor(
        pd.DataFrame(rows), hide_index=True, width="stretch", key="bulk_editor",
        column_config={
            "_hash": None,
            "Datei": st.column_config.TextColumn(disabled=True, width="large"),
            "Modul": st.column_config.SelectboxColumn(options=list(module_names.values()), required=True),
            "Typ": st.column_config.SelectboxColumn(options=list(type_names.values()), required=True),
            "Kapitel-Nr.": st.column_config.NumberColumn(min_value=0, max_value=30, step=1),
            "Seiten": st.column_config.NumberColumn(disabled=True),
            "Sicherheit": st.column_config.TextColumn(disabled=True),
        })

    if st.button("Ausgewählte Dateien importieren", type="primary"):
        name_to_id = {v: k for k, v in module_names.items()}
        type_to_key = {v: k for k, v in type_names.items()}
        imported, skipped, to_analyse, errors = 0, 0, [], []
        unit_cache: dict[str, tuple[list, list]] = {}
        for item, (_, row) in zip(items, edited.iterrows()):
            if not row["Importieren"]:
                continue
            module_id = name_to_id[row["Modul"]]
            data = load_module(module_id)
            existing_hashes = {d.get("hash") for d in data["documents"]}
            if row["_hash"] in existing_hashes:
                skipped += 1
                continue
            chapter_nr = int(row["Kapitel-Nr."] or 0)
            chapter_id = data["chapters"][chapter_nr - 1]["id"] if 1 <= chapter_nr <= len(data["chapters"]) else None
            if module_id not in unit_cache:
                unit_cache[module_id] = units.all_units(cfg, get_module(cfg, module_id), data)
            doc_type = type_to_key[row["Typ"]]
            unit = units.guess_unit(item["path"], doc_type, chapter_id, *unit_cache[module_id])
            doc = add_document(module_id, item["name"], item["content"], doc_type, chapter_id,
                               extracted=item["extracted"], unit=unit)
            doc["hash"] = row["_hash"]
            save_module(module_id)
            imported += 1
            if doc_type == "folien" and doc["n_chars"] >= 50:
                to_analyse.append((module_id, doc))
        if to_analyse:
            bar = st.progress(0.0, text="Erstelle Zusammenfassungen der Folien …")
            for i, (module_id, doc) in enumerate(to_analyse):
                bar.progress(i / len(to_analyse), text=f"Fasse {doc['filename']} zusammen …")
                try:
                    run_analysis(cfg, module_id, doc)
                except ai.AIError as exc:
                    errors.append(f"{doc['filename']}: Zusammenfassung fehlgeschlagen – {exc}")
            bar.empty()
        st.session_state["bulk_round"] = st.session_state.get("bulk_round", 0) + 1
        st.session_state["bulk_result"] = (imported, skipped, errors)
        st.rerun()


