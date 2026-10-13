"""BWL-Lernplattform LMU – Haupteinstieg.

Start:  streamlit run app.py
"""

from __future__ import annotations

import hashlib
import hmac

import streamlit as st

st.set_page_config(page_title="BWL-Lernplattform LMU", page_icon="🎓", layout="wide",
                   initial_sidebar_state="auto")

from utils import ai, cloud_sync, storage  # noqa: E402  (set_page_config muss zuerst kommen)
from utils.config import WEEKDAYS, get_secret, load_config, module_ids, module_label  # noqa: E402
from views import bulk_upload, dashboard, export_view, formulas, module_view, settings_view  # noqa: E402
from views.common import NAV_PAGES, open_unit  # noqa: E402



def require_login() -> None:
    """Passwortschutz, sobald APP_PASSWORD gesetzt ist (wichtig, wenn die App online erreichbar ist).

    „Angemeldet bleiben“ hängt einen Zugangsschlüssel an die Adresse. Wird die Seite danach als
    App-Symbol auf dem Home-Bildschirm/im Dock abgelegt, entfällt die Passworteingabe.
    """
    password = get_secret("APP_PASSWORD")
    if not password:
        return
    token = hmac.new(password.encode(), b"bwl-lernplattform", hashlib.sha256).hexdigest()[:32]
    url_token = st.query_params.get("zugang", "")
    if st.session_state.get("auth_ok") or hmac.compare_digest(url_token.encode(), token.encode()):
        st.session_state["auth_ok"] = True
        return
    st.title("🔒 BWL-Lernplattform")
    with st.form("login"):
        entered = st.text_input("Passwort", type="password")
        remember = st.checkbox("Auf diesem Gerät angemeldet bleiben", value=True)
        submitted = st.form_submit_button("Anmelden", type="primary")
    if submitted:
        if hmac.compare_digest(entered.encode(), password.encode()):
            st.session_state["auth_ok"] = True
            if remember:
                st.query_params["zugang"] = token
            st.rerun()
        st.error("Falsches Passwort.")
    st.stop()


require_login()
storage.ensure_dirs()
if cloud_sync.is_configured():
    with st.spinner("☁️ Lade deine Daten aus dem Cloud-Speicher …"):
        cloud_sync.ensure_started(storage.DATA_DIR)
cfg = load_config()
ids = module_ids(cfg)

st.markdown("""
<style>
  div[data-testid="stMetricValue"] { font-size: 1.6rem; }
  .small-muted { color: #888; font-size: 0.85rem; }
  /* Modul-Unterpunkte in der Seitenleiste: eingerückt, linksbündig */
  [class*="st-key-navmod_"] button { justify-content: flex-start; padding-left: 1.6rem; min-height: 2rem; }
  [class*="st-key-navmod_"] button div, [class*="st-key-row_"] button div { justify-content: flex-start;
    text-align: left; }
  [class*="st-key-row_"] button { justify-content: flex-start; text-align: left; }
  [class*="st-key-row_"] { margin-bottom: -0.6rem; }
  [class*="st-key-nextbox_"] { background: rgba(28, 131, 225, 0.09); border-color: rgba(28, 131, 225, 0.35) !important; }
  [class*="st-key-nextbox_"] h4 { padding: 0.2rem 0 0 0; }
  /* Handy: weniger Rand, kleinere Überschriften, Reiter horizontal scrollbar */
  @media (max-width: 640px) {
    .block-container { padding: 2.8rem 0.7rem 4rem 0.7rem !important; }
    h1 { font-size: 1.55rem !important; }
    h2, h3 { font-size: 1.2rem !important; }
    div[data-testid="stMetricValue"] { font-size: 1.25rem; }
    div[data-baseweb="tab-list"] { overflow-x: auto; }
  }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.title("🎓 BWL @ LMU")
    st.caption(f"{cfg['app'].get('semester_label', '')} · {WEEKDAYS[storage.today().weekday()]}, {storage.today():%d.%m.%Y}")
    page = st.radio("Hauptnavigation", NAV_PAGES, key="nav", label_visibility="collapsed")

    # Module direkt als Unterpunkte (ohne Aufklappen)
    if st.session_state.get("nav_module") not in ids:
        st.session_state["nav_module"] = ids[0]
    module_id = st.session_state["nav_module"]
    st.markdown("<div class='small-muted' style='margin:0.4rem 0 0.2rem 0'>Module</div>", unsafe_allow_html=True)
    for mid in ids:
        active = page == NAV_PAGES[1] and mid == module_id
        st.button(module_label(cfg, mid, short=True), key=f"navmod_{mid}", type="primary" if active else "tertiary",
                  width="stretch", on_click=open_unit, args=(mid, None))

    st.divider()
    st.markdown("**Nächste Klausuren**")
    upcoming = []
    for mid in ids:
        days = storage.days_until_exam(mid)
        if days is not None and days >= 0:
            upcoming.append((days, mid))
    if upcoming:
        for days, mid in sorted(upcoming)[:5]:
            st.markdown(f"{module_label(cfg, mid, short=True)}: **{days}** Tage")
    else:
        st.caption("Noch keine Klausurtermine – unter ⚙️ Einstellungen eintragen.")

    st.divider()
    sync_status = cloud_sync.status()
    if sync_status is None:
        st.caption("💾 Daten werden nur auf diesem Gerät gespeichert.")
    elif sync_status["fatal"]:
        st.error(sync_status["error"], icon="☁️")
    else:
        if sync_status["error"]:
            st.warning(sync_status["error"], icon="☁️")
        if sync_status["pending"]:
            st.caption(f"☁️ {sync_status['pending']} Änderung(en) werden in Kürze gesichert.")
            if st.button("Jetzt sichern", key="sync_now"):
                with st.spinner("Sichere …"):
                    cloud_sync.flush()
                st.rerun()
        elif not sync_status["error"]:
            st.caption("☁️ Alles im Cloud-Speicher gesichert.")
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
