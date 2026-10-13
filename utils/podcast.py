"""Tages-Podcast: ca. 10 Minuten Audio zu den Vorlesungen eines Tages (zwei Sprecher, deutsche Stimmen).

Das Skript schreibt Claude aus Folien, Zusammenfassungen und Nachbereitungs-Notizen. Die Sprachausgabe
übernimmt edge-tts (kostenlose Microsoft-Stimmen, ergibt eine MP3). Falls das nicht klappt, bleibt das
Skript erhalten und kann im Browser vorgelesen werden.
"""

from __future__ import annotations

from datetime import date

from utils import ai, units
from utils.learning import unit_material
from utils.storage import abs_data_path, load_extra, load_module, now_iso, save_extra, save_upload

VOICES = {"A": "de-DE-KatjaNeural", "B": "de-DE-ConradNeural"}
HOSTS = {"A": "Lena", "B": "Jonas"}
MAX_MATERIAL = 60_000  # Zeichen pro Vorlesung

PODCAST_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "segments": {"type": "array", "items": {
            "type": "object",
            "properties": {"speaker": {"type": "string", "enum": ["A", "B"]}, "text": {"type": "string"}},
            "required": ["speaker", "text"], "additionalProperties": False}},
    },
    "required": ["title", "segments"],
    "additionalProperties": False,
}

PROMPT = """Schreibe das Skript für einen Lern-Podcast (ca. 10 Minuten gesprochen, also etwa 1.400–1.600 Wörter)
zu den Vorlesungen vom {day}. Zielgruppe: eine BWL-Studentin im 1. Semester an der LMU, die den Podcast unterwegs
hört (U-Bahn, Spaziergang) – ohne Folien vor Augen.

Zwei Sprecher im lockeren, aber fachlich präzisen Dialog: Lena (A) erklärt, Jonas (B) fragt nach, bringt
Beispiele und fasst zusammen. Aufbau:
1. Kurzer Einstieg: welche Vorlesungen heute und worum es geht.
2. Pro Vorlesung: die Kernideen verständlich erklärt, wie sie zusammenhängen, ein anschauliches Beispiel
   (gern mit einfachen Zahlen), Formeln IN WORTEN (keine Symbole, kein LaTeX), typische Klausurfallen.
   Was laut Nachbereitung vom Dozenten betont wurde, besonders hervorheben.
3. Zum Schluss: drei kurze Merksätze und eine kleine Quizfrage zum Mitdenken mit Auflösung.

Regeln für gesprochene Sprache: kurze Sätze, keine Aufzählungszeichen, keine Abkürzungen wie „z. B.“
(sag „zum Beispiel“), Zahlen so schreiben, wie man sie spricht. Nur Inhalte, die zu den Unterlagen passen;
wenn noch keine Folien vorliegen, beim Thema der Vorlesung bleiben und das Grundlegende erklären.
Teile den Text in Abschnitte von je 1–4 Sätzen (segments) mit wechselnden Sprechern.

{material}"""


def lectures_on(cfg: dict, day: date) -> list[tuple[dict, dict]]:
    """(Modul, Vorlesung) aller Vorlesungen an diesem Tag laut Kursplan."""
    result = []
    for module in cfg["modules"]:
        for lec in units.lectures(cfg, module):
            if lec["date"] == day and not lec["is_break"]:
                result.append((module, lec))
    return result


def store() -> dict:
    return load_extra("podcasts")


def get(day: date) -> dict | None:
    return store().get(day.isoformat())


def audio_bytes(entry: dict) -> bytes | None:
    try:
        return abs_data_path(entry["audio"]).read_bytes() if entry.get("audio") else None
    except (ValueError, OSError):
        return None


def synthesize(segments: list[dict]) -> bytes:
    """MP3 aus den Abschnitten (abwechselnde Stimmen). Wirft eine Exception, wenn edge-tts nicht erreichbar ist."""
    import edge_tts

    audio = bytearray()
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        communicate = edge_tts.Communicate(text, VOICES.get(seg["speaker"], VOICES["A"]), rate="+4%")
        for chunk in communicate.stream_sync():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
    if not audio:
        raise RuntimeError("Keine Audiodaten erhalten.")
    return bytes(audio)


def generate(cfg: dict, day: date) -> dict:
    """Erstellt Skript und (wenn möglich) Audio für einen Tag und speichert beides."""
    lectures = lectures_on(cfg, day)
    if not lectures:
        raise ai.AIError("An diesem Tag ist keine Vorlesung.")
    parts = []
    for module, lec in lectures:
        data = load_module(module["id"])
        material = unit_material(data, lec)
        if len(material) > MAX_MATERIAL:
            material = unit_material(data, lec, summaries_only=True) or material[:MAX_MATERIAL]
        parts.append(f"<vorlesung modul=\"{module['name']}\" thema=\"{lec['topic']}\">\n"
                     f"{material or '(noch keine Folien oder Notizen – nur das Thema ist bekannt)'}\n</vorlesung>")
    result = ai.complete_json(PROMPT.format(day=f"{day:%d.%m.%Y}", material="\n\n".join(parts)), PODCAST_SCHEMA,
                              max_tokens=32000)
    entry = {"date": day.isoformat(), "title": result["title"], "segments": result["segments"],
             "modules": [m["id"] for m, _ in lectures], "created_at": now_iso(), "audio": None, "audio_error": None}
    try:
        entry["audio"] = save_upload("podcasts", f"podcast_{day.isoformat()}.mp3", synthesize(result["segments"]),
                                     "audio")
    except Exception as exc:  # noqa: BLE001 - Audio ist optional, das Skript bleibt nutzbar
        entry["audio_error"] = str(exc)[:300]
    store()[day.isoformat()] = entry
    save_extra("podcasts")
    return entry


def script_text(entry: dict) -> str:
    return "\n\n".join(f"**{HOSTS.get(s['speaker'], s['speaker'])}:** {s['text']}" for s in entry["segments"])


def plain_text(entry: dict) -> str:
    return " ".join(s["text"] for s in entry["segments"])
