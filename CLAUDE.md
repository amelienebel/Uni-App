# Amelies Lern-App (Streamlit, BWL 1. Semester LMU)

Nutzerin ist Nicht-Programmiererin: Antworten auf Deutsch, einfach erklärt. Nach jeder Änderung: testen,
committen, auf den Arbeits-Branch pushen und sagen, dass sie auf share.streamlit.io „Reboot app“ drücken muss.
Keine Secrets (API-Key, GitHub-Token, App-Passwort) ins Repo.

## Aufbau
- `app.py` – Login, Seitenleiste (Navigation als Buttons, Module mit Farbe/Symbol), Routing über `PAGES` in `views/common.py`.
- `config.json` – Module (Farbe, Material-Symbol, Stundenplan, Kapitel inkl. `nr`, Vorlesungen, Übungen, Fristen-Wochentage `deadlines`), Kalender.
- `utils/` – `storage.py` (JSON in `data/`, Cloud-Sync), `cloud_sync.py` (GitHub-Repo, PDFs werden erst bei Bedarf geladen),
  `units.py` (Vorlesungen/Übungen = Einheiten), `planner.py` (To-dos, Fristen), `learning.py` (Folienanalyse, Karten,
  Definitionen, Seiten mit Abbildungen genau lesen), `ai.py` (Anthropic, Modell pro Aufgabe in `TASKS`),
  `textbook.py` (Lehrbuch, nur für Tutor), `definitions.py`, `exam_plan.py`, `weakness.py`, `notify.py` (ntfy-Push).
- `views/` – `today_view.py`, `dashboard.py` (Wochenplan), `module_view.py` (Reiter Ablauf / Lernen & Klausur /
  Definitionen / Dateien / Formeln & Notizen), `module_tabs/` (Vorlesungs- und Übungsseiten, Lernen, Tutor …).

## Regeln für KI-Inhalte
- Karteikarten nur aus Folien/Skript + Nachbereitung; „betont“ gründlicher, „kurz angerissen“ knapp; keine Beispiel-Karten;
  jede Definition → Reiter Definitionen + eigene Karte. Lehrbuch nur im Tutor.
- Modelle: Zusammenfassung Haiku 5.5, Karten Sonnet 5.5, Tutor Opus 5.5 (änderbar in den Einstellungen).
- PDFs zuerst nur als Text lesen; Seiten mit Abbildungen vorschlagen, genau lesen nur nach Auswahl.

## Testen
`ruff check --select F,E9 --line-length 120 .` und Streamlit-AppTest (`streamlit.testing.v1.AppTest`) gegen `app.py`;
danach `data/` und `__pycache__` aufräumen.
