"""BWL-Lernplattform LMU – Haupteinstieg.

Start:  streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="BWL-Lernplattform LMU", page_icon="🎓", layout="wide",
                   initial_sidebar_state="expanded")

from utils import ai, storage  # noqa: E402  (set_page_config muss zuerst kommen)
from utils import spaced_repetition as sr  # noqa: E402
from utils.config import WEEKDAYS, load_config, module_ids, module_label  # noqa: E402
from views import bulk_upload, dashboard, export_view, formulas, module_view, settings_view  # noqa: E402
from views.common import NAV_PAGES  # noqa: E402

storage.ensure_dirs()
cfg = load_config()
ids = module_ids(cfg)

st.markdown("""
<style>
  div[data-testid="stMetricValue"] { font-size: 1.6rem; }
  .small-muted { color: #888; font-size: 0.85rem; }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.title("🎓 BWL @ LMU")
    st.caption(f"{cfg['app'].get('semester_label', '')} · {WEEKDAYS[storage.today().weekday()]}, {storage.today():%d.%m.%Y}")
    page = st.radio("Hauptnavigation", NAV_PAGES, key="nav", label_visibility="collapsed")

    module_id = None
    if page == NAV_PAGES[1]:
        if st.session_state.get("nav_module") not in ids:
            st.session_state["nav_module"] = ids[0]
        module_id = st.selectbox("📚 Modul wählen", ids, key="nav_module",
                                 format_func=lambda mid: module_label(cfg, mid))

    st.divider()
    st.markdown("**⏳ Nächste Klausuren**")
    upcoming = []
    for mid in ids:
        days = storage.days_until_exam(mid)
        if days is not None and days >= 0:
            upcoming.append((days, mid))
    if upcoming:
        for days, mid in sorted(upcoming)[:5]:
            st.markdown(f"{sr.exam_pressure(days)['label'].split(' ')[0]} {module_label(cfg, mid, short=True)}: "
                        f"**{days}** Tage")
    else:
        st.caption("Noch keine Klausurtermine – unter ⚙️ Einstellungen eintragen.")

    st.divider()
    if ai.is_available():
        model, _ = ai._settings()
        st.success(f"KI aktiv · {model}", icon="🤖")
    else:
        st.warning("Kein API-Key – Offline-Modus", icon="🔌")

if page == NAV_PAGES[0]:
    dashboard.render(cfg)
elif page == NAV_PAGES[1]:
    module_view.render(cfg, module_id)
elif page == NAV_PAGES[2]:
    formulas.render(cfg)
elif page == NAV_PAGES[3]:
    bulk_upload.render(cfg)
elif page == NAV_PAGES[4]:
    export_view.render(cfg)
else:
    settings_view.render(cfg)
