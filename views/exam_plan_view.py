"""Klausur-Lernplan: alle Kapitel, Schwachstellen und Altklausuren verteilt auf die Tage bis zu den Klausuren."""

from __future__ import annotations

import re
from datetime import date

import streamlit as st

from utils import exam_plan
from utils.config import WEEKDAYS, get_module
from utils.storage import get_exam_date, load_extra, load_module, load_todos, save_extra, today
from views.common import micon, toggle_todo


def _settings() -> dict:
    conf = load_extra("exam_plan").setdefault("settings", {})
    exam_plan.start_of(conf)
    conf.setdefault("weekday_blocks", 2)
    conf.setdefault("weekend_blocks", 3)
    return conf


def render(cfg: dict) -> None:
    now = today()
    st.title(":material/event_note: Klausur-Lernplan")
    st.caption("Der Plan verteilt die Wiederholung aller Kapitel, deine Schwachstellen und Altklausuren auf die Tage "
               "bis zu den Klausuren. Ein Block ≈ 90 Minuten. Er passt sich täglich an: Erledigtes fällt heraus, "
               "Verpasstes wird neu verteilt.")
    conf = _settings()
    with st.expander("Einstellungen des Plans", icon=":material/tune:"):
        with st.form("plan_settings"):
            c1, c2, c3 = st.columns(3)
            start = c1.date_input("Start der Klausurphase", date.fromisoformat(conf["start"]), format="DD.MM.YYYY")
            wd = c2.number_input("Blöcke pro Werktag", 1, 6, int(conf["weekday_blocks"]))
            we = c3.number_input("Blöcke pro Wochenendtag", 1, 6, int(conf["weekend_blocks"]))
            if st.form_submit_button("Speichern", type="primary"):
                conf.update({"start": start.isoformat(), "weekday_blocks": int(wd), "weekend_blocks": int(we)})
                save_extra("exam_plan")
                st.rerun()

    modules_data = {m["id"]: load_module(m["id"]) for m in cfg["modules"]}
    state = load_todos()
    plan = exam_plan.build_plan(cfg, modules_data, state, date.fromisoformat(conf["start"]), now,
                                conf["weekday_blocks"], conf["weekend_blocks"])

    # --- Fortschritt -------------------------------------------------------------
    cols = st.columns(len(cfg["modules"]))
    for col, module in zip(cols, sorted(cfg["modules"], key=lambda m: get_exam_date(m["id"]) or date.max)):
        done, total = plan["progress"][module["id"]]
        exam = get_exam_date(module["id"])
        with col.container(key=f"tdrow_{module['id']}_planprog"):
            st.markdown(f"{micon(module)} **{module['short']}**")
            st.caption(f"Klausur {exam:%d.%m.}" if exam else "kein Termin")
            st.progress(done / total if total else 0, text=f"{done}/{total} Blöcke")
    if plan["unplanned"]:
        missing = ", ".join(f"{get_module(cfg, mid)['short']} ({n})" for mid, n in plan["unplanned"].items())
        st.warning(f"Nicht alles passt in die verbleibende Zeit: {missing}. Erhöhe die Blöcke pro Tag oder starte "
                   "früher.")
    if not plan["days"]:
        st.info("Keine anstehenden Klausuren mit Termin.")
        return

    # --- Tage ----------------------------------------------------------------------
    if date.fromisoformat(conf["start"]) > now:
        st.info(f"Vorschau – der Plan startet am {date.fromisoformat(conf['start']):%d.%m.%Y}. Bis dahin gilt dein "
                "Wochenplan; was du jetzt schon schaffst, kannst du hier vorab abhaken.")
    current_week = None
    for day in plan["days"]:
        week = day["date"].isocalendar()[1]
        if week != current_week:
            current_week = week
            st.markdown(f"#### Woche ab {day['date']:%d.%m.}")
        with st.container(border=True, key=f"planday_{day['date']:%Y%m%d}"):
            st.markdown(f"**{WEEKDAYS[day['date'].weekday()]}, {day['date']:%d.%m.}**"
                        + ("  · heute" if day["date"] == now else ""))
            if not day["items"]:
                st.caption("Frei / Puffer")
            for item in day["items"]:
                module = get_module(cfg, item["module_id"])
                if item["kind"] == "Klausur":
                    with st.container(key=f"tdrow_{module['id']}_exam_{day['date']:%Y%m%d}"):
                        st.markdown(f"{micon(module)} **Klausur {module['short']}**")
                    continue
                key = exam_plan.plan_key(item["module_id"], item["id"])
                wkey = f"plan_{re.sub(r'[^0-9A-Za-z]', '_', key)}"
                st.session_state[wkey] = bool(state.get(key))
                with st.container(key=f"tdrow_{module['id']}_pl_{day['date']:%Y%m%d}_{wkey}"):
                    st.checkbox(f"**{module['short']}** · {item['title']}", key=wkey, on_change=toggle_todo,
                                args=({"key": key, "module_id": module["id"]}, wkey))
