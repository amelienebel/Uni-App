"""📂 Bulk-Upload & Moodle-Import: viele PDFs (oder ZIP-Ordner) automatisch zuordnen."""

from __future__ import annotations

import hashlib
import zipfile
from datetime import timedelta

import pandas as pd
import streamlit as st

from utils.config import get_module, module_label
from utils.pdf_parser import (extract_pdf, find_formula_candidates, guess_chapter_from_plan, guess_chapter_index,
                              guess_doc_type, guess_module,
                              pdfs_from_zip)
from utils import moodle, planner
from utils.storage import (add_document, add_formulas, load_module, load_settings, save_module, save_settings,
                           semester_dates)


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


def _chapter_for_moodle_file(file: dict, module_cfg: dict, chapters: list[dict], sem_start) -> int:
    """Kapitel-Nr.: 1) Aktivitäts-/Dateiname laut Kursplan, 2) Datum des Moodle-Abschnitts, 3) Heuristik."""
    ids = [ch["id"] for ch in chapters]
    for name in (file["title"] + ".pdf", file["filename"]):
        chapter_id = guess_chapter_from_plan(name, module_cfg)
        if chapter_id in ids:
            return ids.index(chapter_id) + 1
    start = moodle.section_date(file["section"], sem_start)
    if start:
        monday = planner.monday_of(start)
        for lec in planner.lectures_of(module_cfg):
            if monday <= lec["date"] <= monday + timedelta(days=6) and lec.get("chapter_id") in ids:
                return ids.index(lec["chapter_id"]) + 1
    return guess_chapter_index(f"{file['section']}/{file['title']}", "", chapters)


def _moodle_tab(cfg: dict) -> None:
    if not moodle.is_configured():
        st.info("Noch nicht verbunden. Trage deinen Moodle-Sicherheitsschlüssel in den Streamlit-Secrets ein:\n\n"
                "```\nMOODLE_TOKEN = \"dein-schlüssel\"\n```\n\nDanach die App neu starten (Reboot).", icon="🔗")
        return
    settings = load_settings()
    course_map = settings.setdefault("moodle", {}).setdefault("course_map", {})
    names = {m["id"]: module_label(cfg, m["id"]) for m in cfg["modules"]}

    if st.button("🔄 Verbindung herstellen & Kurse laden", type="primary" if "moodle_courses" not in st.session_state
                 else "secondary"):
        with st.spinner("Verbinde mit Moodle …"):
            try:
                st.session_state["moodle_courses"] = moodle.MoodleClient().courses()
            except moodle.MoodleError as exc:
                st.error(str(exc))
    courses = st.session_state.get("moodle_courses")
    if not courses:
        st.caption("Klicke auf den Knopf, um deine Moodle-Kurse zu laden.")
        return
    st.success(f"Verbunden – {len(courses)} Kurse gefunden.")

    course_names = {c["id"]: c["fullname"] for c in courses}
    with st.expander("🔗 Zuordnung Fach ↔ Moodle-Kurs", expanded=not course_map):
        new_map = {}
        suggested = moodle.match_courses(cfg["modules"], courses)
        for module in cfg["modules"]:
            saved = course_map.get(module["id"])
            default = saved if saved in course_names else suggested.get(module["id"])
            options = [None] + list(course_names)
            new_map[module["id"]] = st.selectbox(
                names[module["id"]], options, index=options.index(default) if default in options else 0,
                format_func=lambda cid: "— kein Kurs —" if cid is None else course_names[cid],
                key=f"moodle_map_{module['id']}")
        if st.button("💾 Zuordnung speichern"):
            settings["moodle"]["course_map"] = {k: v for k, v in new_map.items() if v}
            save_settings()
            st.success("Gespeichert.")
            course_map = settings["moodle"]["course_map"]
    active_map = {k: v for k, v in new_map.items() if v}

    if st.button("🔎 Neue Dateien in Moodle suchen"):
        client = moodle.MoodleClient()
        sem_start, _ = semester_dates(cfg)
        rows, files = [], []
        type_names = cfg["document_types"]
        with st.spinner("Durchsuche Kurse …"):
            for module_id, course_id in active_map.items():
                module_cfg = get_module(cfg, module_id)
                data = load_module(module_id)
                known = {d.get("moodle_key") for d in data["documents"]}
                try:
                    course_files = client.course_pdfs(course_id)
                except moodle.MoodleError as exc:
                    st.error(f"{names[module_id]}: {exc}")
                    continue
                for f in course_files:
                    if f["key"] in known:
                        continue
                    files.append({**f, "module_id": module_id})
                    rows.append({
                        "Importieren": True,
                        "Fach": names[module_id],
                        "Abschnitt": f["section"],
                        "Datei": f["title"] if f["title"].lower().endswith(".pdf") else f"{f['title']} ({f['filename']})",
                        "Typ": type_names[guess_doc_type(f"{f['section']}/{f['title']}/{f['filename']}")],
                        "Kapitel-Nr.": _chapter_for_moodle_file(f, module_cfg, data["chapters"], sem_start),
                    })
        st.session_state["moodle_new"] = (files, rows)

    if "moodle_new" not in st.session_state:
        return
    files, rows = st.session_state["moodle_new"]
    if not files:
        st.success("✅ Alles aktuell – keine neuen Dateien in Moodle.")
        return
    st.markdown(f"#### {len(files)} neue Datei(en) gefunden")
    st.caption("Häkchen entfernen, was du nicht brauchst. Kapitel-Nr. 0 = ohne Kapitel. "
               "Gesperrte Dateien (z. B. Lösungen vor dem Freischaltdatum) werden übersprungen.")
    type_names = cfg["document_types"]
    edited = st.data_editor(
        pd.DataFrame(rows), hide_index=True, width="stretch", key="moodle_editor",
        column_config={
            "Fach": st.column_config.TextColumn(disabled=True),
            "Abschnitt": st.column_config.TextColumn(disabled=True),
            "Datei": st.column_config.TextColumn(disabled=True, width="large"),
            "Typ": st.column_config.SelectboxColumn(options=list(type_names.values()), required=True),
            "Kapitel-Nr.": st.column_config.NumberColumn(min_value=0, max_value=30, step=1),
        })
    if st.button("📥 Ausgewählte Dateien importieren", type="primary", key="moodle_import"):
        client = moodle.MoodleClient()
        type_to_key = {v: k for k, v in type_names.items()}
        imported, skipped = 0, []
        progress = st.progress(0.0)
        for i, (f, (_, row)) in enumerate(zip(files, edited.iterrows())):
            progress.progress((i + 1) / len(files), text=f"Lade {f['filename']} …")
            if not row["Importieren"]:
                continue
            try:
                content = client.download(f)
            except moodle.MoodleError as exc:
                skipped.append(str(exc))
                continue
            data = load_module(f["module_id"])
            digest = hashlib.sha1(content).hexdigest()
            existing = next((d for d in data["documents"] if d.get("hash") == digest), None)
            if existing:  # gleicher Inhalt schon vorhanden (z. B. per Hand hochgeladen)
                existing["moodle_key"] = f["key"]
                save_module(f["module_id"])
                continue
            nr = int(row["Kapitel-Nr."] or 0)
            chapter_id = data["chapters"][nr - 1]["id"] if 1 <= nr <= len(data["chapters"]) else None
            name = f["filename"] if f["title"].lower() in f["filename"].lower() else f"{f['title']} – {f['filename']}"
            doc = add_document(f["module_id"], name, content, type_to_key[row["Typ"]], chapter_id)
            doc.update({"hash": digest, "moodle_key": f["key"]})
            save_module(f["module_id"])
            imported += 1
        progress.empty()
        st.session_state.pop("moodle_new", None)
        st.session_state["moodle_result"] = (imported, skipped)
        st.rerun()


def render(cfg: dict) -> None:
    st.title("📂 Bulk-Upload & Moodle-Import")
    if result := st.session_state.pop("moodle_result", None):
        st.success(f"✅ {result[0]} Datei(en) aus Moodle importiert.")
        for msg in result[1]:
            st.caption(f"⏭️ {msg}")
    tab_moodle, tab_upload = st.tabs(["🔗 Direkt aus Moodle", "⬆️ Dateien hochladen"])
    with tab_moodle:
        _moodle_tab(cfg)
    with tab_upload:
        _upload_tab(cfg)


def _upload_tab(cfg: dict) -> None:
    st.markdown(
        "Lade ganze Wochenordner hoch – einzelne PDFs oder den **ZIP-Download eines Moodle-Ordners**. "
        "Die App ordnet jede Datei anhand von Dateiname, Ordnerpfad und Inhalt automatisch **Modul**, "
        "**Dokumenttyp** (Folien, Übungsblatt, Musterlösung, Altklausur) und **Kapitel** zu. "
        "Du kannst die Zuordnung vor dem Import korrigieren.")
    if result := st.session_state.pop("bulk_result", None):
        st.success(f"✅ {result[0]} Datei(en) importiert"
                   + (f", {result[1]} Duplikat(e) übersprungen." if result[1] else "."))

    files = st.file_uploader("PDFs oder ZIP-Archive", type=["pdf", "zip"], accept_multiple_files=True,
                             key=f"bulk_files_{st.session_state.get('bulk_round', 0)}")
    if not files:
        with st.expander("💡 Tipps für eine gute automatische Zuordnung"):
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
    extract_formulas = st.checkbox("Formeln direkt heuristisch extrahieren (ohne KI, kostenlos)", value=True)

    if st.button("📥 Ausgewählte Dateien importieren", type="primary"):
        name_to_id = {v: k for k, v in module_names.items()}
        type_to_key = {v: k for k, v in type_names.items()}
        imported, skipped = 0, 0
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
            doc = add_document(module_id, item["name"], item["content"], type_to_key[row["Typ"]], chapter_id,
                               extracted=item["extracted"])
            doc["hash"] = row["_hash"]
            save_module(module_id)
            if extract_formulas and doc["doc_type"] in ("folien", "skript", "loesung"):
                add_formulas(module_id, find_formula_candidates(item["extracted"]["pages"]),
                             f"{item['name']} (heuristisch)", chapter_id)
            imported += 1
        st.session_state["bulk_round"] = st.session_state.get("bulk_round", 0) + 1
        st.session_state["bulk_result"] = (imported, skipped)
        st.rerun()


