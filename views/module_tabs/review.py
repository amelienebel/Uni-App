"""Reiter: Nachbereitung – Notizen, Tafelbilder, Dozenten-Feedback, Audio-Pitch."""

from __future__ import annotations

import re
from pathlib import Path

import streamlit as st

from utils import ai, planner
from utils.config import get_module
from utils.storage import (abs_data_path, chapter_label, delete_data_file, get_notes, load_module, save_module,
                           save_upload, today)
from views.common import chapter_select, tts_player

IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}

PITCH_PROMPT = """Erstelle einen kurzen „Audio-Pitch“ (ca. 150–200 Wörter, gesprochene Sprache, keine Formeln
in LaTeX – Formeln in Worten ausdrücken, keine Aufzählungszeichen) zur Vorlesung „{chapter}“ im Modul „{module}“.
Er soll sich gut zum Anhören in der U-Bahn eignen: Worum ging es? Was hat der Dozent besonders betont?
Welche Beispiele merke ich mir? Was ist klausurrelevant? Schließe mit einem Merksatz.

Meine Notizen:
{notes}

Vom Dozenten betont:
{emphasized}

Nur kurz angerissen:
{briefly}

Genannte Beispiele:
{examples}

Zusammenfassung der Folien (falls vorhanden):
{summaries}"""


def _offline_pitch(notes: dict, chapter: str) -> str:
    def first_sentences(text: str) -> str:
        sentences = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
        return " ".join(s.strip(" -•") for s in sentences if s.strip())[:600] if text else ""

    parts = [f"Kurz zusammengefasst: In der Vorlesung zu {chapter} ging es um folgendes."]
    if notes["text"]:
        parts.append(first_sentences(notes["text"]))
    if notes["emphasized"]:
        parts.append("Besonders betont wurde: " + first_sentences(notes["emphasized"]))
    if notes["examples"]:
        parts.append("Als Beispiele wurden genannt: " + first_sentences(notes["examples"]))
    if notes["briefly"]:
        parts.append("Nur kurz angerissen, also eher weniger klausurrelevant: " + first_sentences(notes["briefly"]))
    return " ".join(parts)


def render(cfg: dict, module_id: str) -> None:
    module = get_module(cfg, module_id)
    data = load_module(module_id)
    current = planner.current_chapter(cfg, module, data, today())

    st.subheader("📝 Vorlesung nachbereiten")
    if not data["chapters"]:
        st.info("Lege zuerst im Reiter „Syllabus & Kapitel“ Kapitel an.")
        return
    chapter_id = chapter_select(data, f"rev_ch_{module_id}", default=current["id"] if current else None)
    notes = get_notes(data, chapter_id)
    chapter = next(ch for ch in data["chapters"] if ch["id"] == chapter_id)

    with st.form(f"notes_form_{module_id}_{chapter_id}"):
        text = st.text_area("🗒️ Eigene Vorlesungsnotizen", notes["text"], height=220,
                            placeholder="Was habe ich mitgeschrieben? Formeln gern in LaTeX: $C_0 = ...$")
        c1, c2, c3 = st.columns(3)
        emphasized = c1.text_area("📢 Vom Dozenten betont", notes["emphasized"], height=140,
                                  placeholder="„Das kommt dran!“, Wiederholungen, Tafelanschrieb …")
        briefly = c2.text_area("💨 Nur kurz angerissen", notes["briefly"], height=140,
                               placeholder="Folien übersprungen, „nur zur Info“ …")
        examples = c3.text_area("💡 Genannte Beispiele", notes["examples"], height=140,
                                placeholder="Rechenbeispiele, Unternehmen, Fallstudien …")
        mark_done = st.checkbox("Kapitel als nachbereitet markieren", value=chapter["status"]["nachbereitet"])
        if st.form_submit_button("💾 Speichern", type="primary"):
            notes.update({"text": text, "emphasized": emphasized, "briefly": briefly, "examples": examples})
            chapter["status"]["nachbereitet"] = mark_done
            save_module(module_id)
            st.success("Notizen gespeichert.")

    if notes["text"].strip():
        with st.expander("👁️ Vorschau der Notizen (mit Formel-Rendering)"):
            st.markdown(notes["text"])

    # --- Tafelbilder -----------------------------------------------------------
    st.markdown("#### 📸 Tafelbilder & Screenshots")
    images = st.file_uploader("Bilder hochladen", type=list(IMAGE_TYPES), accept_multiple_files=True,
                              key=f"img_up_{module_id}_{chapter_id}_{len(notes['images'])}")
    if images and st.button("Bilder speichern", key=f"img_save_{module_id}_{chapter_id}"):
        for img in images:
            notes["images"].append({"path": save_upload(module_id, img.name, img.getvalue(), "images"),
                                    "name": img.name, "transcript": ""})
        save_module(module_id)
        st.rerun()

    if notes["images"]:
        cols = st.columns(3)
        for i, img in enumerate(list(notes["images"])):
            with cols[i % 3]:
                try:
                    path = abs_data_path(img["path"])
                except ValueError:
                    continue
                if path.exists():
                    st.image(str(path), caption=img["name"], width="stretch")
                b1, b2 = st.columns(2)
                if ai.is_available() and b1.button("🔍 Transkribieren", key=f"tr_{module_id}_{chapter_id}_{i}"):
                    ext = Path(img["name"]).suffix.lower().lstrip(".")
                    with st.spinner("Lese Tafelbild …"):
                        try:
                            img["transcript"] = ai.complete([
                                ai.image_block(path.read_bytes(), IMAGE_TYPES.get(ext, "image/png")),
                                {"type": "text", "text": "Transkribiere dieses Tafelbild/diesen Screenshot aus einer "
                                 f"Vorlesung „{module['name']}“ vollständig. Formeln in LaTeX ($...$), "
                                 "Skizzen kurz in Worten beschreiben."},
                            ], max_tokens=8000)
                            save_module(module_id)
                        except ai.AIError as exc:
                            st.error(str(exc))
                if b2.button("🗑️", key=f"del_img_{module_id}_{chapter_id}_{i}"):
                    delete_data_file(img["path"])
                    notes["images"].remove(img)
                    save_module(module_id)
                    st.rerun()
                if img.get("transcript"):
                    with st.expander("Transkript"):
                        st.markdown(img["transcript"])
                        if st.button("➕ In Notizen übernehmen", key=f"tr_add_{module_id}_{chapter_id}_{i}"):
                            notes["text"] = (notes["text"] + "\n\n" + img["transcript"]).strip()
                            save_module(module_id)
                            st.rerun()

    # --- Audio-Pitch -------------------------------------------------------------
    st.markdown("#### 🎧 Audio-Pitch")
    st.caption("Wird nur auf Klick erzeugt, um API-Tokens zu sparen. Vorlesen erfolgt lokal im Browser.")
    if st.button("🎙️ Audio-Pitch generieren", key=f"pitch_{module_id}_{chapter_id}"):
        if not any(notes[k].strip() for k in ("text", "emphasized", "briefly", "examples")):
            st.warning("Bitte zuerst Notizen speichern – der Pitch basiert darauf.")
        elif ai.is_available():
            summaries = "\n\n".join(d["analysis"].get("summary", "") for d in data["documents"]
                                    if d.get("chapter_id") == chapter_id and d.get("analysis"))
            with st.spinner("Erzeuge Pitch …"):
                try:
                    notes["pitch"] = ai.complete(PITCH_PROMPT.format(
                        chapter=chapter_label(data, chapter_id), module=module["name"], notes=notes["text"] or "-",
                        emphasized=notes["emphasized"] or "-", briefly=notes["briefly"] or "-",
                        examples=notes["examples"] or "-", summaries=summaries or "-"),
                        max_tokens=4000, effort="low")
                    save_module(module_id)
                except ai.AIError as exc:
                    st.error(str(exc))
        else:
            notes["pitch"] = _offline_pitch(notes, chapter["title"])
            save_module(module_id)
    if notes["pitch"]:
        st.markdown(f"> {notes['pitch']}")
        tts_player(notes["pitch"], key=f"{module_id}_{chapter_id}")
