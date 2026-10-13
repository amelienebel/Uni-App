"""Export & Backup."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from utils.config import module_label
from utils.export import backup_zip, build_blocks, restore_zip, to_markdown, to_pdf
from utils.storage import load_module, reload_all


def render(cfg: dict) -> None:
    st.title(":material/download: Export & Backup")

    st.subheader("Lernunterlagen exportieren (Offline-Lernen)")
    ids = [m["id"] for m in cfg["modules"]]
    selected = st.multiselect("Module", ids, default=ids, format_func=lambda mid: module_label(cfg, mid))
    c = st.columns(4)
    include = {
        "summaries": c[0].checkbox("Zusammenfassungen", True),
        "notes": c[1].checkbox("Notizen", True),
        "formulas": c[2].checkbox("Formelsammlung", True),
        "cards": c[3].checkbox("Lernkarten", False),
    }
    if not selected:
        st.caption("Bitte mindestens ein Modul wählen.")
    else:
        modules_data = {mid: load_module(mid) for mid in selected}
        blocks = build_blocks(cfg, modules_data, selected, include)
        stamp = datetime.now().strftime("%Y-%m-%d")
        markdown = to_markdown(blocks)
        c1, c2 = st.columns(2)
        c1.download_button("Markdown (.md)", markdown.encode("utf-8"), file_name=f"lernexport_{stamp}.md",
                           mime="text/markdown", width="stretch",
                           help="Formeln als $$LaTeX$$ – ideal für Obsidian, Notion, Typora oder VS Code.")
        if c2.button("PDF erzeugen", width="stretch"):
            with st.spinner("Erzeuge PDF …"):
                st.session_state["export_pdf"] = to_pdf(blocks)
        if pdf := st.session_state.get("export_pdf"):
            c2.download_button("PDF herunterladen", pdf, file_name=f"lernexport_{stamp}.pdf",
                               mime="application/pdf", width="stretch")
            st.caption("Hinweis: Im PDF erscheinen Formeln als LaTeX-Quelltext. Für gerenderte Formeln den "
                       "Markdown-Export in einem Markdown-Editor mit Mathe-Unterstützung öffnen.")
        with st.expander("Vorschau"):
            st.markdown(markdown[:20000] + ("\n\n…" if len(markdown) > 20000 else ""))

    st.divider()
    st.subheader("Vollständiges Backup")
    st.markdown("Sichert den kompletten Ordner `data/` (Einstellungen, Notizen, Karten inkl. Lernstand, Uploads) als ZIP.")
    if st.button("Backup erstellen"):
        with st.spinner("Packe Daten …"):
            st.session_state["backup_zip"] = backup_zip()
    if backup := st.session_state.get("backup_zip"):
        st.download_button("Backup herunterladen", backup,
                           file_name=f"lernplattform_backup_{datetime.now():%Y-%m-%d_%H%M}.zip",
                           mime="application/zip")

    with st.expander("Backup wiederherstellen"):
        st.warning("Vorhandene Dateien mit gleichem Namen werden überschrieben.")
        upload = st.file_uploader("Backup-ZIP", type=["zip"], key="restore_zip")
        confirm = st.checkbox("Ich habe verstanden, dass aktuelle Daten überschrieben werden.")
        if st.button("Wiederherstellen", disabled=not (upload and confirm), type="primary"):
            try:
                count = restore_zip(upload.getvalue())
                reload_all()
                st.success(f"{count} Dateien wiederhergestellt.")
            except Exception as exc:  # noqa: BLE001 - Fehler verständlich anzeigen
                st.error(f"Wiederherstellung fehlgeschlagen: {exc}")
