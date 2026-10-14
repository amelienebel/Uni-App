"""Reiter: Verständnis-Chat – modulspezifischer KI-Tutor mit Modulkontext."""

from __future__ import annotations

import streamlit as st

from utils import ai
from utils.config import get_module
from utils.storage import load_module, save_module
from views.common import module_context

TUTOR_SYSTEM = (
    ai.BASE_SYSTEM + "\n\nDu bist Tutor für das Modul „{module}“. Nutze den folgenden Modulkontext "
    "(Kapitel, Zusammenfassungen, Notizen des Studierenden, Formeln) als Grundlage und beziehe dich, wo möglich, "
    "auf die Kapitel und Folien. Arbeite sokratisch, wenn der Studierende üben möchte: erst Denkanstoß, dann Lösung. "
    "Rechenaufgaben stets mit vollständigem Rechenweg. Hauptquelle sind Folien, Skript und meine Notizen. Für "
    "weiterführende Fragen darfst du Fachliteratur heranziehen – die Lehrbuch-Auszüge (<lehrbuch>, nenne das Kapitel) "
    "oder dein Fachwissen; kennzeichne, was über die Vorlesung hinausgeht. Bei Abweichungen gelten Folien und Notizen.\n\n<modulkontext>\n{context}\n</modulkontext>"
)


def render(cfg: dict, module_id: str, scope_key: str = "main", context: str | None = None,
           scope_label: str | None = None) -> None:
    """Tutor-Chat zum ganzen Modul oder – mit scope_key/context – zu ausgewählten Vorlesungen."""
    module = get_module(cfg, module_id)
    data = load_module(module_id)
    history = data["chat"] if scope_key == "main" else data.setdefault("chats", {}).setdefault(scope_key, [])

    if not ai.is_available():
        st.info("Der Tutor-Chat benötigt einen API-Key (`ANTHROPIC_API_KEY` in `.env`).", icon=":material/info:")
        return

    c1, c2 = st.columns([3, 1])
    if context is None:
        fulltext = c1.toggle("Volltexte aller Unterlagen einbeziehen (genauer, aber mehr Tokens)",
                             key=f"tutor_full_{module_id}")
        context, size = module_context(module_id, include_fulltext=fulltext)
    else:
        size = len(context)
        if scope_label:
            c1.caption(f"Bezieht sich auf: {scope_label}")
    if c2.button("Chat leeren", key=f"tutor_clear_{module_id}_{scope_key}"):
        history.clear()
        save_module(module_id)
        st.rerun()
    st.caption(f"Kontext: ca. {size // 4:,} Tokens".replace(",", ".")
               + " · wird gecacht, Folgefragen sind günstiger.")

    if not history:
        st.markdown("_Beispiele:_ „Erklär mir den Unterschied zwischen Kapitalwert und Annuität“, "
                    "„Stell mir drei Fragen zu Kapitel 2“, „Wo liegt mein Fehler in dieser Rechnung: …“")

    chat_box = st.container(height=460)
    with chat_box:
        for msg in history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    prompt = st.chat_input(f"Frage zu {module['short']} …", key=f"tutor_input_{module_id}_{scope_key}")
    if prompt:
        history.append({"role": "user", "content": prompt})
        with chat_box:
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                answer = st.write_stream(ai.stream_chat(
                    history, system=TUTOR_SYSTEM.format(module=module["name"], context=context)))
        history.append({"role": "assistant", "content": answer if isinstance(answer, str) else "".join(map(str, answer))})
        save_module(module_id)
