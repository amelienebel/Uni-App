"""Einstellungen & Klausurtermine."""

from __future__ import annotations

from datetime import date, time

import pandas as pd
import requests
import streamlit as st

from utils import ai, notify
from utils.config import WEEKDAYS, module_label
from utils.storage import (get_exam_date, get_schedule, load_settings, save_settings,
                           semester_dates)


def render(cfg: dict) -> None:
    settings = load_settings()
    st.title(":material/settings: Einstellungen & Klausurtermine")
    ids = [m["id"] for m in cfg["modules"]]

    # --- Klausurtermine -----------------------------------------------------
    st.subheader("Klausurtermine")
    st.caption("Je näher die Klausur, desto häufiger fragt dich die App die Lernkarten des Fachs ab.")
    with st.form("exam_form"):
        new_dates = {}
        for mid in ids:
            entry = settings["exam_dates"].get(mid) or {}
            c1, c2, c3, c4 = st.columns([3, 2, 1, 2])
            c1.markdown(f"**{module_label(cfg, mid)}**")
            d = c2.date_input("Datum", value=get_exam_date(mid), key=f"exam_d_{mid}", format="DD.MM.YYYY",
                              label_visibility="collapsed")
            t = c3.text_input("Uhrzeit", entry.get("time", ""), key=f"exam_t_{mid}", placeholder="10:00",
                              label_visibility="collapsed")
            r = c4.text_input("Raum", entry.get("room", ""), key=f"exam_r_{mid}", placeholder="Raum",
                              label_visibility="collapsed")
            new_dates[mid] = {"date": d.isoformat() if d else "", "time": t, "room": r}
        if st.form_submit_button("Klausurtermine speichern", type="primary"):
            settings["exam_dates"] = new_dates
            save_settings()
            st.success("Gespeichert.")
            st.rerun()

    # --- Semester -------------------------------------------------------------
    st.subheader("Semester")
    start, end = semester_dates(cfg)
    with st.form("semester_form"):
        c1, c2 = st.columns(2)
        new_start = c1.date_input("Vorlesungsbeginn", start, format="DD.MM.YYYY")
        new_end = c2.date_input("Vorlesungsende", end, format="DD.MM.YYYY")
        if st.form_submit_button("Speichern"):
            if new_end <= new_start:
                st.error("Das Vorlesungsende muss nach dem Beginn liegen.")
            else:
                settings["semester_start"], settings["semester_end"] = new_start.isoformat(), new_end.isoformat()
                save_settings()
                st.success("Gespeichert.")

    # --- Stundenplan ----------------------------------------------------------
    st.subheader("Stundenplan")
    st.caption("Grundlage für Wochenübersicht und To-do-Fristen. Standardwerte stammen aus config.json – "
               "bitte an deinen LSF-Stundenplan anpassen.")
    names = {mid: module_label(cfg, mid, short=True) for mid in ids}
    rows = [{"Modul": names.get(e["module_id"], e["module_id"]), "Typ": e.get("type", "Vorlesung"),
             "Tag": WEEKDAYS[int(e.get("weekday", 0))], "Beginn": e.get("start", ""), "Ende": e.get("end", ""),
             "Raum": e.get("room", "")} for e in get_schedule(cfg)]
    edited = st.data_editor(
        pd.DataFrame(rows), num_rows="dynamic", hide_index=True, width="stretch", key="schedule_editor",
        column_config={
            "Modul": st.column_config.SelectboxColumn(options=list(names.values()), required=True),
            "Typ": st.column_config.SelectboxColumn(options=["Vorlesung", "Übung", "Tutorium", "Sonstiges"],
                                                    required=True),
            "Tag": st.column_config.SelectboxColumn(options=WEEKDAYS, required=True),
            "Beginn": st.column_config.TextColumn(help="Format HH:MM"),
            "Ende": st.column_config.TextColumn(help="Format HH:MM"),
        })
    c1, c2 = st.columns(2)
    if c1.button("Stundenplan speichern", type="primary"):
        name_to_id = {v: k for k, v in names.items()}
        schedule = []
        for _, row in edited.iterrows():
            if not row["Modul"] or not row["Tag"]:
                continue
            schedule.append({"module_id": name_to_id[row["Modul"]], "type": row["Typ"] or "Vorlesung",
                             "weekday": WEEKDAYS.index(row["Tag"]), "start": row["Beginn"] or "",
                             "end": row["Ende"] or "", "room": row["Raum"] or ""})
        settings["schedule"] = schedule
        save_settings()
        st.success("Stundenplan gespeichert.")
    if c2.button("↩ Auf config.json zurücksetzen"):
        settings["schedule"] = None
        save_settings()
        st.rerun()

    # --- Lernparameter ----------------------------------------------------------
    st.subheader("Lernparameter")
    learning = settings["learning"]
    with st.form("learning_form"):
        limit = st.number_input("Max. Wiederholungen pro Modul und Sitzung", 10, 500,
                                int(learning["daily_review_limit"]), step=10)
        days = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
        lines = []
        for m in cfg["modules"]:
            dl = m.get("deadlines", {})
            if dl:
                lines.append(f"- **{m['short']}**: vorbereiten {days[dl['prep_weekday']]} · nachbereiten "
                             f"{days[dl['review_weekday']]} · Übungsblatt {days[dl['exercise_weekday']]}")
        st.caption("Feste Fristen (in config.json → deadlines):\n" + "\n".join(lines))
        if st.form_submit_button("Speichern"):
            learning.update({"daily_review_limit": int(limit)})
            save_settings()
            st.success("Gespeichert.")

    # --- Push-Erinnerungen & Podcast ----------------------------------------------
    st.subheader(":material/notifications: Push-Erinnerungen")
    conf = notify.settings()
    st.markdown(
        "Erinnerungen ans Karteikarten-Lernen kommen über die kostenlose App **ntfy** aufs Handy:\n"
        "1. Lade **ntfy** aus dem App Store (Symbol: weiße Glocke auf grünem Grund) und öffne sie.\n"
        "2. Tippe auf **+**, gib als Thema genau das hier ein und tippe auf **Subscribe**:")
    st.code(conf["topic"], language=None)
    st.caption("Das Thema ist dein persönlicher, zufälliger Kanal – gib es nicht weiter.")
    with st.form("notify_form"):
        c1, c2 = st.columns(2)
        enabled = c1.toggle("Tägliche Erinnerung aktiv", value=conf["enabled"])
        hh, mm = (int(x) for x in conf["time"].split(":"))
        at = c2.time_input("Uhrzeit", value=time(hh, mm), step=900)
        if st.form_submit_button("Speichern", type="primary"):
            conf.update({"enabled": enabled, "time": f"{at:%H:%M}", "scheduled": {}})
            save_settings()
            st.success("Gespeichert. Die Erinnerungen der nächsten Tage werden beim nächsten Öffnen eingeplant.")
    if st.button("Testnachricht senden", icon=":material/send:"):
        try:
            notify.send(conf["topic"], "Amelies Lern-App", "Es klappt! Ab jetzt erinnere ich dich ans Lernen.")
            st.success("Gesendet – kommt sie auf dem Handy an?")
        except requests.RequestException as exc:
            st.error(f"Senden fehlgeschlagen: {exc}")
    st.caption("Die App plant beim Öffnen immer die nächsten 3 Tage ein. Öffnest du sie länger nicht, pausieren die "
               "Erinnerungen. Es wird nur erinnert, wenn Karteikarten fällig sind.")

    podcast_conf = settings.setdefault("podcast", {"auto": True})
    auto = st.toggle("Tages-Podcast automatisch erstellen, wenn ich „Heute“ öffne", value=podcast_conf.get("auto", True),
                     help="An Vorlesungstagen: ca. 10 Minuten Audio zu den Vorlesungen des Tages.")
    if auto != podcast_conf.get("auto", True):
        podcast_conf["auto"] = auto
        save_settings()

    # --- KI -----------------------------------------------------------------------
    st.subheader("KI-Einstellungen")
    if ai.is_available():
        st.success("API-Key aus `.env` geladen (wird aus Sicherheitsgründen nicht angezeigt).")
    else:
        st.warning("Kein API-Key gefunden. Lege im Projektordner eine Datei `.env` an:\n\n"
                   "```\nANTHROPIC_API_KEY=sk-ant-...\n```\n\nund starte die App neu. Ohne Key laufen "
                   "alle Funktionen im Offline-Modus (heuristische Analyse, keine Chats).")
    ai._settings()  # stellt ggf. auf die Modell-Mischung um
    with st.form("ai_form"):
        c1, c2, c3 = st.columns(3)
        models = list(ai.MODELS)
        model = c1.selectbox("Modell für alles (Zusammenfassungen, Podcast, Chat …)", models,
                             index=models.index(settings["ai"].get("model", ai.DEFAULT_MODEL))
                             if settings["ai"].get("model") in models else 1, format_func=ai.MODELS.get)
        model_cards = c3.selectbox("Modell für Karteikarten", models,
                                   index=models.index(settings["ai"].get("model_cards", ai.DEFAULT_CARDS_MODEL))
                                   if settings["ai"].get("model_cards") in models else 0, format_func=ai.MODELS.get)
        efforts = list(ai.EFFORTS)
        effort = c2.selectbox("Gründlichkeit (Effort)", efforts,
                              index=efforts.index(settings["ai"].get("effort", "medium"))
                              if settings["ai"].get("effort") in efforts else 1, format_func=ai.EFFORTS.get)
        visual = st.toggle("Folien immer genau lesen (Formeln, Tabellen & Grafiken; ca. 2–3× teurer pro Foliensatz)",
                           value=bool(settings["ai"].get("visual_pdf")),
                           help="Aus: schneller Textauszug. Einzelne Foliensätze kannst du auf der Vorlesungsseite "
                                "unter Vorbereiten → „Genau lesen“ trotzdem genau lesen lassen.")
        if st.form_submit_button("Speichern"):
            settings["ai"].update({"model": model, "model_cards": model_cards, "effort": effort,
                                   "visual_pdf": visual})
            save_settings()
            st.success("Gespeichert.")

    st.caption(f"Stand: {date.today():%d.%m.%Y} · Daten liegen lokal im Ordner `data/`.")
