"""BWL-Lernplattform LMU – Haupteinstieg.

Start:  streamlit run app.py
"""

from __future__ import annotations

import hashlib
import hmac

import streamlit as st

st.set_page_config(page_title="Amelies Lern-App", page_icon=":material/school:", layout="wide",
                   initial_sidebar_state="auto")

from utils import ai, cloud_sync, storage  # noqa: E402  (set_page_config muss zuerst kommen)
from utils.config import WEEKDAYS, get_module, get_secret, load_config, module_ids, module_label  # noqa: E402
from views import (bulk_upload, cards_center, dashboard, exam_plan_view, module_view,  # noqa: E402
                   quiz_center, settings_view, today_view)
from views.common import NAV_PAGES, PAGES, back_button, goto, micon, open_unit, track_history  # noqa: E402
from utils import upload_debug  # noqa: E402

upload_debug.install()



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
    st.title("Amelies Lern-App")
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
    with st.spinner("Lade deine Daten aus dem Cloud-Speicher …"):
        cloud_sync.ensure_started(storage.DATA_DIR)
cfg = load_config()
ids = module_ids(cfg)
# Nach einem Neuladen (z. B. nach längerer Pause) wieder auf derselben Seite landen: Seite/Modul/Einheit in der Adresse
if st.session_state.get("nav") not in NAV_PAGES:
    st.session_state["nav"] = PAGES.get(st.query_params.get("seite", ""), PAGES["today"])
    if st.query_params.get("einheit") and st.query_params.get("modul") in ids:
        st.session_state[f"unit_{st.query_params['modul']}"] = st.query_params["einheit"]
if st.session_state.get("nav_module") not in ids:
    st.session_state["nav_module"] = st.query_params.get("modul") if st.query_params.get("modul") in ids else ids[0]
track_history()
_page_key = next(k for k, v in PAGES.items() if v == st.session_state["nav"])
_where = {"seite": _page_key}
if _page_key == "module":
    _where["modul"] = st.session_state["nav_module"]
    if _unit := st.session_state.get(f"unit_{_where['modul']}"):
        _where["einheit"] = _unit
for _k in ("seite", "modul", "einheit"):
    if st.query_params.get(_k) != _where.get(_k):
        if _k in _where:
            st.query_params[_k] = _where[_k]
        else:
            st.query_params.pop(_k, None)

# Verbindung nach Pause automatisch wiederherstellen: Zeigt Streamlit länger „Verbindung verloren“ (Handy/Tab lag im
# Hintergrund, Server hat geschlafen), lädt die Seite selbst neu – Anmeldung und Seite bleiben über die Adresse erhalten.
with st.container(key="watchdog"):
    st.html("""<script>
(function () {
  document.cookie = "lernapp_mobile=" + (window.innerWidth < 700 ? "1" : "0") + "; path=/; max-age=31536000; SameSite=Lax";
  if (window.__lernAppWatchdog) return;
  window.__lernAppWatchdog = true;
  var lostSince = null, hiddenAt = null;
  function lost() { return !!document.querySelector('[data-testid="stConnectionStatus"]'); }
  function reload() {
    var last = Number(sessionStorage.getItem("lernAppReload") || 0);
    if (!navigator.onLine || Date.now() - last < 20000) return;
    // nur neu laden, wenn der Server erreichbar ist (sonst bliebe eine Fehlerseite stehen)
    fetch(new URL("_stcore/health", window.location.href), { cache: "no-store" }).then(function (r) {
      if (!r.ok || !lost()) return;
      sessionStorage.setItem("lernAppReload", String(Date.now()));
      window.location.reload();
    }).catch(function () {});
  }
  setInterval(function () {
    if (document.hidden) return;
    if (lost()) { lostSince = lostSince || Date.now(); if (Date.now() - lostSince > 5000) reload(); }
    else lostSince = null;
  }, 1500);
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) { hiddenAt = Date.now(); return; }
    if (hiddenAt && Date.now() - hiddenAt > 20 * 60 * 1000) setTimeout(function () { if (lost()) reload(); }, 2500);
  });
  window.addEventListener("online", function () { setTimeout(function () { if (lost()) reload(); }, 2500); });
})();
</script>""", unsafe_allow_javascript=True)
page = st.session_state["nav"]
module_id = st.session_state["nav_module"]
# Ablenkungsfreier Lernmodus: aktive Karten- oder Quiz-Session blendet Seitenleiste und Kopfzeile aus
focus = (page == PAGES["cards"] and cards_center.session_active()) or (page == PAGES["quiz"] and quiz_center.session_active())

st.markdown("""
<style>
  div[data-testid="stMetricValue"] { font-size: 1.6rem; }
  .small-muted { color: #888; font-size: 0.85rem; }
  /* Modul-Unterpunkte in der Seitenleiste: eingerückt, linksbündig */
  [class*="st-key-navmod_"] button { justify-content: flex-start; padding-left: 1.6rem; min-height: 2rem; }
  [data-testid="stSidebar"] h1 { font-size: 1.35rem; }
  [class*="st-key-navpage_"] button { justify-content: flex-start; min-height: 2.1rem; padding-left: 0.6rem; }
  [class*="st-key-navpage_"] button div { justify-content: flex-start; text-align: left; }
  [class*="st-key-navpage_"] { margin-bottom: -0.55rem; }
  [class*="st-key-navmod_"] { margin-bottom: -0.55rem; }
  [class*="st-key-navmod_"] button div, [class*="st-key-row_"] button div { justify-content: flex-start;
    text-align: left; }
  [class*="st-key-row_"] button { justify-content: flex-start; text-align: left; }
  [class*="st-key-row_"] { margin-bottom: -0.6rem; }
  [class*="st-key-nextbox_"] { background: rgba(28, 131, 225, 0.09); border-color: rgba(28, 131, 225, 0.35) !important; }
  [class*="st-key-nextbox_"] h4 { padding: 0.2rem 0 0 0; }
  [class*="st-key-hintbox_"] { background: rgba(217, 130, 43, 0.08); border-color: rgba(217, 130, 43, 0.55) !important; }
  /* Abhak-Knöpfe (erledigt / offen) */
  [class*="st-key-doneon_"] button, [class*="st-key-doneoff_"] button { border-radius: 999px; min-height: 2.2rem;
    justify-content: center; font-weight: 600; transition: all 0.15s ease; }
  [class*="st-key-doneon_"] button div, [class*="st-key-doneoff_"] button div { justify-content: center; }
  [class*="st-key-doneon_"] button { background: rgba(46, 160, 92, 0.16); border: 1px solid rgba(46, 160, 92, 0.6);
    color: #2e9d5b; }
  [class*="st-key-doneon_"] button span { color: #2e9d5b; }
  [class*="st-key-doneon_"] button:hover { background: rgba(46, 160, 92, 0.26); border-color: #2e9d5b; color: #2e9d5b; }
  [class*="st-key-doneoff_"] button { background: transparent; border: 1.5px dashed rgba(128, 128, 128, 0.55);
    color: inherit; opacity: 0.85; }
  [class*="st-key-doneoff_"] button:hover { border-style: solid; border-color: #2e9d5b; color: #2e9d5b; opacity: 1; }
  /* Allgemeines Design: ruhiger Kopf, Kacheln, Pillen-Reiter, weiche Übergänge */
  [data-testid="stAppDeployButton"], .st-key-watchdog { display: none; }
  .block-container { padding-top: 3rem; padding-bottom: 4rem; }
  .st-key-nav_back_btn button { min-height: 1.9rem; padding: 0.1rem 0.85rem; border-radius: 999px; font-size: 0.85rem; }
  .st-key-nav_back_btn { margin-bottom: -0.4rem; }
  [data-testid="stMetric"] { background: rgba(127, 127, 127, 0.06); border: 1px solid rgba(127, 127, 127, 0.16);
    border-radius: 0.8rem; padding: 0.7rem 1rem; }
  [data-testid="stTab"] { border-radius: 999px; padding: 0.25rem 0.85rem !important; margin-bottom: 0.3rem; }
  [data-testid="stTab"][aria-selected="true"] { background: rgba(91, 127, 204, 0.12); }
  [data-testid="stTab"]:hover { background: rgba(127, 127, 127, 0.08); }
  div[data-baseweb="tab-highlight"] { display: none; }
  div[data-baseweb="tab-list"] { gap: 0.25rem; }
  [data-testid="stExpander"] details { border-radius: 0.7rem; }
  [data-testid="stExpander"] summary:hover { background: rgba(127, 127, 127, 0.05); }
  .stButton button, .stFormSubmitButton button { transition: transform 0.08s ease, box-shadow 0.15s ease,
    background 0.15s ease; }
  .stButton button:active, .stFormSubmitButton button:active { transform: scale(0.98); }
  button[kind="primary"], button[kind="primaryFormSubmit"] { box-shadow: 0 1px 3px rgba(30, 60, 140, 0.22); }
  [class*="st-key-navpage_"] button, [class*="st-key-navmod_"] button { border-radius: 0.6rem; }
  [class*="st-key-fbbox_"] { background: rgba(91, 127, 204, 0.06); border-color: rgba(91, 127, 204, 0.4) !important; }
  [data-testid="stAlert"] { border-radius: 0.7rem; }
  /* Handy: weniger Rand, kleinere Überschriften, Reiter horizontal scrollbar, Zeilen kompakt nebeneinander */
  @media (max-width: 640px) {
    .block-container { padding: 2.8rem 0.7rem 4rem 0.7rem !important; }
    h1 { font-size: 1.55rem !important; }
    h2, h3 { font-size: 1.2rem !important; }
    div[data-testid="stMetricValue"] { font-size: 1.25rem; }
    [data-testid="stMetricLabel"] p { font-size: 0.78rem; }
    div[data-baseweb="tab-list"] { overflow-x: auto; flex-wrap: nowrap; }
    .st-key-kpis [data-testid="stHorizontalBlock"], .st-key-weeknav [data-testid="stHorizontalBlock"] {
      flex-wrap: nowrap !important; gap: 0.5rem; }
    .st-key-kpis [data-testid="stColumn"], .st-key-weeknav [data-testid="stColumn"] { min-width: 0 !important;
      flex: 1 1 0 !important; width: auto !important; }
    .st-key-kpis [data-testid="stColumn"]:nth-child(3), .st-key-weeknav [data-testid="stColumn"]:nth-child(4) {
      display: none; }
    [class*="st-key-tdrow_"][class*="_today_"] [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important;
      gap: 0 0.4rem; }
    [class*="st-key-tdrow_"][class*="_today_"] [data-testid="stColumn"] { min-width: 0 !important; width: auto !important; }
    [class*="st-key-tdrow_"][class*="_today_"] [data-testid="stColumn"]:nth-child(1) { flex: 0 0 1.6rem !important; }
    [class*="st-key-tdrow_"][class*="_today_"] [data-testid="stColumn"]:nth-child(2) {
      flex: 1 1 calc(100% - 2.2rem) !important; }
    [class*="st-key-tdrow_"][class*="_today_"] [data-testid="stColumn"]:nth-child(3) { flex: 1 1 0 !important;
      padding-left: 2rem; margin-top: -0.6rem; }
    [class*="st-key-tdrow_"][class*="_today_"] [data-testid="stColumn"]:nth-child(4) { flex: 0 0 auto !important; }
    button[kind="primary"], button[kind="secondary"] { min-height: 2.6rem; }
  }
</style>
""", unsafe_allow_html=True)

# Modulfarben: Symbole, Aufgaben, Kapitel und Kopfzeilen tragen die Farbe ihres Moduls
_rules = [
    "[data-testid='stIconMaterial'] {vertical-align: -0.18em;}",
    "h1 [data-testid='stIconMaterial'], h2 [data-testid='stIconMaterial'], h3 [data-testid='stIconMaterial'] "
    "{color: #5B7FCC; margin-right: 0.15em;}",
    ".exam-row {display: flex; align-items: center; gap: 0.55rem; padding: 0.2rem 0; font-size: 0.95rem;}",
    ".exam-row b {margin-left: auto; font-weight: 600;}",
    ".exam-row .dot {width: 0.6rem; height: 0.6rem; border-radius: 50%; display: inline-block;}",
]
for _m in cfg["modules"]:
    _id, _c = _m["id"], _m["color"]
    _rules += [
        f".st-key-navmod_{_id} button:not([kind='primary']) [data-testid='stIconMaterial'] {{color: {_c};}}",
        f".st-key-navmod_{_id} button[kind='primary'] {{background: {_c}; border-color: {_c};}}",
        f"[class*='st-key-evcard_{_id}_'] [data-testid='stIconMaterial'], "
        f"[class*='st-key-chip_open_{_id}_'] [data-testid='stIconMaterial'], "
        f"[class*='st-key-chip_done_{_id}_'] [data-testid='stIconMaterial'], "
        f"[class*='st-key-tdrow_{_id}_'] [data-testid='stIconMaterial'], "
        f"[class*='st-key-row_{_id}_'] [data-testid='stIconMaterial'], "
        f".st-key-modhead_{_id} h1 [data-testid='stIconMaterial'] {{color: {_c};}}",
        f"[class*='st-key-tdrow_{_id}_'] {{border-left: 3px solid {_c}; padding-left: 0.9rem;}}",
        f"[class*='st-key-chap_{_id}_'] {{border-left: 4px solid {_c} !important;}}",
        f"[class*='st-key-chip_open_{_id}_'] {{background: {_c}14;}}",
        f"[class*='st-key-chip_open_{_id}_'] strong, [class*='st-key-chip_done_{_id}_'] strong, "
        f"[class*='st-key-tdrow_{_id}_'] strong {{color: {_c};}}",
        f".st-key-modhead_{_id} {{border-bottom: 3px solid {_c}; padding-bottom: 0.3rem; margin-bottom: 0.4rem;}}",
    ]
st.markdown(f"<style>{' '.join(_rules)}</style>", unsafe_allow_html=True)


def sidebar() -> None:
    st.title(":material/school: Amelies Lern-App")
    st.caption(f"{cfg['app'].get('semester_label', '')} · {WEEKDAYS[storage.today().weekday()]}, {storage.today():%d.%m.%Y}")
    # Hauptnavigation: ganze Zeile antippbar (keine Radio-Kreise)
    for key, label in PAGES.items():
        if key == "module":
            continue
        icon, _, text = label.partition(": ")
        st.button(text, key=f"navpage_{key}", icon=icon + ":", width="stretch",
                  type="primary" if page == label else "tertiary", on_click=goto, args=(key,))

    # Module direkt als Unterpunkte (ohne Aufklappen)
    st.markdown("<div class='small-muted' style='margin:0.4rem 0 0.2rem 0'>Module</div>", unsafe_allow_html=True)
    for mid in ids:
        active = page == PAGES["module"] and mid == module_id
        st.button(module_label(cfg, mid, short=True), key=f"navmod_{mid}", type="primary" if active else "tertiary",
                  width="stretch", on_click=open_unit, args=(mid, None), icon=micon(get_module(cfg, mid)))

    st.divider()
    st.markdown("**Nächste Klausuren**")
    upcoming = []
    for mid in ids:
        days = storage.days_until_exam(mid)
        if days is not None and days >= 0:
            upcoming.append((days, mid))
    if upcoming:
        for days, mid in sorted(upcoming)[:5]:
            color = get_module(cfg, mid)["color"]
            st.markdown(f"<div class='exam-row'><span class='dot' style='background:{color}'></span>"
                        f"<span>{module_label(cfg, mid, short=True)}</span><b>{days} Tage</b></div>",
                        unsafe_allow_html=True)
    else:
        st.caption("Noch keine Klausurtermine – unter Einstellungen eintragen.")

    st.divider()
    sync_status = cloud_sync.status()
    if sync_status is None:
        st.caption("Daten werden nur auf diesem Gerät gespeichert.")
    elif sync_status["fatal"]:
        st.error(sync_status["error"])
    else:
        if sync_status["error"]:
            st.warning(sync_status["error"])
        if sync_status["pending"]:
            st.caption(f"{sync_status['pending']} Änderung(en) werden in Kürze gesichert.")
            if st.button("Jetzt sichern", key="sync_now"):
                with st.spinner("Sichere …"):
                    cloud_sync.flush()
                st.rerun()
        elif not sync_status["error"]:
            st.caption("Alles im Cloud-Speicher gesichert.")
    if ai.is_available():
        model = ai.model_overview()
        st.caption(f"KI aktiv · {model}")
    else:
        st.caption("Kein API-Key – Offline-Modus")


if focus:
    st.markdown("""<style>
      [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stHeader"],
      [data-testid="stToolbar"] { display: none !important; }
      .block-container { max-width: 860px; padding-top: 1.5rem !important; }
    </style>""", unsafe_allow_html=True)
else:
    with st.sidebar:
        sidebar()
    back_button()

if page == PAGES["today"]:
    today_view.render(cfg)
elif page == PAGES["week"]:
    dashboard.render(cfg)
elif page == PAGES["module"]:
    module_view.render(cfg, module_id)
elif page == PAGES["examplan"]:
    exam_plan_view.render(cfg)
elif page == PAGES["bulk"]:
    bulk_upload.render(cfg)
elif page == PAGES["cards"]:
    cards_center.render(cfg)
elif page == PAGES["quiz"]:
    quiz_center.render(cfg)
else:
    settings_view.render(cfg)
