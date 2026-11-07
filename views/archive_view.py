"""Einstellungen → Ausgeblendet: archivierte Karteikarten (nur lesen) mit Lernstand und Minithema."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from utils import mastery, migration, sessions, topics
from utils.storage import load_module


def render(cfg: dict) -> None:
    st.subheader(":material/inventory_2: Ausgeblendete Karteikarten")
    rows, problems = [], []
    for module in cfg["modules"]:
        data = load_module(module["id"])
        info = data.get("cards_archived")
        if info and migration.fingerprint(data.get("cards", []))["sha256"] != info.get("sha256") \
                and len(data.get("cards", [])) < info.get("count", 0):
            problems.append(module["short"])
        names = {lec["id"]: f"VL {lec['nr']}" for lec in sessions.lectures(cfg, module["id"], data)}
        mts = {m["id"]: m for m in topics.minitopics(data, include_excluded=True)}
        amap = data.get("archive_map") or {}
        for c in data.get("cards", []):
            hist = c.get("history") or []
            last = mastery.SELF_GRADES[mastery.ARCHIVE_GRADE.get(int(hist[-1]["grade"]), "schwer")] if hist else "–"
            mt = mts.get(amap.get(c["id"]))
            rows.append({"Modul": module["short"], "Vorlesung": names.get(c.get("unit"), ""), "Frage": c["front"],
                         "Antwort": c["back"], "Bewertungen": len(hist), "Zuletzt": last,
                         "Zuletzt gelernt": c.get("last_review") or "", "Minithema": mt["title"] if mt else ""})
    if problems:
        st.error("Achtung: In " + ", ".join(problems) + " fehlen Karten gegenüber dem Archiv-Stand. Das Backup liegt "
                 "unter data/backups/.")
    if not rows:
        st.caption("Keine Karteikarten vorhanden.")
        return
    backups = {load_module(m["id"]).get("cards_archived", {}).get("backup") for m in cfg["modules"]} - {None}
    st.caption(f"{len(rows)} Karten mit allen Bewertungen unverändert gespeichert"
               + (f" · Backup: data/{', '.join(sorted(backups))}" if backups else ""))
    df = pd.DataFrame(rows)
    c1, c2 = st.columns([1, 2])
    module = c1.selectbox("Modul", ["Alle"] + sorted(df["Modul"].unique()), key="arch_mod")
    query = c2.text_input("Suchen", key="arch_q", placeholder="Begriff in Frage oder Antwort")
    if module != "Alle":
        df = df[df["Modul"] == module]
    if query.strip():
        mask = df["Frage"].str.contains(query, case=False, regex=False) | \
            df["Antwort"].str.contains(query, case=False, regex=False)
        df = df[mask]
    st.dataframe(df, hide_index=True, width="stretch", height=min(480, 40 + 35 * len(df)),
                 column_config={"Frage": st.column_config.TextColumn(width="large"),
                                "Antwort": st.column_config.TextColumn(width="large")})
    st.caption("Umrechnung der alten Bewertungen: Gar nicht und Etwas = Schwer · Gut = Mittel · Perfekt = Einfach")
