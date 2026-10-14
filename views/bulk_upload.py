"""Bulk-Upload: viele PDFs (oder ZIP-Ordner) automatisch Modul, Vorlesung bzw. Übung zuordnen."""

from __future__ import annotations

import hashlib
import zipfile

import streamlit as st

from utils import ai, units
from utils.config import get_module
from utils.learning import run_analysis
from utils.pdf_parser import (extract_pdf, guess_chapter_from_plan, guess_chapter_index,
                              guess_doc_type, guess_module,
                              pdfs_from_zip)
from utils.storage import add_document, load_module, save_module
from views.module_tabs.files import unit_label, unit_options


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
    st.title(":material/cloud_upload: Bulk-Upload")
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
                "- Dateinamen wie `Mathe_VL03_Folien.pdf`, `ExRW_Uebungsblatt_4.pdf`, `IuF_Loesung_Blatt2.pdf`\n"
                "- Ordnerpfade aus Moodle werden mit ausgewertet, z. B. `Statistik/Woche 5/…`\n"
                "- Kapitelnummern werden aus `Kap`, `Kapitel`, `VL`, `Vorlesung`, `Blatt`, `Woche` … erkannt\n"
                "- Schlüsselwörter pro Modul lassen sich in `config.json` (Feld `keywords`) erweitern")
        return

    round_no = st.session_state.get("bulk_round", 0)
    cache_key = f"bulk_items_{round_no}"
    signature = tuple((f.name, f.size) for f in files)
    if st.session_state.get(cache_key, {}).get("signature") != signature:
        items, errors = _collect(files)
        progress = st.progress(0.0, text="Analysiere Dateien …")
        unit_cache: dict[str, tuple[list, list]] = {}
        for i, item in enumerate(items):
            extracted = extract_pdf(item["content"])
            text = "\n".join(extracted["pages"])
            module_id, score = guess_module(item["path"], text, cfg["modules"])
            module_id = module_id or cfg["modules"][0]["id"]
            doc_type = guess_doc_type(item["path"], text)
            chapters = load_module(module_id)["chapters"]
            planned = guess_chapter_from_plan(item["path"], get_module(cfg, module_id))
            chapter_ids = [ch["id"] for ch in chapters]
            if planned not in chapter_ids:
                nr = guess_chapter_index(item["path"], text, chapters)
                planned = chapter_ids[nr - 1] if 1 <= nr <= len(chapter_ids) else None
            if module_id not in unit_cache:
                unit_cache[module_id] = units.all_units(cfg, get_module(cfg, module_id), load_module(module_id))
            item.update({"module_id": module_id, "doc_type": doc_type, "score": score,
                         "n_pages": len(extracted["pages"]),
                         "unit": units.guess_unit(item["path"], doc_type, planned, *unit_cache[module_id]),
                         "hash": hashlib.sha1(item["content"]).hexdigest()})
            del item["content"]  # Inhalt nicht im Sitzungsspeicher halten (Arbeitsspeicher!)
            del extracted
            progress.progress((i + 1) / len(items), text=f"Analysiere {item['name']} …")
        progress.empty()
        st.session_state[cache_key] = {"signature": signature, "items": items, "errors": errors}
    items = st.session_state[cache_key]["items"]
    for err in st.session_state[cache_key]["errors"]:
        st.error(err)
    if not items:
        st.warning("Keine PDFs gefunden.")
        return

    ids = [m["id"] for m in cfg["modules"]]
    type_names = cfg["document_types"]
    st.markdown(f"#### Vorgeschlagene Zuordnung ({len(items)} Datei(en))")
    st.caption("Prüfe Modul, Typ und Vorlesung/Übung und ändere sie bei Bedarf. Doppelte Dateien (gleicher Inhalt) "
               "werden übersprungen.")
    for i, item in enumerate(items):
        k = f"{round_no}_{i}"
        sicher = "hoch" if item["score"] >= 5 else "mittel" if item["score"] >= 2 else "niedrig – bitte prüfen"
        with st.container(border=True):
            top = st.columns([5, 1], vertical_alignment="center")
            top[0].markdown(f"**{item['name']}**  \n<span class='small-muted'>{item['path']} · "
                            f"{item['n_pages']} Seiten · Sicherheit: {sicher}</span>",
                            unsafe_allow_html=True)
            top[1].checkbox("Importieren", value=True, key=f"bk_on_{k}")
            c1, c2, c3 = st.columns([1, 1, 2])
            c1.selectbox("Modul", ids, index=ids.index(item["module_id"]), key=f"bk_mod_{k}",
                         format_func=lambda mid: get_module(cfg, mid)["short"])
            mid = st.session_state.get(f"bk_mod_{k}", item["module_id"])
            c2.selectbox("Typ", list(type_names), index=list(type_names).index(item["doc_type"]),
                         key=f"bk_type_{k}", format_func=type_names.get)
            options, unit_map = unit_options(cfg, mid)
            default = item["unit"] if mid == item["module_id"] and item["unit"] in unit_map else None
            c3.selectbox("Gehört zu", options, index=options.index(default), key=f"bk_unit_{k}_{mid}",
                         format_func=lambda uid, m=unit_map: unit_label(m, uid))

    if st.button("Ausgewählte Dateien importieren", type="primary", icon=":material/download_done:"):
        imported, skipped, to_analyse, errors = 0, 0, [], []
        contents = {it["path"]: it["content"] for it in _collect(files)[0]}
        for i, item in enumerate(items):
            k = f"{round_no}_{i}"
            if not st.session_state.get(f"bk_on_{k}", True):
                continue
            module_id = st.session_state[f"bk_mod_{k}"]
            doc_type = st.session_state[f"bk_type_{k}"]
            data = load_module(module_id)
            if item["hash"] in {d.get("hash") for d in data["documents"]}:
                skipped += 1
                continue
            _, unit_map = unit_options(cfg, module_id)
            unit = unit_map.get(st.session_state.get(f"bk_unit_{k}_{module_id}"))
            content = contents.get(item["path"])
            if content is None:
                continue
            doc = add_document(module_id, item["name"], content, doc_type,
                               unit.get("chapter_id") if unit else None, unit=unit["id"] if unit else None)
            doc["hash"] = item["hash"]
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
        st.session_state.pop(cache_key, None)
        st.session_state["bulk_round"] = round_no + 1
        st.session_state["bulk_result"] = (imported, skipped, errors)
        st.rerun()
