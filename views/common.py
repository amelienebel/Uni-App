"""Gemeinsame UI-Bausteine."""

from __future__ import annotations

import html
import json

import streamlit as st
import streamlit.components.v1 as components

from utils import ai
from utils.config import get_module, load_config
from utils.storage import chapter_label, documents_of, get_document_text, get_notes, load_module

PAGES = {
    "today": ":material/today: Heute",
    "week": ":material/calendar_month: Wochenübersicht",
    "module": ":material/school: Modul-Bereiche",
    "cards": ":material/style: Karteikarten-Lernzentrum",
    "examplan": ":material/event_note: Klausur-Lernplan",
    "formulas": ":material/functions: Zentrale Formelsammlung",
    "bulk": ":material/cloud_upload: Bulk-Upload",
    "settings": ":material/settings: Einstellungen",
}
NAV_PAGES = list(PAGES.values())

MODULE_TABS = [":material/view_timeline: Ablauf", ":material/school: Lernen & Klausur",
               ":material/library_books: Definitionen", ":material/folder_open: Dateien",
               ":material/functions: Formeln & Notizen"]
LECTURE_TABS = [":material/folder_open: Dateien", ":material/menu_book: Vorbereiten",
                ":material/edit_note: Nachbereiten", ":material/style: Lernen"]


def micon(module: dict) -> str:
    """Material-Symbol des Moduls (config.json → symbol)."""
    return f":material/{module.get('symbol') or 'school'}:"


def page_title(text: str, icon: str) -> None:
    st.title(f":material/{icon}: {text}")


# Zurück-Button: Verlauf der Ansichten (Seite, Modul, geöffnete Vorlesung/Übung, Reiter)
_VIEW_KEYS = ("nav", "nav_module")
_UNIT_PREFIX = "unit_"
_TAB_PREFIXES = ("mtabs_", "ltab_", "learntabs_", "settings_tabs")
_HISTORY_LIMIT = 40


def _view_state() -> dict:
    state = st.session_state
    return {k: state[k] for k in list(state.keys()) if isinstance(k, str) and (
        k in _VIEW_KEYS or k.startswith(_UNIT_PREFIX)
        or (k.startswith(_TAB_PREFIXES) and not k.startswith("ltab_next_")))}


def _changed(last: dict, cur: dict) -> bool:
    for k in last.keys() | cur.keys():
        if k in _VIEW_KEYS or k.startswith(_UNIT_PREFIX):
            if last.get(k) != cur.get(k):
                return True
        elif k in last and k in cur and last[k] != cur[k]:  # Reiter, die gerade erst erscheinen, zählen nicht
            return True
    return False


def track_history() -> None:
    """Zu Beginn jedes Durchlaufs: Hat sich die Ansicht geändert, merkt sich die App die vorige."""
    cur = _view_state()
    last = st.session_state.get("_nav_last")
    if not st.session_state.pop("_nav_going_back", False) and last is not None and _changed(last, cur):
        history = st.session_state.setdefault("_nav_history", [])
        history.append(last)
        del history[:-_HISTORY_LIMIT]
    st.session_state["_nav_last"] = cur


def go_back() -> None:
    """Callback: vorige Ansicht wiederherstellen (Seite, Modul, Vorlesung/Übung und Reiter)."""
    history = st.session_state.get("_nav_history") or []
    if not history:
        return
    prev = history.pop()
    for k in list(_view_state()):
        if k not in prev and (k.startswith(_UNIT_PREFIX) or k.startswith(_TAB_PREFIXES)):
            st.session_state.pop(k, None)
    for k, v in prev.items():
        st.session_state[k] = v
    st.session_state["_nav_going_back"] = True


def back_button() -> None:
    st.button("Zurück", key="nav_back_btn", icon=":material/arrow_back:", on_click=go_back,
              disabled=not st.session_state.get("_nav_history"))


def goto(page: str, module_id: str | None = None) -> None:
    """Als on_click-Callback verwenden (ändert Widget-Zustand vor dem nächsten Rendern)."""
    st.session_state["nav"] = PAGES[page]
    if module_id:
        st.session_state["nav_module"] = module_id


def toggle_todo(todo: dict, widget_key: str) -> None:
    """Callback für Abhak-Kästchen (Wochenübersicht, Vorlesungs- und Übungsseiten)."""
    from utils import planner
    from utils.storage import load_todos, save_module, save_todos

    value = st.session_state[widget_key]
    if todo.get("status_field"):
        data = load_module(todo["module_id"])
        for ch in data["chapters"]:
            if ch["id"] == todo["chapter_id"]:
                ch["status"][todo["status_field"]] = value
        save_module(todo["module_id"])
        return
    state = load_todos()
    state[todo["key"]] = value
    save_todos()
    if todo.get("sync") and todo.get("chapter_id"):
        data = load_module(todo["module_id"])
        planner.sync_chapter_status(get_module(load_config(), todo["module_id"]), data, todo["chapter_id"],
                                    todo["sync"], state)
        save_module(todo["module_id"])


def open_unit(module_id: str, unit_id: str | None) -> None:
    """Callback: Vorlesung/Übung öffnen (None = zurück zum Ablauf)."""
    goto("module", module_id)
    st.session_state[f"unit_{module_id}"] = unit_id


def open_todo(todo: dict) -> None:
    """Callback: Aufgabe anklicken → passende Vorlesung/Übung (bzw. Lernbereich) im Modul öffnen."""
    parts = todo["key"].split(":")
    module_id = todo["module_id"]
    unit_id = None
    if len(parts) >= 4 and parts[1] == "vl":
        unit_id = f"vl:{parts[2]}"
        st.session_state[f"ltab_next_{unit_id}"] = LECTURE_TABS[2] if parts[3] == "nachbereitet" else LECTURE_TABS[1]
    elif len(parts) >= 4 and parts[1] == "ex":
        unit_id = f"ex:{parts[2]}:{parts[3]}"
    elif todo.get("kind") in ("Wiederholung", "Klausurvorbereitung"):
        st.session_state[f"mtabs_{module_id}"] = MODULE_TABS[1]
    open_unit(module_id, unit_id)


def ai_hint(feature: str = "Diese Funktion") -> bool:
    """Zeigt einen Hinweis, wenn kein API-Key vorhanden ist. Gibt True zurück, wenn KI verfügbar ist."""
    if ai.is_available():
        return True
    st.info(f"{feature} nutzt ohne API-Key ein vereinfachtes Offline-Verfahren. "
            "Für KI-Funktionen `ANTHROPIC_API_KEY` in der `.env` hinterlegen.", icon=":material/info:")
    return False


def chapter_select(module_data: dict, key: str, label: str = "Kapitel", include_none: bool = False,
                   default: str | None = None) -> str | None:
    options = ([None] if include_none else []) + [ch["id"] for ch in module_data["chapters"]]
    if key in st.session_state and st.session_state[key] in options:
        # Vorauswahl kommt z. B. aus der Wochenübersicht (Sprung zu einer Veranstaltung)
        return st.selectbox(label, options, key=key, format_func=lambda cid: chapter_label(module_data, cid))
    st.session_state.pop(key, None)
    index = options.index(default) if default in options else 0
    return st.selectbox(label, options, index=index, key=key,
                        format_func=lambda cid: chapter_label(module_data, cid))


def render_formula(formula: dict, show_meta: bool = True) -> None:
    st.markdown(f"**{formula['name']}**")
    try:
        st.latex(formula["latex"])
    except Exception:  # noqa: BLE001 - fehlerhaftes LaTeX nicht die Seite abstürzen lassen
        st.code(formula["latex"], language="latex")
    if show_meta and formula.get("explanation"):
        st.caption(formula["explanation"])


def doc_type_label(doc_type: str) -> str:
    return load_config()["document_types"].get(doc_type, doc_type)


def module_context(module_id: str, include_fulltext: bool = False) -> tuple[str, int]:
    """Baut den Modulkontext für die KI (Kapitel, Zusammenfassungen, Notizen, Formeln, optional Volltexte).

    Gibt den Kontext und seine Länge in Zeichen zurück, damit die Oberfläche die Größe anzeigen kann.
    """
    cfg = load_config()
    module = get_module(cfg, module_id)
    data = load_module(module_id)
    parts = [f"# Modul: {module['name']}", "", "## Kapitel"]
    for i, ch in enumerate(data["chapters"], start=1):
        done = [k for k, v in ch["status"].items() if v]
        parts.append(f"{i}. {ch['title']} (Woche {ch.get('week')}; Status: {', '.join(done) or 'offen'})")

    summaries = [d for d in data["documents"] if d.get("analysis")]
    if summaries:
        parts += ["", "## Zusammenfassungen der Unterlagen"]
        for doc in summaries:
            a = doc["analysis"]
            parts.append(f"### {doc['filename']} ({chapter_label(data, doc.get('chapter_id'))})")
            parts.append(a.get("summary", ""))
            for c in a.get("key_concepts", []):
                parts.append(f"- {c['term']}: {c['explanation']}")

    notes_parts = []
    for ch in data["chapters"]:
        if ch["id"] not in data["notes"]:
            continue
        notes = get_notes(data, ch["id"])
        content = [f"{label}: {notes[field]}" for field, label in
                   (("text", "Notizen"), ("emphasized", "Vom Dozenten betont"),
                    ("briefly", "Nur kurz angerissen"), ("examples", "Beispiele aus der Vorlesung"))
                   if notes.get(field, "").strip()]
        if content:
            notes_parts.append(f"### {chapter_label(data, ch['id'])}\n" + "\n".join(content))
    for unit_id, notes in sorted(data.get("lecture_notes", {}).items()):
        content = [f"{label}: {notes[field]}" for field, label in
                   (("text", "Notizen"), ("emphasized", "Vom Dozenten betont"),
                    ("briefly", "Nur kurz angerissen"), ("examples", "Beispiele aus der Vorlesung"))
                   if (notes.get(field) or "").strip()]
        content += [f"Tafelbild: {img['transcript']}" for img in notes.get("images", []) if img.get("transcript")]
        if content:
            notes_parts.append(f"### Vorlesung vom {unit_id.removeprefix('vl:')}\n" + "\n".join(content))
    if notes_parts:
        parts += ["", "## Eigene Vorlesungsnotizen"] + notes_parts

    if data["formulas"]:
        parts += ["", "## Formeln"]
        parts += [f"- {f['name']}: ${f['latex']}$" for f in data["formulas"]]

    if include_fulltext:
        docs = [d for d in documents_of(data) if d["doc_type"] != "lehrbuch"]
        if docs:
            parts += ["", "## Volltexte der Unterlagen"]
            for doc in docs:
                parts.append(f"<dokument name=\"{doc['filename']}\" typ=\"{doc['doc_type']}\">")
                parts.append(get_document_text(doc))
                parts.append("</dokument>")
    context = "\n".join(parts)
    return context, len(context)


def tts_player(text: str, key: str) -> None:
    """Vorlesen über die Web-Speech-API des Browsers – keine zusätzlichen API-Kosten."""
    payload = json.dumps(text)
    components.html(f"""
    <div style="font-family:sans-serif;display:flex;gap:8px;align-items:center">
      <button id="play-{key}" style="padding:6px 14px;border-radius:6px;border:1px solid #ccc;cursor:pointer">▶ Vorlesen</button>
      <button id="stop-{key}" style="padding:6px 14px;border-radius:6px;border:1px solid #ccc;cursor:pointer">⏹ Stopp</button>
      <label style="font-size:13px">Tempo
        <input id="rate-{key}" type="range" min="0.7" max="1.5" step="0.1" value="1.0">
      </label>
      <span id="msg-{key}" style="font-size:12px;color:#888"></span>
    </div>
    <script>
      const text = {payload};
      const msg = document.getElementById("msg-{key}");
      document.getElementById("play-{key}").onclick = () => {{
        if (!("speechSynthesis" in window)) {{ msg.textContent = "Browser unterstützt keine Sprachausgabe."; return; }}
        window.speechSynthesis.cancel();
        const u = new SpeechSynthesisUtterance(text);
        u.lang = "de-DE";
        u.rate = parseFloat(document.getElementById("rate-{key}").value);
        const de = window.speechSynthesis.getVoices().find(v => v.lang && v.lang.startsWith("de"));
        if (de) u.voice = de;
        window.speechSynthesis.speak(u);
      }};
      document.getElementById("stop-{key}").onclick = () => window.speechSynthesis.cancel();
    </script>
    """, height=50)


def escape(text: str) -> str:
    return html.escape(text or "")
