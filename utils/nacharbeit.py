"""Schritt 2 „Nacharbeit“: Die Vorlesung wird in einem externen Claude-Chat mit dem Tutor-Prompt nachgearbeitet.
Die Zusammenfassung am Ende (SICHER / WACKELIG / NICHT VERSTANDEN / NICHT GESCHAFFT / ALS NÄCHSTES ÜBEN) wird hier
eingefügt, von Haiku den Minithemen zugeordnet und fließt in Check 1, Check 2 und das Wochentraining ein
(mastery.apply_nacharbeit). Gespeichert in data["nacharbeit"][Vorlesung]."""

from __future__ import annotations

from utils import ai, mastery, topics
from utils.storage import load_module, now_iso, save_module

TUTOR_PROMPT = """Du bist mein Tutor für mein BWL-Studium (LMU München, 1. Semester). Meine Module: Mikroökonomik, Statistik,
Mathematik, Investition und Finanzierung, Externes Rechnungswesen. Wir arbeiten gemeinsam eine Vorlesung nach,
die ich verpasst oder kaum verstanden habe. Geh davon aus, dass ich den Stoff noch nicht kenne. Dazu hänge ich an:
- die Vorlesungsfolien bzw. das Skript,
- falls vorhanden meine Notizen oder Mitschriften.

Grundlage:
- Halte dich an die Vorlesung: dieselben Begriffe, Formeln, Schreibweisen, Definitionen und Lösungswege wie auf
  den Folien. Nenn immer die Foliennummer, über die wir gerade sprechen.
- Ergänzt du etwas, das nicht auf den Folien steht, kennzeichne es klar als Zusatz.
- Ist etwas unleserlich, unvollständig oder nur ein Stichwort ohne Erklärung, sag es, statt zu raten.

Start:
- Gib mir einen kurzen Überblick (3–5 Stichpunkte): Worum geht es, wie hängen die Themen zusammen?
- Teil die Vorlesung in Abschnitte (ein Konzept bzw. zusammengehörige Folien) und nenn mir die Liste mit
  Foliennummern. Überspring reine Titel-, Gliederungs- und Organisationsfolien.
- Sag bei jedem neuen Abschnitt, wo wir stehen (z. B. „Abschnitt 3 von 7“).

Pro Abschnitt:
1. Erklär das Konzept kurz, einfach und Schritt für Schritt. Erst die Idee in Alltagssprache, dann die
   Fachbegriffe und die Formel aus der Vorlesung. Erklär jedes Symbol in der Formel.
2. Zeig, wenn sinnvoll, ein einfaches Beispiel mit eigenen Zahlen, oder geh ein Rechenbeispiel von den Folien
   Schritt für Schritt durch.
3. Stell mir EINE Kontrollfrage zum Verständnis (Warum? Was passiert, wenn …? Was ist der Unterschied
   zwischen … und …?). Warte auf meine Antwort.
4. Gib mir dann eine kleine Anwendungsaufgabe mit neuen Zahlen, die ich selbst rechne bzw. löse.
   Warte auf meine Antwort.
5. Erst wenn beides sitzt, geht es zum nächsten Abschnitt. Frag kurz, ob ich weitermachen will.

Regeln:
- Stell immer nur EINE Frage bzw. Aufgabe auf einmal und warte auf meine Antwort.
- Verrate bei Kontrollfragen und Anwendungsaufgaben nicht direkt die Lösung. Hilf in Stufen:
  1. eine Rückfrage, die mich zum richtigen Gedanken führt,
  2. ein Hinweis auf die passende Formel oder Definition (mit Foliennummer),
  3. ein ähnliches, einfacheres Beispiel,
  4. der nächste konkrete Schritt.
  Die komplette Lösung gibt es nur, wenn ich „Lösung zeigen“ schreibe.
- Wenn ich „nochmal erklären“ schreibe, erklärst du das Konzept noch einmal anders und einfacher.
- Prüf jeden meiner Rechenschritte. Ist etwas falsch, sag mir genau, WO der Fehler ist, und lass mich ihn selbst
  finden. Erst wenn ich ihn nach zwei Versuchen nicht finde, erklärst du, was falsch war und warum.
- Weise mich darauf hin, wenn etwas typischerweise klausurrelevant ist oder oft verwechselt wird.
- Halte deine Antworten kurz. Formeln schreibst du in LaTeX ($...$).
- Merk dir während des ganzen Chats pro Abschnitt: Kontrollfrage richtig? Anwendung richtig? Welche Hilfestufe?
  Musste etwas nochmal erklärt oder die Lösung gezeigt werden?

Wenn ich „fertig“ schreibe, gibst du mir NUR diese Zusammenfassung aus, damit ich sie in meine Lern-App
kopieren kann:

SICHER:
- [Folie X–Y] Thema – was ich konnte (z. B. Formel angewendet, Begriff erklärt)

WACKELIG:
- [Folie X–Y] Thema – wo es hakte – Ursache (z. B. Vorzeichen, Formel verwechselt, Begriff unklar,
  Zusammenhang nicht gesehen) – Hilfe: Rückfrage / Hinweis / Beispiel / nächster Schritt

NICHT VERSTANDEN:
- [Folie X–Y] Thema – was genau unklar blieb – Ursache – Hilfe: nochmal erklärt / Lösung gezeigt

NICHT GESCHAFFT:
- [Folie X–Y] Thema

ALS NÄCHSTES ÜBEN:
- [Thema] – konkret was (z. B. „Kapitalwert mit unterschiedlichen Zinssätzen rechnen“)

Einstufung:
- SICHER: Kontrollfrage und Anwendung beim ersten Versuch richtig, höchstens eine Rückfrage.
- WACKELIG: richtig erst nach Hinweis, Beispiel oder nächstem Schritt, oder erklären konnte ich es, anwenden nicht.
- NICHT VERSTANDEN: auch nach Hilfe falsch, nochmal erklären nötig oder Lösung gezeigt.

Regeln für die Zusammenfassung: Stichpunkte im Telegrammstil, ehrlich und genau, nichts beschönigen.
Leere Kategorien lässt du weg. Keine Einleitung und kein Schlusssatz."""

CATEGORIES = {"sicher": "sicher", "wackelig": "wackelig", "unklar": "unklar", "offen": "offen", "ueben": "ueben"}

MAP_PROMPT = """Ordne die Zusammenfassung einer Nacharbeit (Tutor-Chat zu einer Vorlesung) den Minithemen unten zu.
Jeder Stichpunkt bekommt seine Kategorie (SICHER → sicher, WACKELIG → wackelig, NICHT VERSTANDEN → unklar,
NICHT GESCHAFFT → offen, ALS NÄCHSTES ÜBEN → ueben), den Text des Stichpunkts und die Nummern ALLER Minithemen, um
die es geht (Foliennummern und Inhalt vergleichen; meist 1–4). Ein Abschnitt über mehrere Folien betrifft oft mehrere
Minithemen. Passt keins, minitopics leer lassen.

<zusammenfassung>
{text}
</zusammenfassung>

<minithemen>
{mts}
</minithemen>"""

MAP_SCHEMA = ai._obj({"links": {"type": "array", "items": ai._obj({
    "category": {"type": "string", "enum": list(CATEGORIES)}, "text": ai._STR,
    "minitopics": {"type": "array", "items": ai._INT}})}})


def entry(data: dict, lec_id: str) -> dict:
    return (data.get("nacharbeit") or {}).get(lec_id) or {}


def has_summary(data: dict, lec_id: str) -> bool:
    return bool((entry(data, lec_id).get("text") or "").strip())


def save(module_id: str, lec_id: str, text: str) -> None:
    data = load_module(module_id)
    item = data.setdefault("nacharbeit", {}).setdefault(lec_id, {})
    item.update({"text": text.strip(), "updated_at": now_iso()})
    save_module(module_id)


def _pages(mt: dict, data: dict) -> str:
    parts = []
    for s in mt.get("slides", []):
        doc = next((d for d in data["documents"] if d["id"] == s.get("doc_id")), None)
        if s.get("pages"):
            parts.append(f"{doc['filename'] if doc else 'Folien'} S. {topics.format_pages(s['pages'])}")
    return "; ".join(parts) or "–"


def map_summary(cfg: dict, module_id: str, lec_id: str) -> int:
    """Zusammenfassung den Minithemen der Vorlesung zuordnen (ersetzt eine frühere Zuordnung). Wirft ai.AIError."""
    data = load_module(module_id)
    item = entry(data, lec_id)
    mts = topics.minitopics(data, lec_id)
    if not (item.get("text") or "").strip() or not mts:
        return 0
    result = ai.complete_json(MAP_PROMPT.format(
        text=item["text"], mts="\n".join(f"[{i}] {m['topic']}: {m['title']} ({_pages(m, data)}) – {m.get('summary', '')}"
                                         for i, m in enumerate(mts, start=1))),
        MAP_SCHEMA, max_tokens=8000, effort="low", task="check")
    for m in mts:  # frühere Einstufung aus der Nacharbeit dieser Vorlesung ersetzen
        (data.get("mastery") or {}).get(m["id"], {}).pop("nacharbeit", None)
    practice: list[tuple[dict, str]] = []
    linked = 0
    for link in result.get("links", []):
        for nr in sorted(set(link["minitopics"])):
            if not 1 <= nr <= len(mts):
                continue
            linked += 1
            if link["category"] == "ueben":
                practice.append((mts[nr - 1], link["text"].strip()))
            else:
                mastery.apply_nacharbeit(data, mts[nr - 1], link["category"], link["text"].strip())
    for mt, text in practice:
        nach = mastery.entry(data, mt["id"]).get("nacharbeit")
        if nach:
            nach["practice"] = " | ".join(x for x in (nach.get("practice"), text) if x)
        else:
            mastery.apply_nacharbeit(data, mt, "wackelig", "", text)
    data.setdefault("nacharbeit", {}).setdefault(lec_id, {})["mapped_at"] = now_iso()
    save_module(module_id)
    return linked


def needs_mapping(data: dict, lec_id: str) -> bool:
    item = entry(data, lec_id)
    return bool((item.get("text") or "").strip()) and bool(topics.minitopics(data, lec_id)) \
        and (not item.get("mapped_at") or item.get("updated_at", "") > item["mapped_at"])


def ensure_mapped(cfg: dict, module_id: str) -> None:
    if not ai.is_available():
        return
    data = load_module(module_id)
    for lec_id in list((data.get("nacharbeit") or {})):
        if needs_mapping(data, lec_id):
            try:
                map_summary(cfg, module_id, lec_id)
            except ai.AIError:
                continue


def rated(data: dict, lec_id: str) -> dict[str, list[dict]]:
    """Minithemen der Vorlesung nach Einstufung aus der Nacharbeit (ohne Einstufung: Schlüssel None)."""
    out: dict = {k: [] for k in mastery.NACH_RATINGS}
    out[None] = []
    for m in topics.minitopics(data, lec_id):
        out[mastery.nacharbeit_rating(data, m)].append(m)
    return out
