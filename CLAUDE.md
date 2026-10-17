# Amelies Lern-App (Streamlit, BWL 1. Semester LMU)

Nutzerin ist Nicht-Programmiererin: Antworten auf Deutsch, einfach erklärt. Nach jeder Änderung: testen,
committen, auf den Arbeits-Branch pushen und sagen, dass sie auf share.streamlit.io „Reboot app“ drücken muss.
Keine Secrets (API-Key, GitHub-Token, App-Passwort) ins Repo.

## Aufbau
- `app.py` – Login, Seitenleiste (Navigation als Buttons, Module mit Farbe/Symbol), Routing über `PAGES` in `views/common.py`,
  Zurück-Button oben auf jeder Seite (Verlauf in `views/common.py`: `track_history`/`go_back`, Reiter mit `on_change="rerun"`).
- `config.json` – Module (Farbe, Material-Symbol, Stundenplan, Kapitel inkl. `nr`, Vorlesungen, Übungen, Fristen-Wochentage `deadlines`,
  Klausurformat `exam_format`: mc_multi / sc4 / open / mixed → Karten-Prompt und Quiz), Kalender.
- `utils/` – `storage.py` (JSON in `data/`, Cloud-Sync), `cloud_sync.py` (GitHub-Repo, PDFs werden erst bei Bedarf geladen),
  `units.py` (Vorlesungen/Übungen = Einheiten), `planner.py` (To-dos, Fristen), `learning.py` (Folienanalyse, Karten
  inkl. Abdeckung jeder Seite und Prüfdurchgang, Definitionen, Seiten mit Abbildungen genau lesen),
  `spaced_repetition.py` (FSRS mit Klausurtermin: Zielquote, Endspurt, neue Karten pro Tag), `ai.py` (Anthropic, Modell pro Aufgabe in `TASKS`),
  `textbook.py` (Lehrbuch, nur für Tutor), `definitions.py`, `exam_plan.py`, `weakness.py`, `notify.py` (ntfy-Push).
- `views/` – `today_view.py`, `dashboard.py` (Wochenübersicht), `cards_center.py` (Karteikarten-Lernzentrum: Lernstand,
  Empfehlung, freie Auswahl, Focus Mode ohne Seitenleiste mit Zurück zur vorigen Karte), `settings_view.py` (mit Reitern
  Export und Backup aus `export_view.py`), `module_view.py` (Reiter Ablauf / Lernen & Klausur /
  Definitionen / Dateien / Formeln & Notizen), `module_tabs/` (Vorlesungs- und Übungsseiten, Lernen, Tutor …).

## Regeln für KI-Inhalte
- Karteikarten nur aus Folien/Skript + Nachbereitung; „betont“ gründlicher (priority high), „kurz angerissen“ knapp
  (low); keine Karten, die Beispiele abfragen (Anwendungskarten zum Konzept erlaubt); Erklärung 40–120 Wörter;
  jede Definitionskarte → auch Reiter Definitionen. Lehrbuch nur im Tutor. Jede Seite: Karte oder Grund fürs Überspringen.
- Karten entstehen nur auf Klick (nach der Nachbereitung), nie automatisch.
- Modelle: Zusammenfassung Haiku 5.5, Karten Sonnet 5.5, Tutor Sonnet 5.5, Antwort-/Kartenprüfung Haiku 5.5
  (änderbar in den Einstellungen).
- Vorbereiten (Haiku, effort low): Must-Watch (2–3 Folien), Tabelle Folie | Begriff | Kurzerklärung | Worauf achten,
  Ablauf als Stichpunkte, 3 Pre-Check-Fragen – kein Fließtext, alles mit Foliennummer.
- Keine erklärenden Hinweistexte in der Oberfläche ergänzen (Nutzerin hat sie bewusst entfernen lassen).
- PDFs zuerst nur als Text lesen; Seiten mit Abbildungen vorschlagen, genau lesen nur nach Auswahl.

## Testen
- `ruff check --select F,E9 --line-length 120 .`
- `python -m pytest tests -q` (Schnelltest: alle Seiten und Module öffnen; räumt `data/` selbst auf)
- Abhängigkeiten installiert der SessionStart-Hook (`.claude/hooks/session-start.sh`) in Cloud-Sitzungen automatisch.
