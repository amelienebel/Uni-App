"""Folienanalyse (Zusammenfassung) und Lernkarten-Erstellung für einzelne Vorlesungen und Übungen."""

from __future__ import annotations

import re

from utils import ai
from utils import definitions as defs
from utils import spaced_repetition as sr
from utils.config import exam_format, get_module
from utils.pdf_parser import heuristic_analysis
from utils.storage import (chapter_label, get_document_pages, get_document_text, load_module, now_iso, read_data_file,
                           save_module, set_document_pages, suggest_formulas)
from utils.units import lecture_notes, unit_cards, unit_docs

_PREP_TASKS = """Ich lese deine Vorbereitung auf dem Mac mit, während ich auf dem iPad durch die Folien scrolle.
Darum: KEIN Fließtext, nur Stichpunkte und Tabellenzellen (Tabellen im Telegrammstil, je max. ~15 Wörter).
Jede Angabe MUSS mit Foliennummer(n) verknüpft sein – "slides" immer als Nummer oder Bereich, z. B. "12" oder "12–15".

Erstelle:
1. must_watch: genau 2–3 Folien/Konzepte, die ich mir unbedingt VOR der Vorlesung ansehen sollte (komplexe Grafiken,
   Formeln, schwierige Definitionen): slides, topic (Begriff/Folientitel), why (ein kurzer Grund).
2. concept_table: alle Kernbegriffe und Formeln in Folienreihenfolge: slides, term (Kernbegriff oder Formel, Formeln
   in $...$), short (Kurzerklärung, max. ~15 Wörter), watch_out (worauf achten: Falle, Verwechslung, Bedingung –
   max. ~12 Wörter).
3. summary: Zusammenfassung entlang der Folien als Markdown-Stichpunktliste – ergänzend zu den Folien, so dass ich
   ohne Vorwissen sofort verstehe, worum es geht. Jeder Abschnitt beginnt mit „**Folie N–M** · Thema“, darunter
   3–6 Unterpunkte in einfacher, verständlicher Sprache (je 1–2 ganze Sätze, max. ~40 Wörter): Was bedeutet das?
   Warum ist das wichtig? Wie hängt es mit dem Vorherigen zusammen? Fachbegriffe beim ersten Auftreten in
   Alltagssprache erklären, Formeln in Worten deuten (was steigt, was sinkt). Erkläre, was die Folien nur andeuten,
   statt sie abzuschreiben. Nur Inhalte der Folien, kein neuer Stoff. Keine Absätze, keine Überschriften.
4. quiz: genau 5 Quizfragen zum Selbsttest, die das Verständnis der wichtigsten Inhalte prüfen. {quiz_format}
   Plausible Distraktoren (typische Denkfehler). correct_indices = Indizes der richtigen Optionen (ab 0).
   explanation: kurz, warum richtig bzw. falsch, mit Foliennummer. slides: Foliennummer(n) der Frage.
5. formulas: alle mathematischen und betriebswirtschaftlichen Formeln als sauberes LaTeX (ohne $-Zeichen) mit Name,
   kurzer Erklärung der Variablen und Foliennummer (page). Übernimm sie exakt wie auf den Folien."""

ANALYSIS_PROMPT = """Bereite mich auf die Vorlesung vor. Unten stehen die Folien für das Modul „{module}“,
{chapter}. Jede Folie ist mit „--- Folie N ---“ markiert.

""" + _PREP_TASKS + """

<folien>
{text}
</folien>"""

# Bleibt immer gleich ⇒ wird als Systemprompt gecacht (siehe ai._request)
CARDS_SYSTEM = """Du erstellst Karteikarten für eine Lern-App mit Spaced Repetition (BWL-Bachelor, LMU München,
1. Semester). Die Nutzerin tippt ihre Antwort, sieht danach die Musterantwort und bewertet sich selbst in 4 Stufen
(Gar nicht / Etwas / Gut / Perfekt). Daraus folgt: Jede Antwort muss aus dem Kopf reproduzierbar und mit dem eigenen
Getippten vergleichbar sein.

# Ziel
Wer alle Karten beherrscht, kann den KOMPLETTEN Prüfungsstoff dieser Einheit. Nichts Prüfungsrelevantes darf fehlen.

# Quellen und Gewichtung
1. DOKUMENTE (<dokument nr="N">): Seiten markiert mit „--- Folie N ---“ (Folien), „--- Skript S. N ---“ (Skript)
   oder „--- Seite N ---“ (Übungsblatt, Lösung, Sonstiges). Folien sind die Hauptquelle und bestimmen Umfang und
   Struktur. Das Skript ist gleichrangig und ergänzt Definitionen, Herleitungen, Zusammenhänge.
2. NACHBEREITUNG der Nutzerin, markiert als:
   - [NOTIZEN] – eigene Mitschrift. Was nicht auf den Folien steht, wie Folieninhalt behandeln.
   - [BETONT] – in der Vorlesung hervorgehoben ⇒ immer eigene Karte(n), priority "high", gründlicher, ggf. mehrere
     Karten inkl. Verständnis- oder Anwendungsfrage.
   - [ANGERISSEN] – nur kurz erwähnt ⇒ höchstens eine knappe Karte, priority "low", oder gar keine, wenn es nur ein
     Nebensatz war.
   - [BEISPIELE] – in der Vorlesung genannte Beispiele ⇒ nur zur Veranschaulichung in "explanation", nie als eigene
     Karte.
   - [TAFELBILD] – abgetippte Tafelbilder/Screenshots ⇒ wie Notizen.
Kein Wissen außerhalb dieser Quellen in "answer". In "explanation" darfst du allgemeines Fachwissen nutzen, um
verständlich zu erklären – aber nichts, was den Quellen widerspricht, und keinen zusätzlichen Prüfungsstoff.

# Auswahl
Leitfrage für jede Karte: Könnte das sinnvoll in der Prüfung abgefragt werden?
- Behalten: Definitionen, Abgrenzungen zwischen Begriffen, Annahmen, Abläufe, Klassifikationen, Formeln,
  Rechenschemata, Vor- und Nachteile, Kernbefunde, Anwendung auf Fälle.
- Streichen: Organisatorisches, Lernziele, Gliederung/Agenda, Literaturlisten, Allgemeinplätze und alles, was
  schon in VORHANDENE KARTEN abgefragt wird.
- Ein Merkmal, das zwei Begriffe unterscheidet, ist nie ein Allgemeinplatz.
- Beispiele (Unternehmen, Anekdoten, konkrete Zahlen) muss die Nutzerin NICHT auswendig können: keine Karte, die
  ein Beispiel abfragt („Welches Unternehmen …?“). Zahlenbeispiele ⇒ Rechenweg/Schema als Karte, nicht die Zahlen.
- Durchgearbeitete Fallstudien: Karte zum Kernbefund und dazu, wie das Konzept angewendet wird – nicht die Details.
- Anwendungskarten ("application") sind erwünscht bei zentralen Konzepten: kurzer, selbst formulierter Fall, auf den
  die Nutzerin ein Konzept aus den Unterlagen anwendet.
- Richtwert: 0,5–1 Karte pro Inhaltsfolie, dichte Folien auch 2–3. Deutlich mehr Karten als Folien ⇒ Bündelung prüfen.
- Prüfungsform beachten (PRÜFUNG im Input): Rechenklausur ⇒ mehr Schema- und Rechenkarten; Open Book ⇒ keine Karten
  zu reinem Nachschlagewissen, sondern Anwendung.
- Klausurformat beachten (KLAUSURFORMAT im Input) – als Gewichtung, nicht als Ersatz für die Regeln oben:
  - Multiple Choice (mehrere richtig) ⇒ etwas mehr Karten zu genauen Bedingungen, Ausnahmen, Abgrenzungen und
    typischen Fehlvorstellungen (Aussagen, die man sicher als richtig/falsch erkennen muss); Rechenkarten so, dass
    das Ergebnis sicher und schnell berechnet werden kann.
  - Single Choice (genau eine richtig) ⇒ etwas mehr Karten, die ähnliche Begriffe, Fälle oder Buchungen präzise
    unterscheiden; in "explanation" die typische Verwechslung nennen.
  - Offene Fragen ⇒ etwas mehr Rechenschema- und Erläuterungskarten; Antwort mit vollständigem Lösungsweg in
    Schritten.
  - Unbekannt/gemischt ⇒ ausgewogen.
- Übungen: Lösungswege (Ansatz, Rechenschritte, Interpretation des Ergebnisses) als Karten, keine Zahlen auswendig.

# Vollständigkeit (sehr wichtig)
Gehe die Dokumente Seite für Seite durch. JEDE Seite muss danach entweder in "sources" mindestens einer Karte stehen
oder in "skipped" mit kurzem Grund (z. B. „Titelfolie“, „Gliederung“, „Organisatorisches“, „Literaturliste“,
„nur Beispiel ohne neuen Inhalt“, „schon durch vorhandene Karte abgedeckt“). Keine Seite auslassen.

# Kartentypen ("type")
- "definition" – Begriff erklären. Jeder in den Unterlagen definierte Fachbegriff bekommt GENAU EINE
  Definitionskarte; der Begriff steht im Feld "term" (bei allen anderen Typen "term" leer lassen). Die Antwort ist
  die präzise Definition, möglichst im Wortlaut der Quelle. Begriffe aus VORHANDENE DEFINITIONEN nicht wiederholen.
- "list" – Aufzählung/Klassifikation (alle Elemente in eine Karte)
- "process" – Ablauf mit fester Reihenfolge
- "formula" – Formel + Bedeutung der Bestandteile
- "calculation" – Rechenschema/Vorgehen, kein Zahlenbeispiel
- "comparison" – nur wenn die Quelle zwei Konzepte explizit gegenüberstellt
- "application" – Transfer: kurzer Fall, Nutzerin wendet Konzept an
- "graphic" – Inhalt einer Grafik in Worten; die Seite mit der Grafik als erste in "sources"

# Fragen ("front")
- Eigenständig verständlich (die App zeigt Karten einzeln und gemischt) ⇒ nötigen Kontext in die Frage, z. B.
  „CAPM: Formel und Bedeutung von Beta?“ statt nur „Formel?“.
- Kurz, präzise, in der Sprache der Vorlesung.
- Zusammengehöriges in einer Frage: „Definition + Annahmen?“, „Arten + Kurzbeschreibung?“.

# Antworten ("answer")
- Musterantwort, die man tippen könnte: ein Listenelement = ein Stichpunkt, Telegrammstil, meist 2–5 Punkte,
  höchstens ~40 Wörter (Schemata/Abläufe länger). Unterpunkte mit zwei führenden Leerzeichen.
- Keine Aufzählungszeichen voranstellen; nur nummerieren („1. …“), wenn die Reihenfolge inhaltlich zählt.
- Bedingungen nie weglassen, Kriterienlisten vollständig, Fachbegriffe exakt wie in der Quelle.
- „⇒“ für Folgen, „vs.“ für Gegenüberstellungen.
- Formeln in LaTeX mit $...$ (inline) bzw. $$...$$ (eigene Zeile).
- "keywords": 2–6 Kernbegriffe, die in einer guten getippten Antwort vorkommen müssen (exakt so geschrieben wie in
  der Antwort). Daran prüft die App die getippte Antwort.

# Erklärung ("explanation")
40–120 Wörter Fließtext, Ziel: echtes Verständnis statt Auswendiglernen. Nicht die Musterantwort wiederholen.
- Warum ist das so / wozu braucht man es?
- Intuition oder Alltagsbeispiel
- Typischer Fehler oder Verwechslungsgefahr
- Verbindung zu anderen Konzepten, wenn die Quelle sie herstellt
- Bei Formeln: was passiert, wenn sich eine Größe ändert

# Gliederung
- "section": Pfad entlang der Folienstruktur, z. B. ["2 Portfoliotheorie", "2.1 Rendite und Risiko"].
- "chapter_hint": Titel des passenden Kapitels aus der KAPITEL-Liste (exakt übernehmen) oder leer.
- Ein Konzept = eine Karte; Teilaspekte als Stichpunkte in diese Karte.
- Gleichartige Geschwister (z. B. drei Forschungsarten): erst Überblickskarte, dann je eine Karte mit gleich
  aufgebauter Frage.

# Priorität ("priority")
- "high": [BETONT], Kerndefinitionen, zentrale Formeln, alles, was die Folien als zentral markieren
- "normal": Standard
- "low": [ANGERISSEN], Randaspekte
Die App plant damit bis zur Prüfung (high zuerst und öfter, low zuletzt) – bewusst vergeben, nicht alles "high".

# Quellen
- "sources": [{"doc": Nummer des Dokuments, "pages": [Seitennummern laut Marker]}] – alle Seiten, aus denen die
  Karte stammt.
- "from_notes": true, wenn die Karte (auch) auf der Nachbereitung beruht.

# Qualität
- Formeln gegen die Quelle prüfen (Vorzeichen, Indizes).
- Offensichtlicher Fehler in der Quelle ⇒ korrigiert übernehmen und in "warnings" nennen.
- Unklarer/unlesbarer Text ⇒ nicht raten: "needs_review": true und Hinweis in "warnings" (sonst false).
- Widerspruch zwischen Folien und Skript ⇒ Folien gelten; Widerspruch in "warnings" und in "explanation" erwähnen.
- "warnings" kurz und konkret (mit Seitenangabe), leer, wenn alles klar ist."""

CARDS_USER = """<meta>
MODUL: {module}
EINHEIT: {scope}
PRÜFUNG: {exam}
KLAUSURFORMAT: {exam_format}
KAPITEL: {chapters}
</meta>
{focus}
<vorhandene_karten>
{existing}
</vorhandene_karten>

<vorhandene_definitionen>
{existing_defs}
</vorhandene_definitionen>

<nachbereitung>
{notes}
</nachbereitung>

<dokumente>
{documents}
</dokumente>"""

FOCUS_NOTE = """
AUFTRAG: Bisher fehlen Karten zu einigen Seiten. Unten stehen NUR diese Seiten. Erstelle die fehlenden Karten
bzw. trage Seiten ohne Prüfungsinhalt in "skipped" ein. Nichts doppeln, was in VORHANDENE KARTEN steht.
"""

CHECK_PROMPT = """Prüfe die Karteikarten unten einzeln gegen die Unterlagen. Melde NUR echte inhaltliche Fehler:
falsche oder unvollständige Formeln (Vorzeichen, Indizes, Variablen), falsche Aussagen, fehlende Bedingungen oder
Kriterien, Widersprüche zu den Unterlagen. Stil, Länge und Formulierung ignorieren. "card" = Nummer der Karte,
"problem" = kurz, was falsch ist und wie es richtig lautet (mit Seite). Keine Fehler ⇒ leere Liste.

<unterlagen>
{material}
</unterlagen>

<karten>
{cards}
</karten>"""

# Seitenmarker je Dokumentart; eigene Lösungen sind keine Kartenquelle (können Fehler enthalten)
_PAGE_LABELS = {"folien": "Folie", "skript": "Skript S."}
_NOTE_MARKERS = (("text", "NOTIZEN"), ("emphasized", "BETONT"), ("briefly", "ANGERISSEN"), ("examples", "BEISPIELE"))

DEFINITIONS_PROMPT = """Sammle alle Definitionen aus den Unterlagen der Einheit „{title}“ im Modul „{module}“.
Jeder Fachbegriff, der in Folien, Skript oder meinen Notizen definiert oder erklärt wird: term + präzise
Definition, möglichst im Wortlaut der Unterlagen (keine Beispiele, kein Wissen von außerhalb).
Diese Begriffe gibt es schon (nicht wiederholen): {existing}

<unterlagen>
{material}
</unterlagen>"""


VISUAL_PROMPT = """Bereite mich auf die Vorlesung vor. Das angehängte PDF sind die Folien für das Modul „{module}“,
{chapter}. Lies jede Folie vollständig – auch Formeln, Tabellen, Diagramme und Abbildungen.

Zusätzlich zu den Punkten unten: slides – für JEDE Folie (page = Foliennummer) eine vollständige Textfassung: aller
Text, Formeln exakt als LaTeX in $...$, Tabellen als Markdown, Diagramme/Abbildungen in [eckigen Klammern] kurz, aber
mit allen Achsen, Werten und Aussagen beschrieben. Nichts zusammenfassen, nichts weglassen.

""" + _PREP_TASKS


QUIZ_FORMATS = {
    "mc_multi": 'Wie in der Klausur: type "mc_multi", genau 5 Optionen, eine oder mehrere richtig.',
    "sc4": 'Wie in der Klausur: type "mc", genau 4 Optionen, genau eine richtig.',
}
QUIZ_FORMAT_MIXED = ('Gemischt: type "mc" (genau 4 Optionen, genau eine richtig) und type "mc_multi" (genau 5 '
                     'Optionen, eine oder mehrere richtig).')


def _quiz_format(module: dict) -> str:
    return QUIZ_FORMATS.get(exam_format(module)["type"], QUIZ_FORMAT_MIXED)


def pending_figures(doc: dict) -> list[int]:
    """Seiten mit Abbildungen, über die noch nicht entschieden wurde (genau lesen oder überspringen)."""
    decided = set(doc.get("visual_pages", [])) | set(doc.get("skipped_figures", []))
    return [p for p in doc.get("figure_pages", []) if p not in decided]


def _first_page(slides: str) -> int:
    match = re.search(r"\d+", slides or "")
    return int(match.group()) if match else 0


def _compat_fields(result: dict) -> None:
    """Felder, die Export, Tutor-Kontext und Offline-Karten weiter nutzen (Fachbegriffe, wichtige Folien)."""
    result["key_concepts"] = [{"term": row["term"], "explanation": row["short"]}
                              for row in result.get("concept_table", [])]
    result["important_slides"] = [{"page": _first_page(m["slides"]), "reason": f"{m['topic']}: {m['why']}"}
                                  for m in result.get("must_watch", [])]


MAX_VISUAL_BYTES = 30 * 1024 * 1024


def visual_enabled() -> bool:
    from utils.storage import load_settings

    return bool(load_settings().get("ai", {}).get("visual_pdf"))


def run_analysis(cfg: dict, module_id: str, doc: dict, visual: bool | None = None) -> str:
    """Analysiert einen Foliensatz und legt Formel-Vorschläge zur Prüfung ab. Gibt eine Statusmeldung zurück.

    visual=True: Claude liest das PDF selbst (inkl. Formeln und Grafiken) und ersetzt den gespeicherten Text
    durch diese genauere Fassung – davon profitieren auch Karteikarten, Tutor und Podcast. Kostet mehr.
    """
    module = get_module(cfg, module_id)
    data = load_module(module_id)
    visual = visual_enabled() if visual is None else visual
    chapter = chapter_label(data, doc.get("chapter_id")) if doc.get("chapter_id") else "ohne Kapitelangabe"
    if ai.is_available() and visual and doc.get("kind") != "image":
        content = read_data_file(doc["path"])
        if len(content) > MAX_VISUAL_BYTES:
            raise ai.AIError("Die Datei ist für die genaue Lesung zu groß (max. 30 MB). Bitte normal analysieren.")
        result = ai.complete_json([ai.pdf_block(content),
                                   {"type": "text", "text": VISUAL_PROMPT.format(module=module["name"], chapter=chapter,
                                                                                 quiz_format=_quiz_format(module))}],
                                  ai.VISUAL_ANALYSIS_SCHEMA, max_tokens=64000, task="summary")
        slides = sorted(result.pop("slides", []), key=lambda s: s["page"])
        if slides:
            set_document_pages(doc, [s["text"] for s in slides], "ki-genau")
        result["mode"] = "ki"
        result["visual"] = True
    elif ai.is_available():
        result = ai.complete_json(ANALYSIS_PROMPT.format(module=module["name"], chapter=chapter,
                                                         quiz_format=_quiz_format(module),
                                                         text=get_document_text(doc, label="Folie")),
                                  ai.ANALYSIS_SCHEMA, effort="low", task="summary")
        result["mode"] = "ki"
    else:
        result = heuristic_analysis(get_document_pages(doc))
    if "concept_table" in result:
        _compat_fields(result)
    result["created_at"] = now_iso()
    doc["analysis"] = result
    save_module(module_id)
    added = suggest_formulas(module_id, result.get("formulas", []),
                             source=f"{doc['filename']} ({'KI' if result['mode'] == 'ki' else 'heuristisch'})",
                             chapter_id=doc.get("chapter_id"))
    msg = "Zusammenfassung erstellt (nur Text gelesen)." if not result.get("visual") else "Zusammenfassung erstellt."
    pending = pending_figures(doc)
    if pending and not result.get("visual"):
        msg += (f" Auf {len(pending)} Seite(n) sind Abbildungen ({', '.join(map(str, pending))}) – unter "
                "„Vorbereiten“ kannst du entscheiden, ob sie genau gelesen werden sollen.")
    if added:
        msg += (f" {added} Formel-Vorschlag/-Vorschläge – bitte unter „Formeln & Notizen“ prüfen, welche "
                "übernommen werden sollen.")
    return msg


def _notes_material(data: dict, unit: dict) -> str:
    notes = lecture_notes(data, unit["id"])
    parts = [f"{label}:\n{notes[field]}" for field, label in
             (("text", "Meine Notizen"), ("emphasized", "Vom Dozenten betont"),
              ("briefly", "Nur kurz angerissen"), ("examples", "Genannte Beispiele")) if notes[field].strip()]
    parts += [f"Tafelbild „{img['name']}“:\n{img['transcript']}" for img in notes["images"]
              if img.get("transcript") and not img.get("in_notes")]
    return "\n\n".join(parts)


def unit_material(data: dict, unit: dict, summaries_only: bool = False) -> str:
    """Unterlagen + Nachbereitung einer Einheit als KI-Kontext (bei vielen Vorlesungen nur Zusammenfassungen)."""
    material = []
    for doc in unit_docs(data, unit):
        if summaries_only:
            analysis = doc.get("analysis") or {}
            text = analysis.get("summary", "") + "\n" + "\n".join(
                f"- {c['term']}: {c['explanation']}" for c in analysis.get("key_concepts", []))
        else:
            text = get_document_text(doc)
        if text.strip():
            material.append(f"<dokument name=\"{doc['filename']}\" typ=\"{doc['doc_type']}\">\n{text}\n</dokument>")
    if unit["kind"] == "lecture" and (notes := _notes_material(data, unit)):
        material.append(f"<nachbereitung>\n{notes}\n</nachbereitung>")
    return "\n\n".join(material)


def _offline_cards(data: dict, unit: dict) -> list[dict]:
    """Ohne KI: Karten aus Analyse-Fragen, Kernbegriffen und Notizzeilen der Form „Begriff: Erklärung“."""
    cards = []
    for doc in unit_docs(data, unit):
        analysis = doc.get("analysis") or {}
        for q in analysis.get("check_questions", []):
            cards.append({"front": q["question"], "back": q["answer"]})
    if unit["kind"] == "lecture":
        notes = lecture_notes(data, unit["id"])
        for line in (notes["text"] + "\n" + notes["emphasized"]).splitlines():
            m = re.match(r"^\s*[-•*]?\s*([^:]{3,60}):\s+(.{5,})$", line)
            if m:
                cards.append({"front": f"{m.group(1).strip()}?", "back": m.group(2).strip()})
    return cards


def _card_docs(data: dict, unit: dict) -> list[dict]:
    return [d for d in unit_docs(data, unit) if d["doc_type"] != "eigene_loesung"]


def _card_notes(data: dict, unit: dict) -> str:
    if unit["kind"] != "lecture":
        return ""
    notes = lecture_notes(data, unit["id"])
    parts = [f"[{marker}]\n{notes[field].strip()}" for field, marker in _NOTE_MARKERS if notes[field].strip()]
    parts += [f"[TAFELBILD] „{img['name']}“\n{img['transcript']}" for img in notes["images"]
              if img.get("transcript") and not img.get("in_notes")]
    return "\n\n".join(parts)


def _card_documents(docs: list[dict], only: dict[str, set[int]] | None = None) -> str:
    blocks = []
    for nr, doc in enumerate(docs, start=1):
        if only is not None and doc["id"] not in only:
            continue
        label = _PAGE_LABELS.get(doc["doc_type"], "Seite")
        pages = [f"--- {label} {i} ---\n{text}" for i, text in enumerate(get_document_pages(doc), start=1)
                 if only is None or i in only[doc["id"]]]
        if pages:
            blocks.append(f"<dokument nr=\"{nr}\" name=\"{doc['filename']}\" typ=\"{doc['doc_type']}\">\n"
                          + "\n\n".join(pages) + "\n</dokument>")
    return "\n\n".join(blocks)


def _exam_info(module: dict) -> str:
    return module.get("exam_note") or (f"Klausur am {module['exam_date']}" if module.get("exam_date") else "unbekannt")


def answer_markdown(lines: list[str]) -> str:
    """Stichpunkte der KI als Markdown-Liste (Unterpunkte eingerückt, nummerierte Schritte bleiben nummeriert)."""
    out = []
    for line in lines:
        text = re.sub(r"^[-•*–]\s+", "", line.strip())
        if not text:
            continue
        nested = line.startswith("  ")
        if text.startswith("$$") or re.match(r"^\d+[.)]\s", text):
            out.append(("   " if nested else "") + text)
        else:
            out.append(("  - " if nested else "- ") + text)
    return "\n".join(out)


def card_coverage(data: dict, unit: dict) -> list[dict]:
    """Pro Dokument: welche Seiten Karten haben, welche bewusst übersprungen wurden und welche noch fehlen."""
    cards = unit_cards(data, unit)
    skipped = data.get("card_skipped", {}).get(unit["id"], [])
    result = []
    for doc in _card_docs(data, unit):
        pages = get_document_pages(doc)
        covered = {p for c in cards for s in c.get("sources", []) if s.get("doc_id") == doc["id"]
                   for p in s.get("pages", [])}
        skip = {p: s["reason"] for s in skipped if s.get("doc_id") == doc["id"] for p in s.get("pages", [])}
        empty = {i for i, text in enumerate(pages, start=1) if len(text.strip()) < 15}
        result.append({
            "doc": doc, "pages": len(pages),
            "covered": sorted(p for p in covered if 1 <= p <= len(pages)),
            "skipped": {p: r for p, r in sorted(skip.items()) if p not in covered},
            "empty": sorted(empty - covered - set(skip)),
            "missing": [p for p in range(1, len(pages) + 1) if p not in covered and p not in skip and p not in empty],
        })
    return result


def cards_cost_estimate(data: dict, unit: dict, only: dict[str, set[int]] | None = None) -> float:
    """Grobe Kosten der Kartenerstellung: Eingabe ≈ Textlänge/3,5; Ausgabe ≈ 350 Tokens je Seite + Denken."""
    docs = _card_docs(data, unit)
    text = _card_documents(docs, only) + _card_notes(data, unit)
    n_pages = sum(len(v) for v in only.values()) if only else sum(len(get_document_pages(d)) for d in docs)
    tokens_in = (len(CARDS_SYSTEM) + len(text) + 60 * len(data["cards"])) / 3.5
    return ai.estimate_cost("cards", int(tokens_in), 350 * max(n_pages, 5) + 4000)


def generate_unit_cards(cfg: dict, module_id: str, unit: dict, only: dict[str, set[int]] | None = None) -> int:
    """Erstellt bzw. ergänzt die Lernkarten einer Vorlesung/Übung. Gibt die Zahl neuer Karten zurück.

    only = {doc_id: {Seiten}}: nur diese (bisher fehlenden) Seiten bearbeiten – günstiger beim Nachholen.
    """
    module = get_module(cfg, module_id)
    data = load_module(module_id)
    if not ai.is_available():
        return _generate_offline(data, module_id, unit)
    docs = _card_docs(data, unit)
    documents = _card_documents(docs, only)
    notes = _card_notes(data, unit) if only is None else ""  # beim Nachholen nur die fehlenden Seiten
    if not documents.strip() and not notes.strip():
        raise ai.AIError("Es gibt noch keine Unterlagen oder Notizen, aus denen Karten entstehen können.")
    title = unit.get("topic") or unit.get("title") or ""
    scope = (f"Vorlesung {unit.get('nr', '')} vom {unit['date']:%d.%m.%Y} – {title}" if unit["kind"] == "lecture"
             else f"Übung – {title}")
    chapters = {ch["title"]: ch["id"] for ch in data["chapters"]}
    prompt = CARDS_USER.format(
        module=module["name"], scope=scope, exam=_exam_info(module), exam_format=exam_format(module)["label"],
        chapters="; ".join(chapters) or "keine",
        focus=FOCUS_NOTE if only is not None else "",
        existing="\n".join(c["front"] for c in data["cards"]) or "keine",
        existing_defs="\n".join(d["term"] for d in defs.definitions(data)) or "keine",
        notes=notes or "keine", documents=documents or "keine")
    result = ai.complete_json(prompt, ai.CARDS_SCHEMA, system=CARDS_SYSTEM, max_tokens=64000, task="cards")

    def doc_sources(items: list[dict]) -> list[dict]:
        return [{"doc_id": docs[s["doc"] - 1]["id"], "pages": sorted(set(s["pages"]))}
                for s in items if 1 <= s["doc"] <= len(docs) and s["pages"]]

    known = {c["front"].strip().lower() for c in data["cards"]}
    added = 0
    for c in result.get("cards", []):
        front, back = c["front"].strip(), answer_markdown(c["answer"])
        if not front or not back or front.lower() in known:
            continue
        card = sr.new_card(front, back, source="KI", card_type=c["type"],
                           chapter_id=chapters.get(c.get("chapter_hint")) or unit.get("chapter_id"),
                           priority=c["priority"], keywords=[k.strip() for k in c["keywords"] if k.strip()],
                           explanation=c["explanation"].strip(), section=c["section"],
                           sources=doc_sources(c["sources"]), from_notes=c["from_notes"],
                           needs_review=c["needs_review"])
        card["unit"] = unit["id"]
        data["cards"].append(card)
        if c["type"] == "definition" and c["term"].strip():
            card["definition_term"] = defs.term_key(c["term"])
            defs.add_definition(data, c["term"], back, unit["id"], card["chapter_id"])
        known.add(front.lower())
        added += 1
    skipped = data.setdefault("card_skipped", {}).setdefault(unit["id"], [])
    skipped += [{"doc_id": s["doc_id"], "pages": s["pages"], "reason": r["reason"]}
                for r in result.get("skipped", []) for s in doc_sources([r])]
    warnings = data.setdefault("card_warnings", {})
    warnings[unit["id"]] = (warnings.get(unit["id"], []) if only is not None else []) + result.get("warnings", [])
    data.setdefault("cards_generated", {})[unit["id"]] = now_iso()
    save_module(module_id)
    return added


def _generate_offline(data: dict, module_id: str, unit: dict) -> int:
    """Ohne API-Key: einfache Karten aus Analyse-Fragen, Kernbegriffen und Notizzeilen."""
    for doc in unit_docs(data, unit):
        for c in (doc.get("analysis") or {}).get("key_concepts", []):
            if not c["term"].startswith("Folie"):
                defs.add_definition(data, c["term"], c["explanation"], unit["id"], unit.get("chapter_id"), "auto")
    known = {c["front"].strip().lower() for c in data["cards"]}
    added = 0
    for item in _offline_cards(data, unit):
        if not item["front"].strip() or item["front"].strip().lower() in known:
            continue
        card = sr.new_card(item["front"], item["back"], source="auto", chapter_id=unit.get("chapter_id"))
        card["unit"] = unit["id"]
        data["cards"].append(card)
        known.add(item["front"].strip().lower())
        added += 1
    data.setdefault("cards_generated", {})[unit["id"]] = now_iso()
    save_module(module_id)
    return added


def delete_unit_cards(module_id: str, unit: dict) -> int:
    """Alle Karten einer Einheit samt Abdeckungsinfo löschen (Definitionen im Reiter bleiben erhalten)."""
    data = load_module(module_id)
    ids = {c["id"] for c in unit_cards(data, unit)}
    data["cards"] = [c for c in data["cards"] if c["id"] not in ids]
    for key in ("card_skipped", "card_warnings", "cards_generated"):
        data.get(key, {}).pop(unit["id"], None)
    save_module(module_id)
    return len(ids)


def check_cost_estimate(data: dict, unit: dict) -> float:
    text = _card_documents(_card_docs(data, unit)) + _card_notes(data, unit)
    cards = unit_cards(data, unit)
    return ai.estimate_cost("check", int((len(text) + sum(len(c["front"]) + len(c["back"]) for c in cards)) / 3.5),
                            1500 + 60 * len(cards))


def check_unit_cards(cfg: dict, module_id: str, unit: dict) -> int:
    """Günstiger zweiter Durchgang: Karten gegen die Unterlagen prüfen. Fehler ⇒ Karte „bitte prüfen“ mit Hinweis."""
    data = load_module(module_id)
    cards = unit_cards(data, unit)
    if not cards:
        return 0
    material = _card_documents(_card_docs(data, unit)) + "\n\n" + _card_notes(data, unit)
    listing = "\n\n".join(f"[{i}] Frage: {c['front']}\nAntwort:\n{c['back']}" for i, c in enumerate(cards, start=1))
    result = ai.complete_json(CHECK_PROMPT.format(material=material, cards=listing), ai.CARD_CHECK_SCHEMA,
                              max_tokens=16000, task="check")
    found = 0
    for issue in result.get("issues", []):
        if 1 <= issue["card"] <= len(cards) and issue["problem"].strip():
            cards[issue["card"] - 1].update({"needs_review": True, "review_note": issue["problem"].strip()})
            found += 1
    data.setdefault("cards_checked", {})[unit["id"]] = now_iso()
    save_module(module_id)
    return found


def extract_definitions(cfg: dict, module_id: str, unit: dict) -> int:
    """Nur Definitionen einer Einheit sammeln (günstiger als Karten) – jede wird auch zur Karteikarte."""
    module = get_module(cfg, module_id)
    data = load_module(module_id)
    material = unit_material(data, unit)
    added = 0
    if material.strip() and ai.is_available():
        existing = "; ".join(d["term"] for d in defs.definitions(data)) or "keine"
        title = unit.get("topic") or unit.get("title") or ""
        result = ai.complete_json(DEFINITIONS_PROMPT.format(title=title, module=module["name"], existing=existing,
                                                            material=material), ai.DEFINITIONS_SCHEMA, max_tokens=32000,
                                  task="cards")
        for d in result.get("definitions", []):
            added += defs.add_definition(data, d["term"], d["definition"], unit["id"], unit.get("chapter_id"))
    else:
        for doc in unit_docs(data, unit):
            for c in (doc.get("analysis") or {}).get("key_concepts", []):
                added += defs.add_definition(data, c["term"], c["explanation"], unit["id"], unit.get("chapter_id"),
                                             "auto")
    data.setdefault("definitions_done", {})[unit["id"]] = now_iso()
    save_module(module_id)
    return added


PAGES_PROMPT = """Das angehängte PDF enthält {n} Folie(n) aus der Vorlesung „{module}“ (Original-Seiten: {pages}).
Der reine Textauszug hat Abbildungen, Diagramme, Tabellen und Formeln nicht erfasst. Lies jede Folie vollständig
und gib für jede (page = Position im angehängten PDF, beginnend bei 1) eine Textfassung zurück: aller Text,
Formeln als LaTeX in $...$, Tabellen als Markdown, Diagramme/Abbildungen in [eckigen Klammern] mit allen Achsen,
Werten und der Kernaussage beschrieben. Nichts weglassen, nichts erfinden."""

PAGES_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["slides"], "properties": {
    "slides": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                           "required": ["page", "text"],
                                           "properties": {"page": {"type": "integer"}, "text": {"type": "string"}}}}}}


def page_cost_estimate(n_pages: int) -> float:
    """Grobe Kosten fürs genaue Lesen: ca. 1.600 Eingabe- und 500 Ausgabe-Tokens pro Folie."""
    return ai.estimate_cost("summary", 1600 * n_pages + 500, 500 * n_pages)


def read_pages_visual(cfg: dict, module_id: str, doc: dict, pages: list[int]) -> str:
    """Liest nur die ausgewählten Seiten als Bild (Abbildungen, Formeln) und ersetzt dort den Textauszug.
    Danach wird die Zusammenfassung mit dem vollständigen Text neu erstellt."""
    import io

    from pypdf import PdfReader, PdfWriter

    module = get_module(cfg, module_id)
    reader = PdfReader(io.BytesIO(read_data_file(doc["path"])))
    pages = sorted(p for p in set(pages) if 1 <= p <= len(reader.pages))
    if not pages:
        return "Keine Seiten ausgewählt."
    writer = PdfWriter()
    for p in pages:
        writer.add_page(reader.pages[p - 1])
    buf = io.BytesIO()
    writer.write(buf)
    result = ai.complete_json([ai.pdf_block(buf.getvalue()),
                               {"type": "text", "text": PAGES_PROMPT.format(
                                   n=len(pages), module=module["name"], pages=", ".join(map(str, pages)))}],
                              PAGES_SCHEMA, max_tokens=32000, task="summary")
    texts = get_document_pages(doc)
    texts += [""] * (len(reader.pages) - len(texts))
    for slide in result.get("slides", []):
        if 1 <= slide["page"] <= len(pages):
            texts[pages[slide["page"] - 1] - 1] = slide["text"]
    set_document_pages(doc, texts, "teilweise-genau")
    doc["visual_pages"] = sorted(set(doc.get("visual_pages", [])) | set(pages))
    save_module(module_id)
    run_analysis(cfg, module_id, doc, visual=False)  # Zusammenfassung mit den neuen Inhalten
    return f"{len(pages)} Seite(n) genau gelesen und die Zusammenfassung aktualisiert."


REWRITE_PROMPT = """Überarbeite diese Karteikarte nach dem Feedback der Nutzerin (BWL, 1. Semester, LMU).
Setze das Feedback um, ändere sonst so wenig wie möglich. Inhaltlich nur, was in Karte oder Quelle steht – nichts
erfinden. Regeln: Frage eigenständig verständlich und präzise; Antwort als Stichpunkte im Telegrammstil (ein
Stichpunkt pro Listenelement, ohne Aufzählungszeichen, Unterpunkte mit zwei führenden Leerzeichen); Formeln in
LaTeX mit $...$; Erklärung 40–120 Wörter Fließtext fürs Verständnis; keywords 2–6 Kernbegriffe exakt wie in der
Antwort geschrieben.

<karte>
Frage: {front}
Antwort:
{back}
Erklärung: {explanation}
</karte>

<feedback>
{feedback}
</feedback>

<quelle>
{source}
</quelle>"""

REWRITE_SCHEMA = {"type": "object", "additionalProperties": False,
                  "required": ["front", "answer", "explanation", "keywords"], "properties": {
                      "front": {"type": "string"}, "answer": {"type": "array", "items": {"type": "string"}},
                      "explanation": {"type": "string"}, "keywords": {"type": "array", "items": {"type": "string"}}}}

_CARD_TEXT_FIELDS = ("front", "back", "explanation", "keywords")


def _card_source_text(data: dict, card: dict) -> str:
    parts = []
    for src in card.get("sources", []):
        doc = next((d for d in data["documents"] if d["id"] == src.get("doc_id")), None)
        if not doc:
            continue
        pages = get_document_pages(doc)
        parts += [f"--- {doc['filename']} S. {p} ---\n{pages[p - 1]}" for p in src.get("pages", [])
                  if 1 <= p <= len(pages)]
    return "\n\n".join(parts) or "(keine Quelle gespeichert)"


def rewrite_card(module_id: str, card: dict, feedback: str) -> None:
    """Karte nach Feedback umformulieren (vorige Fassung bleibt für „Rückgängig“ erhalten)."""
    data = load_module(module_id)
    result = ai.complete_json(REWRITE_PROMPT.format(front=card["front"], back=card["back"],
                                                    explanation=card.get("explanation", ""), feedback=feedback,
                                                    source=_card_source_text(data, card)),
                              REWRITE_SCHEMA, max_tokens=8000, effort="low", task="cards")
    card["previous"] = {f: card.get(f) for f in _CARD_TEXT_FIELDS}
    card.update({"front": result["front"].strip(), "back": answer_markdown(result["answer"]),
                 "explanation": result["explanation"].strip(), "keywords": result["keywords"]})
    card.setdefault("feedback", []).append({"date": now_iso(), "text": feedback})
    save_module(module_id)


def undo_rewrite(module_id: str, card: dict) -> None:
    if previous := card.pop("previous", None):
        card.update(previous)
        save_module(module_id)
