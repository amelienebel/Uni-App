"""Fragenspeicher für Vorlesungs-Check und Wochentraining.

Kosten sparen:
- Jede Frage wird gespeichert und wiederverwendet: höchstens MAX_USES-mal und frühestens, wenn mindestens eine
  andere Session des Moduls dazwischen lag. Danach entsteht zum selben Minithema eine neue Frage.
- Altklausuren und Übungsblätter werden einmal zu einem kompakten Klausurstil-Profil zusammengefasst (statt bei
  jeder Erstellung zehntausende Zeichen mitzuschicken); Regeln + Profil stehen im (gecachten) Systemprompt.
- Claude bekommt nur die Folienseiten der benötigten Minithemen; alle neuen Fragen einer Session entstehen in
  EINER Anfrage – Tipps, Begründung je Option und Musterlösung gleich mit. Auswahlfragen und Zahlen prüft die App
  selbst; nur Freitext bewertet Haiku.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from utils import ai
from utils.config import exam_format, get_module
from utils.storage import documents_of, get_document_pages, load_module, new_id, now_iso, save_module
from utils.units import lecture_notes

MAX_USES = 3
MIN_GAP = 1  # so viele andere Sessions müssen mindestens dazwischen liegen
MINUTES = {"sc": 1.0, "mc": 1.5, "zahl": 2.5, "freitext": 3.5}
TYPE_LABELS = {"sc": "Single Choice", "mc": "Multiple Choice", "zahl": "Kopfrechnen", "freitext": "Freitext"}
CALC_RANK = {"keins": 0, "rechenweg": 0, "kopf": 1, "notizblatt": 2, "taschenrechner": 3}
MATERIAL_CHARS = 60000


def max_calc(settings: dict) -> int:
    return 3 if settings.get("calculator") else 2 if settings.get("notepad") else 1


def calc_rule(settings: dict) -> str:
    rank = max_calc(settings)
    if rank == 3:
        return ("Taschenrechner erlaubt: auch krummere Zahlen möglich, dann aber als Auswahlfrage mit Zahlen-Optionen "
                "(keine Eingabe). Bei type \"zahl\" trotzdem ein glattes, eindeutiges Ergebnis.")
    if rank == 2:
        return ("Kein Taschenrechner, aber Notizblatt: Kopfrechnen in höchstens 2–3 Schritten mit glatten "
                "Zwischenergebnissen und glattem Endergebnis.")
    return "Kein Taschenrechner, kein Notizblatt: höchstens EIN einfacher Rechenschritt mit kleinen, glatten Zahlen."


def question_type(mt: dict, level: str, settings: dict) -> str:
    """Fragetyp aus Stufe und Art des Minithemas (Rechnen nie als Freitext/Formeleingabe)."""
    if mt.get("kind") == "kopfrechnen":
        if level == "sc":
            return "sc"
        return "mc" if settings.get("calculator") else "zahl"
    if mt.get("kind") == "rechenweg":
        return "sc" if level == "sc" else "mc"
    return {"sc": "sc", "mc": "mc"}.get(level, "freitext")


def minutes(q: dict) -> float:
    return MINUTES.get(q.get("type"), 1.5)


# ---------------------------------------------------------------------------
# Klausurstil-Profil
# ---------------------------------------------------------------------------

STYLE_PROMPT = """Fasse den Klausurstil des Moduls „{module}“ (KLAUSURFORMAT: {exam_format}) aus den Altklausuren und
Übungsblättern unten zu einem kompakten Stilprofil zusammen (höchstens ~1.500 Wörter), mit dem später neue,
klausurnahe Fragen geschrieben werden: Aufbau und Aufgabentypen, typische Operatoren und Formulierungen,
Schwierigkeitsgrad, typische Fallen/Distraktoren, Themen nach Häufigkeit und Punkten, und 3 kurze typische
Beispielaufgaben (wörtlich oder sinngemäß). Keine Lösungen nötig.

{material}"""


def _style_key(data: dict) -> str:
    exams = sorted(d["id"] for d in documents_of(data, ("altklausur",)))
    sheets = len(documents_of(data, ("uebung", "loesung")))
    return ",".join(exams) + f"|{sheets // 3}"


def style_profile(cfg: dict, module_id: str, data: dict) -> str:
    """Kompaktes Stilprofil (einmal erzeugt, neu nur bei neuen Altklausuren bzw. ab drei neuen Blättern)."""
    from utils.learning import exam_style_material

    module = get_module(cfg, module_id)
    stored = data.get("style_profile") or {}
    key = _style_key(data)
    if stored.get("key") == key:
        return stored.get("text", "")
    material = exam_style_material(cfg, module_id, data)
    text = ""
    if material.strip() and ai.is_available():
        text = ai.complete(STYLE_PROMPT.format(module=module["name"], exam_format=exam_format(module)["label"],
                                               material=material), max_tokens=6000, effort="low", task="cards")
    data["style_profile"] = {"key": key, "text": text.strip(), "created_at": now_iso()}
    save_module(module_id)
    return text.strip()


# ---------------------------------------------------------------------------
# Wiederverwenden
# ---------------------------------------------------------------------------

def session_counter(data: dict) -> int:
    return int(data.get("session_counter", 0))


def reusable(data: dict, mt_id: str, qtype: str, session_no: int, settings: dict,
             exclude: set[str] | None = None) -> dict | None:
    exclude = exclude or set()
    limit = max_calc(settings)
    candidates = [q for q in data.get("questions", []) if q["minitopic_id"] == mt_id and q["type"] == qtype
                  and not q.get("retired") and q["id"] not in exclude and len(q.get("used_in", [])) < MAX_USES
                  and CALC_RANK.get(q.get("calc", "keins"), 0) <= limit
                  and all(session_no - n > MIN_GAP for n in q.get("used_in", []))]
    candidates.sort(key=lambda q: (len(q.get("used_in", [])), q.get("created_at", "")))
    return candidates[0] if candidates else None


def mark_used(q: dict, session_no: int) -> None:
    q.setdefault("used_in", []).append(session_no)
    if len(q["used_in"]) >= MAX_USES:
        q["retired"] = True


# ---------------------------------------------------------------------------
# Neue Fragen erzeugen
# ---------------------------------------------------------------------------

QUESTIONS_SYSTEM = ai.BASE_SYSTEM + """

Du schreibst Klausur-Übungsfragen für eine BWL-Studentin (LMU, 1. Semester) – genau eine Frage pro Auftragszeile.

Fragetypen:
- "sc": Single Choice, genau 4 Optionen, genau eine richtig (correct_indices = [Index 0–3]).
- "mc": Multiple Choice, genau 5 Optionen, eine oder mehrere richtig (correct_indices = alle richtigen, 0–4;
  die Zahl der richtigen variiert).
- "zahl": Kopfrechnen – die Antwort ist EINE Zahl mit eindeutigem, glattem Ergebnis (number_answer, z. B. "120"
  oder "0,25"); options leer. Kein Toleranzbereich, keine Einheit in number_answer.
- "freitext": Erklärfrage, die man in Worten beantwortet (NIE Formeln oder Rechnungen tippen lassen).
  sample_answer = vollständige Musterlösung; key_points = 2–5 Bewertungspunkte.
Die Studentin kann keine Formeln und keine Mathematik tippen: Rechnen gibt es nur als Auswahl zum Rechenweg
(„Welcher Ansatz/Schritt ist richtig?“) oder als Kopfrechnen mit glattem Ergebnis – die RECHEN-Regel der Zeile
bestimmt den Aufwand. calc: "keins", "rechenweg", "kopf", "notizblatt" oder "taschenrechner" (was die Frage braucht).

Inhalt:
- NUR Stoff aus dem Kerninhalt und den Folien des jeweiligen Minithemas – nichts erfinden.
- Klausurnah im Stil des KLAUSURSTIL-PROFILS (Formulierungen, Operatoren, Distraktoren), aber eigene Fälle/Zahlen.
- Wissensfragen UND kleine Anwendungsaufgaben (je nach Art des Minithemas).
- Beispiele aus der Vorlesung nie auswendig abfragen (außer der Hinweis der Nutzerin verlangt es) – höchstens als
  Vorlage für eine eigene Anwendung.
- Hinweise der Nutzerin zur Vorlesung beachten: [STREICHEN] nie abfragen, [WICHTIG] gründlich, [SONSTIGER HINWEIS]
  hat Vorrang.
- „Lief schlecht“ aus den Übungen: genau diese Schwäche gezielt prüfen.

Zu jeder Frage:
- hints: genau 3 Tipps in steigender Stärke, die die Lösung NICHT verraten: (1) Denkanstoß/Rückfrage, (2) passendes
  Konzept bzw. Bedeutung der Zeichen/Begriffe, (3) konkreter nächster Schritt.
- option_notes (sc/mc): für JEDE Option in derselben Reihenfolge ein Satz, ob richtig/falsch und WARUM (bei
  falschen den Denkfehler benennen). Sonst leer.
- explanation: warum die Lösung richtig ist – Kernargument bzw. Rechenweg in Worten, typische Falle.
- Formeln in LaTeX mit $...$.
"""

QUESTIONS_USER = """KLAUSURFORMAT: {exam_format}
RECHEN-REGEL: {calc}

<hinweise_der_nutzerin>
{hints}
</hinweise_der_nutzerin>

<auftraege>
{requests}
</auftraege>

<folien>
{material}
</folien>"""

QUESTIONS_SCHEMA = ai._obj({"questions": {"type": "array", "items": ai._obj({
    "req": ai._INT, "type": {"type": "string", "enum": ["sc", "mc", "zahl", "freitext"]}, "question": ai._STR,
    "options": {"type": "array", "items": ai._STR}, "correct_indices": {"type": "array", "items": ai._INT},
    "option_notes": {"type": "array", "items": ai._STR}, "hints": {"type": "array", "items": ai._STR},
    "explanation": ai._STR, "sample_answer": ai._STR, "key_points": {"type": "array", "items": ai._STR},
    "number_answer": ai._STR, "calc": {"type": "string", "enum": list(CALC_RANK)}})}})


def _lecture_hints(data: dict, lec_ids: list[str], lec_names: dict[str, str]) -> str:
    parts = []
    for lid in lec_ids:
        notes = lecture_notes(data, lid)
        lines = [f"[{label}] {notes[field].strip()}" for field, label in
                 (("emphasized", "WICHTIG"), ("skip", "STREICHEN"), ("card_hint", "SONSTIGER HINWEIS"))
                 if (notes.get(field) or "").strip()]
        if lines:
            parts.append(f"{lec_names.get(lid, lid)}:\n" + "\n".join(lines))
    return "\n\n".join(parts) or "keine"


def _material(data: dict, mts: list[dict]) -> str:
    wanted: dict[str, set[int]] = {}
    for mt in mts:
        for src in mt.get("slides", []):
            wanted.setdefault(src["doc_id"], set()).update(src.get("pages", []))
    blocks, used = [], 0
    for doc_id, pages in wanted.items():
        doc = next((d for d in data["documents"] if d["id"] == doc_id), None)
        if not doc:
            continue
        texts = get_document_pages(doc)
        body = "\n\n".join(f"--- {doc['filename']} Seite {p} ---\n{texts[p - 1]}" for p in sorted(pages)
                           if 1 <= p <= len(texts))
        if used + len(body) > MATERIAL_CHARS:
            body = body[:max(0, MATERIAL_CHARS - used)]
        used += len(body)
        if body:
            blocks.append(body)
    return "\n\n".join(blocks) or "(keine Folien – nur Kerninhalt verwenden)"


def _valid(q: dict, want: str) -> bool:
    if q["type"] != want or not q["question"].strip():
        return False
    if want == "sc":
        return len(q["options"]) == 4 and len(set(q["correct_indices"])) == 1 and 0 <= q["correct_indices"][0] < 4
    if want == "mc":
        return len(q["options"]) == 5 and bool(q["correct_indices"]) and all(0 <= i < 5 for i in q["correct_indices"])
    if want == "zahl":
        return parse_number(q["number_answer"]) is not None
    return bool(q["sample_answer"].strip())


def generate(cfg: dict, module_id: str, requests: list[dict], settings: dict, lec_names: dict[str, str]) -> list[dict]:
    """requests = [{"mt": Minithema, "type": Fragetyp}] → neue, gespeicherte Fragen (gleiche Reihenfolge; None,
    wenn für einen Auftrag nichts Brauchbares kam). Wirft ai.AIError."""
    if not requests:
        return []
    module = get_module(cfg, module_id)
    data = load_module(module_id)
    style = style_profile(cfg, module_id, data) or "(keine Altklausuren – Stil deutscher Uni-Klausuren, 1. Semester)"
    lines = []
    for i, r in enumerate(requests, start=1):
        mt = r["mt"]
        flags = [f["text"] for f in (data.get("mastery", {}).get(mt["id"], {}) or {}).get("exercise_flags", [])
                 if f["kind"] == "schlecht" and f.get("open")]
        lines.append(f"[{i}] type={r['type']} · Minithema: {mt['title']} (Thema: {mt['topic']}; "
                     f"{lec_names.get(mt['lecture_id'], '')}) · Art: {mt.get('kind', 'wissen')}\n"
                     f"    Kerninhalt: {mt.get('summary', '')}"
                     + (f"\n    Lief schlecht in der Übung: {' | '.join(flags)}" if flags else ""))
    lec_ids = sorted({r["mt"]["lecture_id"] for r in requests})
    prompt = QUESTIONS_USER.format(exam_format=exam_format(module)["label"], calc=calc_rule(settings),
                                   hints=_lecture_hints(data, lec_ids, lec_names), requests="\n".join(lines),
                                   material=_material(data, [r["mt"] for r in requests]))
    # Regeln + Stilprofil im Systemprompt: bleibt je Modul gleich und wird deshalb gecacht
    system = QUESTIONS_SYSTEM + f"\n\n<klausurstil_profil>\n{style}\n</klausurstil_profil>"
    result = ai.complete_json(prompt, QUESTIONS_SCHEMA, system=system, max_tokens=48000, task="cards")
    by_req: dict[int, dict] = {}
    for q in result.get("questions", []):
        if 1 <= q["req"] <= len(requests) and q["req"] not in by_req and _valid(q, requests[q["req"] - 1]["type"]):
            by_req[q["req"]] = q
    out = []
    for i, r in enumerate(requests, start=1):
        q = by_req.get(i)
        if not q:
            out.append(None)
            continue
        stored = {"id": new_id(), "minitopic_id": r["mt"]["id"], "lecture_id": r["mt"]["lecture_id"],
                  "type": q["type"], "question": q["question"].strip(), "options": q["options"],
                  "correct_indices": sorted(set(q["correct_indices"])) if q["type"] in ("sc", "mc") else [],
                  "option_notes": q["option_notes"], "hints": [h for h in q["hints"] if h.strip()][:3],
                  "explanation": q["explanation"].strip(), "sample_answer": q["sample_answer"].strip(),
                  "key_points": q["key_points"], "number_answer": q["number_answer"].strip(),
                  "calc": q["calc"], "slides": r["mt"].get("slides", []), "created_at": now_iso(), "used_in": []}
        data.setdefault("questions", []).append(stored)
        out.append(stored)
    save_module(module_id)
    return out


def cost_estimate(n_new: int) -> float:
    return ai.estimate_cost("cards", 6000 + 2500 * n_new, 700 * n_new) if n_new else 0.0


# ---------------------------------------------------------------------------
# Auswerten
# ---------------------------------------------------------------------------

def parse_number(text: str) -> Decimal | None:
    t = (text or "").strip().replace(" ", "").replace("€", "").replace("%", "").replace("−", "-")
    if not t:
        return None
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def check_choice(q: dict, picked: list[int]) -> bool:
    return sorted(set(picked)) == sorted(q.get("correct_indices", []))


def check_number(q: dict, answer: str) -> bool:
    given, right = parse_number(answer), parse_number(q.get("number_answer", ""))
    return given is not None and right is not None and given == right


def grade_text(q: dict, answer: str, weak: str = "") -> tuple[object, dict]:
    """Freitext mit Haiku gegen die gespeicherte Musterlösung bewerten → (True/"partial"/False, Korrektur)."""
    from views.module_tabs import exams

    points = max(2, len(q.get("key_points") or []) * 2)
    sample = q.get("sample_answer", "") + ("\nBewertungspunkte: " + "; ".join(q["key_points"])
                                           if q.get("key_points") else "")
    grading = exams.grade_answer({"question": q["question"], "sample_answer": sample, "points": points,
                                  "operator": ""}, answer, weak, task="check")
    ratio = grading["score"] / max(1, grading["max_score"])
    return (True if ratio >= 0.85 else "partial" if ratio >= 0.4 else False), grading
