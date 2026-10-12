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
    "Rechenaufgaben stets mit vollständigem Rechenweg.\n\n<modulkontext>\n{context}\n</modulkontext>"
)


def render(cfg: dict, module_id: str) -> None:
    module = get_module(cfg, module_id)
    data = load_module(module_id)

    st.subheader("💬 Verständnis-Chat")
    if not ai.is_available():
        st.info("Der Tutor-Chat benötigt einen API-Key (`ANTHROPIC_API_KEY` in `.env`).", icon="🔌")
        return

    c1, c2 = st.columns([3, 1])
    fulltext = c1.toggle("Volltexte aller Unterlagen einbeziehen (genauer, aber mehr Tokens)",
                         key=f"tutor_full_{module_id}")
    if c2.button("🧹 Chat leeren", key=f"tutor_clear_{module_id}"):
        data["chat"] = []
        save_module(module_id)
        st.rerun()
    context, size = module_context(module_id, include_fulltext=fulltext)
    st.caption(f"Kontext: ca. {size // 4:,} Tokens".replace(",", ".")
               + " · wird gecacht, Folgefragen sind günstiger.")

    if not data["chat"]:
        st.markdown("_Beispiele:_ „Erklär mir den Unterschied zwischen Kapitalwert und Annuität“, "
                    "„Stell mir drei Fragen zu Kapitel 2“, „Wo liegt mein Fehler in dieser Rechnung: …“")

    chat_box = st.container(height=520)
    with chat_box:
        for msg in data["chat"]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    prompt = st.chat_input(f"Frage zu {module['short']} …", key=f"tutor_input_{module_id}")
    if prompt:
        data["chat"].append({"role": "user", "content": prompt})
        with chat_box:
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                answer = st.write_stream(ai.stream_chat(
                    data["chat"], system=TUTOR_SYSTEM.format(module=module["name"], context=context)))
        data["chat"].append({"role": "assistant", "content": answer if isinstance(answer, str) else "".join(map(str, answer))})
        save_module(module_id)
