"""Signalwort-/Operatoren-Analyse für Altklausuren.

Operatoren sind die Arbeitsanweisungen einer Aufgabe („Nennen Sie“, „Erläutern Sie“,
„Berechnen Sie“ …). Sie legen fest, wie tief und in welcher Form geantwortet werden
muss. Die Anforderungsbereiche (AFB) folgen der üblichen Einteilung:
    I   = Reproduktion, II = Anwendung/Transfer, III = Beurteilung/Problemlösung
"""

from __future__ import annotations

import re
from collections import Counter

OPERATORS = [
    {"name": "Nennen / Geben Sie an", "pattern": r"\bnenne[nt]?\b|\bgeben sie\b.{0,40}\ban\b|\bangeben\b|\bnennen sie\b",
     "afb": "I", "how": "Stichpunkte ohne Erklärung genügen. Genau so viele Punkte wie verlangt – Überzählige werden oft nicht gewertet.",
     "example": "„Nennen Sie drei Bestandteile des Jahresabschlusses.“ → Bilanz, GuV, Anhang."},
    {"name": "Definieren Sie", "pattern": r"\bdefinieren sie\b|\bdefinition\b",
     "afb": "I", "how": "Präzise Fachdefinition in 1–2 Sätzen: Oberbegriff + unterscheidendes Merkmal. Formel ergänzen, falls vorhanden.",
     "example": "„Definieren Sie die Preiselastizität.“ → relative Mengenänderung / relative Preisänderung + Formel."},
    {"name": "Beschreiben / Stellen Sie dar", "pattern": r"\bbeschreiben sie\b|\bstellen sie\b.{0,40}\bdar\b|\bdarstellen\b",
     "afb": "I–II", "how": "Sachverhalt strukturiert und vollständig wiedergeben (ggf. mit Skizze), noch ohne Bewertung.",
     "example": "„Stellen Sie den Ablauf der Inventur dar.“"},
    {"name": "Erläutern Sie", "pattern": r"\berl(ä|ae)uter",
     "afb": "II", "how": "Aussage + Begründung + Beispiel. In ganzen Sätzen, Zusammenhänge („weil“, „dadurch“) sichtbar machen.",
     "example": "„Erläutern Sie den Leverage-Effekt.“ → Mechanismus, Bedingung r_GK > r_FK, Zahlenbeispiel."},
    {"name": "Erklären Sie", "pattern": r"\berkl(ä|ae)ren sie\b|\berkl(ä|ae)rung\b",
     "afb": "II", "how": "Ursache-Wirkungs-Kette aufzeigen: Warum ist etwas so? Fachbegriffe verwenden.",
     "example": "„Erklären Sie, warum die Nachfragekurve fällt.“"},
    {"name": "Berechnen / Ermitteln / Bestimmen Sie", "pattern": r"\bberechne|\bermitteln\b|\bermitteln sie\b|\bbestimmen sie\b|\bbestimme\b",
     "afb": "II", "how": "Formel allgemein hinschreiben → Werte einsetzen → Ergebnis mit Einheit, sinnvoll gerundet. Rechenweg zählt Punkte!",
     "example": "„Berechnen Sie den Kapitalwert bei i = 8 %.“"},
    {"name": "Zeigen Sie (rechnerisch)", "pattern": r"\bzeigen sie\b|\bweisen sie\b.{0,40}\bnach\b|\bnachweisen\b",
     "afb": "II–III", "how": "Das Ergebnis ist vorgegeben – entscheidend ist der lückenlose, nachvollziehbare Weg. Jeden Umformungsschritt angeben, am Ende explizit auf die Behauptung schließen.",
     "example": "„Zeigen Sie rechnerisch, dass die Funktion bei x = 2 ein Maximum hat.“ → f'(2)=0 und f''(2)<0."},
    {"name": "Leiten Sie her / Beweisen Sie", "pattern": r"\bleiten sie\b.{0,40}\bher\b|\bherleiten\b|\bbeweisen sie\b",
     "afb": "III", "how": "Von Annahmen/Definitionen ausgehend schrittweise zum Ergebnis; jede Umformung begründen.",
     "example": "„Leiten Sie die Rentenbarwertformel her.“"},
    {"name": "Skizzieren / Zeichnen Sie", "pattern": r"\bskizzieren\b|\bzeichnen sie\b|\bstellen sie\b.{0,40}\bgrafisch\b|\bgrafisch\b",
     "afb": "II", "how": "Achsen beschriften (inkl. Einheit), relevante Punkte/Schnittpunkte markieren, Legende. Skizze ≠ maßstabsgetreu.",
     "example": "„Skizzieren Sie Angebot und Nachfrage und kennzeichnen Sie die Konsumentenrente.“"},
    {"name": "Interpretieren Sie", "pattern": r"\binterpretier",
     "afb": "II–III", "how": "Ergebnis in Worte fassen und ökonomisch einordnen: Was bedeutet der Wert konkret für das Unternehmen/den Markt?",
     "example": "„Interpretieren Sie r = −0,85.“ → starker negativer linearer Zusammenhang."},
    {"name": "Vergleichen / Grenzen Sie ab", "pattern": r"\bvergleichen\b|\bvergleich\b|\bgrenzen sie\b.{0,40}\bab\b|\babgrenz|\bunterscheiden sie\b|\bunterschied",
     "afb": "II", "how": "Gemeinsame Kriterien festlegen und Gemeinsamkeiten UND Unterschiede gegenüberstellen – ideal als Tabelle.",
     "example": "„Grenzen Sie Rückstellungen von Verbindlichkeiten ab.“"},
    {"name": "Begründen Sie", "pattern": r"\bbegr(ü|ue)nden\b|\bbegr(ü|ue)ndung\b",
     "afb": "II–III", "how": "Behauptung mit stichhaltigen Argumenten (Gesetz, Modell, Rechnung) stützen. Ohne Begründung meist 0 Punkte.",
     "example": "„Ist die Aussage richtig? Begründen Sie Ihre Antwort.“"},
    {"name": "Beurteilen / Bewerten Sie", "pattern": r"\bbeurteil|\bbewerten sie\b|\bbewertung\b|\bstellung\b.{0,20}\bnehmen\b",
     "afb": "III", "how": "Kriterien nennen → Pro/Contra abwägen → eigenes, begründetes Urteil formulieren.",
     "example": "„Beurteilen Sie die Vorteilhaftigkeit der Investition.“"},
    {"name": "Diskutieren / Erörtern Sie", "pattern": r"\bdiskutier|\ber(ö|oe)rtern\b",
     "afb": "III", "how": "Mehrere Perspektiven/Argumente gegenüberstellen, Annahmen kritisch prüfen, Fazit ziehen.",
     "example": "„Diskutieren Sie die Grenzen der Kapitalwertmethode.“"},
    {"name": "Prüfen Sie / Wahr oder falsch", "pattern": r"\bpr(ü|ue)fen sie\b|\bwahr\b.{0,15}\bfalsch\b|\brichtig\b.{0,15}\bfalsch\b|\bkreuzen sie\b",
     "afb": "II", "how": "Klare Entscheidung (richtig/falsch) + kurze Begründung bzw. Gegenbeispiel. Bei MC: Punktabzug für Falschantworten beachten!",
     "example": "„Prüfen Sie, ob die Matrix invertierbar ist.“ → det(A) ≠ 0?"},
    {"name": "Buchen Sie / Bilden Sie Buchungssätze", "pattern": r"\bbuchen sie\b|\bbuchungss(ä|ae)tz|\bverbuchen\b|\bkontier",
     "afb": "II", "how": "Format „Soll an Haben  Betrag“. Alle Konten exakt benennen, USt/Vorsteuer nicht vergessen, Summe Soll = Summe Haben.",
     "example": "„Buchen Sie den Wareneinkauf auf Ziel (1.190 € brutto).“ → Waren 1.000 / VSt 190 an Verb. LuL 1.190."},
    {"name": "Erstellen / Stellen Sie auf", "pattern": r"\berstellen sie\b|\bstellen sie\b.{0,40}\bauf\b|\baufstellen\b",
     "afb": "II", "how": "Vollständige formale Struktur liefern (Bilanz, GuV, Tabelle, Lagrange-Funktion …) – Gliederung nach Vorgabe der Vorlesung.",
     "example": "„Stellen Sie die Schlussbilanz auf.“"},
    {"name": "Analysieren / Untersuchen Sie", "pattern": r"\banalysieren\b|\buntersuchen sie\b",
     "afb": "II–III", "how": "Systematisch nach Kriterien zerlegen, Ergebnisse festhalten und Schlussfolgerung ziehen.",
     "example": "„Untersuchen Sie die Funktion auf Extremstellen.“"},
]

for _op in OPERATORS:
    _op["regex"] = re.compile(_op["pattern"], re.IGNORECASE)

_TASK = re.compile(r"\b(Aufgabe|Frage|Teilaufgabe)\s*(\d+[a-z]?)", re.IGNORECASE)
_POINTS = re.compile(r"\(?\s*(\d{1,3})\s*(?:Punkte|Pkt\.?|P\.)\s*\)?", re.IGNORECASE)


def analyze_operators(text: str, context_chars: int = 90) -> list[dict]:
    results = []
    for op in OPERATORS:
        matches = list(op["regex"].finditer(text))
        if not matches:
            continue
        snippets = []
        for m in matches[:6]:
            start = max(0, m.start() - context_chars // 3)
            end = min(len(text), m.end() + context_chars)
            snippets.append("…" + re.sub(r"\s+", " ", text[start:end]).strip() + "…")
        results.append({"Operator": op["name"], "Anzahl": len(matches), "AFB": op["afb"],
                        "So antworten": op["how"], "Beispiel": op["example"], "snippets": snippets})
    results.sort(key=lambda r: r["Anzahl"], reverse=True)
    return results


def analyze_structure(text: str) -> dict:
    tasks = Counter(m.group(2) for m in _TASK.finditer(text))
    points = [int(m.group(1)) for m in _POINTS.finditer(text)]
    points = [p for p in points if 0 < p <= 120]
    afb_counter: Counter = Counter()
    for op in OPERATORS:
        n = len(op["regex"].findall(text))
        if n:
            afb_counter[op["afb"]] += n
    return {"n_tasks": len(tasks), "points": points, "total_points": sum(points), "afb": dict(afb_counter)}
