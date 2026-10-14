"""Anthropic-API-Anbindung (Claude).

- Der API-Key wird über python-dotenv aus der .env-Datei geladen (online: aus den Streamlit-Secrets).
- Alle Aufrufe laufen gestreamt (keine Timeouts bei langen Antworten).
- Für Opus/Sonnet ist der serverseitige Refusal-Fallback aktiviert (fallbacks="default").
- Ohne API-Key bleibt die App nutzbar: Die Views greifen dann auf heuristische Verfahren zurück.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator

import anthropic
import streamlit as st
from utils.config import get_secret

MODELS = {
    "claude-opus-5-5": "Claude Opus 5.5 – beste Qualität, doppelter Preis",
    "claude-sonnet-5-5": "Claude Sonnet 5.5 – fast so gut, halber Preis (empfohlen)",
    "claude-haiku-5-5": "Claude Haiku 5.5 – sehr günstig (1/40 von Opus), für einfache Aufgaben",
}
DEFAULT_MODEL = "claude-sonnet-5-5"
EFFORTS = {
    "low": "Niedrig – schnell, spart Tokens",
    "medium": "Mittel (Standard)",
    "high": "Hoch – gründlicher",
    "xhigh": "Sehr hoch",
}
# Modelle, für die der serverseitige Fallback bei Ablehnungen verfügbar ist
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

BASE_SYSTEM = (
    "Du bist ein geduldiger, fachlich präziser Tutor für Studierende im Bachelor BWL an der "
    "LMU München (1. Semester). Antworte auf Deutsch, klar strukturiert und prüfungsorientiert. "
    "Verwende für Formeln LaTeX: inline mit $...$ und abgesetzt mit $$...$$. "
    "Wenn Informationen aus den Unterlagen fehlen, sag das offen, statt etwas zu erfinden."
)


class AIError(Exception):
    """Verständliche Fehlermeldung für die Oberfläche."""


def api_key() -> str | None:
    return get_secret("ANTHROPIC_API_KEY")


def is_available() -> bool:
    return api_key() is not None


@st.cache_resource(show_spinner=False)
def _client(key: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=key, max_retries=3)


# Preise in US-Dollar pro 1 Million Tokens (Eingabe, Ausgabe)
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}


def estimate_cost(task: str, input_tokens: int, output_tokens: int) -> float:
    model, _ = _settings(task)
    price_in, price_out = PRICES.get(model, (4.0, 20.0))
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


# Welches Modell für welche Aufgabe (änderbar unter Einstellungen → KI-Einstellungen)
TASKS = {
    "summary": ("Zusammenfassungen der Folien", "claude-haiku-5-5"),
    "cards": ("Karteikarten & Definitionen", "claude-sonnet-5-5"),
    "tutor": ("Tutor-Chat", "claude-opus-5-5"),
    "default": ("Alles andere (Quiz, Lösungsvergleich, Abtippen, Karten-Nachfragen …)", "claude-sonnet-5-5"),
}


def _settings(task: str | None = None) -> tuple[str, str]:
    from utils.storage import load_settings, save_settings

    ai_settings = load_settings().setdefault("ai", {})
    if "models" not in ai_settings:  # Umstellung auf die Modellwahl pro Aufgabe
        ai_settings["models"] = {key: default for key, (_, default) in TASKS.items()}
        ai_settings.pop("model", None)
        ai_settings.pop("model_cards", None)
        save_settings()
    models = ai_settings["models"]
    task = task if task in TASKS else "default"
    model = models.get(task) or TASKS[task][1]
    effort = ai_settings.get("effort") or "medium"
    return (model if model in MODELS else TASKS[task][1]), (effort if effort in EFFORTS else "medium")


def model_overview() -> str:
    """Kurzfassung für die Seitenleiste, z. B. „Haiku (Zusammenf.) · Sonnet (Karten) · Opus (Tutor)“."""
    short = {"summary": "Zusammenf.", "cards": "Karten", "tutor": "Tutor"}
    return " · ".join(f"{MODELS.get(_settings(t)[0], _settings(t)[0]).split(' –')[0].replace('Claude ', '')} ({label})"
                      for t, label in short.items())


def _request(system: str, messages: list[dict], max_tokens: int, json_schema: dict | None = None,
             effort: str | None = None, task: str | None = None) -> dict:
    model, default_effort = _settings(task)
    output_config: dict = {"effort": effort or default_effort}
    if json_schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": json_schema}
    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        # Systemprompt wird gecacht: wiederholte Fragen zum selben Modulkontext sind deutlich günstiger
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": messages,
        "thinking": {"type": "adaptive"},
        "output_config": output_config,
    }
    if model in _FALLBACK_MODELS:
        kwargs["betas"] = [_FALLBACK_BETA]
        kwargs["fallbacks"] = "default"
    return kwargs


def _client_or_raise() -> anthropic.Anthropic:
    key = api_key()
    if not key:
        raise AIError("Kein API-Key gefunden. Lege eine .env-Datei mit ANTHROPIC_API_KEY=... an "
                      "(siehe .env.example) und starte die App neu.")
    return _client(key)


def _translate_error(exc: Exception) -> AIError:
    if isinstance(exc, anthropic.AuthenticationError):
        return AIError("Der API-Key ist ungültig. Bitte .env prüfen.")
    if isinstance(exc, anthropic.PermissionDeniedError):
        return AIError("Der API-Key hat keine Berechtigung für dieses Modell.")
    if isinstance(exc, anthropic.NotFoundError):
        return AIError("Modell nicht gefunden – bitte in den Einstellungen ein anderes Modell wählen.")
    if isinstance(exc, anthropic.RateLimitError):
        return AIError("Rate-Limit erreicht. Bitte kurz warten und erneut versuchen.")
    if isinstance(exc, anthropic.BadRequestError):
        return AIError(f"Ungültige Anfrage: {exc.message}")
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code >= 500:
            return AIError(f"Serverfehler bei Anthropic ({exc.status_code}). Bitte später erneut versuchen.")
        return AIError(f"API-Fehler ({exc.status_code}): {exc.message}")
    if isinstance(exc, anthropic.APIConnectionError):
        return AIError("Keine Verbindung zur Anthropic-API. Internetverbindung prüfen.")
    return AIError(f"Unerwarteter Fehler: {exc}")


def _text_of(message) -> str:
    return "".join(block.text for block in message.content if block.type == "text")


def _check_stop(message) -> None:
    if message.stop_reason == "refusal":
        raise AIError("Die Anfrage wurde vom Modell abgelehnt. Bitte anders formulieren.")


def complete(prompt: str | list, system: str = BASE_SYSTEM, history: list[dict] | None = None,
             max_tokens: int = 16000, effort: str | None = None, task: str | None = None) -> str:
    """Einzelne Anfrage, gibt den vollständigen Antworttext zurück."""
    client = _client_or_raise()
    messages = list(history or []) + [{"role": "user", "content": prompt}]
    try:
        with client.beta.messages.stream(**_request(system, messages, max_tokens, effort=effort, task=task)) as stream:
            message = stream.get_final_message()
    except anthropic.APIError as exc:
        raise _translate_error(exc) from exc
    _check_stop(message)
    text = _text_of(message)
    if message.stop_reason == "max_tokens":
        text += "\n\n_(Antwort wurde wegen der Längenbegrenzung abgeschnitten.)_"
    return text


def complete_json(prompt: str | list, schema: dict, system: str = BASE_SYSTEM,
                  max_tokens: int = 32000, effort: str | None = None, task: str | None = None) -> dict:
    """Strukturierte Ausgabe: Die Antwort ist garantiert valides JSON nach dem Schema."""
    client = _client_or_raise()
    messages = [{"role": "user", "content": prompt}]
    try:
        with client.beta.messages.stream(**_request(system, messages, max_tokens, json_schema=schema,
                                                    effort=effort, task=task)) as stream:
            message = stream.get_final_message()
    except anthropic.APIError as exc:
        raise _translate_error(exc) from exc
    _check_stop(message)
    if message.stop_reason == "max_tokens":
        raise AIError("Die Antwort war zu lang und wurde abgeschnitten. Bitte weniger Inhalte auf einmal auswählen.")
    try:
        return json.loads(_text_of(message))
    except json.JSONDecodeError as exc:
        raise AIError("Die KI-Antwort konnte nicht als JSON gelesen werden. Bitte erneut versuchen.") from exc


def stream_chat(messages: list[dict], system: str = BASE_SYSTEM, max_tokens: int = 16000,
                task: str | None = None) -> Iterator[str]:
    """Generator für st.write_stream – liefert Textstücke, Fehler als lesbarer Text."""
    try:
        client = _client_or_raise()
        with client.beta.messages.stream(**_request(system, messages, max_tokens, task=task)) as stream:
            for text in stream.text_stream:
                yield text
            message = stream.get_final_message()
        if message.stop_reason == "refusal":
            yield "\n\nDie Anfrage wurde vom Modell abgelehnt. Bitte formuliere sie anders."
        elif message.stop_reason == "max_tokens":
            yield "\n\n_(Antwort wegen Längenbegrenzung abgeschnitten.)_"
    except AIError as exc:
        yield f"{exc}"
    except anthropic.APIError as exc:
        yield f"{_translate_error(exc)}"


def image_block(content: bytes, media_type: str) -> dict:
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": base64.b64encode(content).decode()},
    }


def pdf_block(content: bytes) -> dict:
    return {
        "type": "document",
        "source": {"type": "base64", "media_type": "application/pdf", "data": base64.b64encode(content).decode()},
    }


# ---------------------------------------------------------------------------
# JSON-Schemata für strukturierte Ausgaben
# ---------------------------------------------------------------------------

def _obj(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties,
            "required": required if required is not None else list(properties), "additionalProperties": False}


_STR = {"type": "string"}
_INT = {"type": "integer"}

FORMULA_SCHEMA = _obj({"name": _STR, "latex": _STR, "explanation": _STR, "page": _INT})

ANALYSIS_SCHEMA = _obj({
    "summary": _STR,
    "key_concepts": {"type": "array", "items": _obj({"term": _STR, "explanation": _STR})},
    "important_slides": {"type": "array", "items": _obj({"page": _INT, "reason": _STR})},
    "check_questions": {"type": "array", "items": _obj({"question": _STR, "answer": _STR})},
    "formulas": {"type": "array", "items": FORMULA_SCHEMA},
})

VISUAL_ANALYSIS_SCHEMA = _obj({
    **ANALYSIS_SCHEMA["properties"],
    "slides": {"type": "array", "items": _obj({"page": _INT, "text": _STR})},
})

DEFINITIONS_SCHEMA = _obj({"definitions": {"type": "array", "items": _obj({"term": _STR, "definition": _STR})}})

CARDS_SCHEMA = _obj({
    "cards": {"type": "array", "items": _obj({"front": _STR, "back": _STR, "chapter_hint": _STR})},
    "definitions": {"type": "array", "items": _obj({"term": _STR, "definition": _STR})},
})

FORMULAS_SCHEMA = _obj({"formulas": {"type": "array", "items": FORMULA_SCHEMA}})

QUIZ_SCHEMA = _obj({
    "questions": {"type": "array", "items": _obj({
        "type": {"type": "string", "enum": ["mc", "freitext"]},
        "operator": _STR,
        "question": _STR,
        "options": {"type": "array", "items": _STR},
        "correct_index": _INT,
        "explanation": _STR,
        "sample_answer": _STR,
        "points": _INT,
    })},
})

GRADING_SCHEMA = _obj({"score": _INT, "max_score": _INT, "feedback": _STR, "missing_points": {"type": "array", "items": _STR}})

EXAM_ANALYSIS_SCHEMA = _obj({
    "overview": _STR,
    "topics": {"type": "array", "items": _obj({"topic": _STR, "frequency": _STR, "typical_tasks": _STR})},
    "operator_strategies": {"type": "array", "items": _obj({"operator": _STR, "how_to_answer": _STR, "example": _STR})},
    "recommendations": {"type": "array", "items": _STR},
})
