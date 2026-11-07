# Amelies Lern-App (Streamlit, BWL 1. Semester LMU)

Nutzerin ist Nicht-Programmiererin: Antworten auf Deutsch, einfach erklärt. Nach jeder Änderung: testen,
committen, auf den Arbeits-Branch pushen und sagen, dass sie auf share.streamlit.io „Reboot app“ drücken muss.

**WICHTIG – sonst kommt nichts in der App an:** Die App auf share.streamlit.io läuft vom Branch
`claude/streamlit-bwl-learning-platform-c129um` (Standard-Branch des Repos). Jede fertige, getestete Änderung
zusätzlich dorthin bringen: `git fetch origin claude/streamlit-bwl-learning-platform-c129um`, den Branch in den
Arbeits-Branch mergen (Konflikte lösen, erneut testen), dann
`git push origin HEAD:claude/streamlit-bwl-learning-platform-c129um`. Die Nutzerin hat das ausdrücklich so
gewünscht (dauerhafte Erlaubnis). Erst danach „Reboot app“ sagen. Nie force-pushen.
Keine Secrets (API-Key, GitHub-Token, App-Passwort) ins Repo.

## Aufbau
- `app.py` – Login, Seitenleiste (Navigation als Buttons, darunter direkt die Module mit Farbe/Symbol – kein eigener
  Punkt „Module“), Routing über `PAGES` in `views/common.py`,
  Zurück-Button oben auf jeder Seite (Verlauf in `views/common.py`: `track_history`/`go_back`, Reiter mit `on_change="rerun"`).
  Seite/Modul/Einheit stehen in der Adresse (`?seite=…&modul=…&einheit=…`); ein kleines Skript (`st.html`, Container
  `watchdog`) lädt die Seite neu, wenn nach einer Pause „Verbindung verloren“ hängen bleibt (nur wenn `/_stcore/health`
  antwortet) und setzt das Cookie `lernapp_mobile` (`common.is_mobile`: Wochenübersicht auf dem Handy als Liste).
  `.streamlit/config.toml`: `disconnectedSessionTTL` 8 h, `websocketPingInterval` 25. Design-CSS in `app.py`
  (Kacheln für Kennzahlen `kpis`, Pillen-Reiter, Handy: To-do-Zeilen und Wochen-Navigation `weeknav` kompakt).
- `config.json` – Module (Farbe, Material-Symbol, Stundenplan, Kapitel inkl. `nr`, Vorlesungen, Übungen, Fristen-Wochentage `deadlines`,
  Klausurformat `exam_format`: mc_multi / sc4 / open / mixed, VWL und I&F = open (freie Aufgaben) → Karten-Prompt und Quiz), Kalender.
  Mathe-Tutorium: Raum M 110 (Hauptgebäude, Geschw.-Scholl-Pl. 1); `storage.ROOM_MOVES` korrigiert alte Räume auch im
  gespeicherten Stundenplan. VWL-Übung und -Tutorium erscheinen nicht im Stundenplan (Heute, Wochenübersicht:
  `storage.HIDDEN_FROM_TIMETABLE`/`in_timetable`), Übungsblätter, To-dos und Modulseite bleiben.
- `utils/` – `storage.py` (JSON in `data/`, Cloud-Sync), `cloud_sync.py` (GitHub-Repo, PDFs werden erst bei Bedarf geladen),
  `units.py` (Vorlesungen/Übungen = Einheiten), `planner.py` (To-dos, Fristen), `learning.py` (Folienanalyse, Karten
  inkl. Abdeckung jeder Seite und Prüfdurchgang, Definitionen, Seiten mit Abbildungen genau lesen),
  `spaced_repetition.py` (FSRS mit Klausurtermin: Zielquote, Endspurt, neue Karten pro Tag), `ai.py` (Anthropic, Modell pro Aufgabe in `TASKS`),
  `textbook.py` (Lehrbuch, nur für Tutor), `exam_tasks.py` (Aufgaben aus Altklausuren auslesen, je Aufgabe die
  nötigen Vorlesungen), `script.py` (ganzes Skript im Reiter Dateien → je Vorlesung ihr Teil laut
  „Skript 1.1–1.4“ im Thema; fließt in die Vorbereitung ein, ohne Folien Vorbereitung nur aus dem Skript), `definitions.py`, `exam_plan.py` (Klausur-Lernplan ab 26.12.), `weakness.py`, `notify.py` (ntfy-Push).
- `views/` – `today_view.py` (ohne Klausur-Countdown und Schwachstellen) und `dashboard.py` (Wochenübersicht mit eigener
  Zeile „Karteikarten“, ohne Lernfahrplan; beide mit eigenen To-dos in todos.json → `_custom`),
  `cards_center.py` (Karteikarten: Lernstand, Empfehlung, freie Auswahl mit Filtern wie „schwach“, Liste aller Karten
  zum Bearbeiten/Löschen, Focus Mode ohne Seitenleiste mit Zurück und Feedback-Button → KI formuliert um; Enter im
  Antwortfeld löst auf; „Lernen“ auf Heute/Wochenplan/Modulseiten öffnet direkt den Focus Mode via `start_focus`),
  `quiz_center.py` (Quiz: Fragen zu gewählten Vorlesungen, Focus Mode Frage für Frage, Mehr Infos, Tutor-Rückfragen),
  Formelsammlung entfernt (keine Seite, Modul-Reiter heißt nur „Notizen“, kein Formel-Schritt; `formulas.py`/
  `formulas_tab.py` und die Daten bleiben ungenutzt erhalten), `settings_view.py` (mit Reitern
  Export und Backup aus `export_view.py`), Abhak-Knöpfe statt Kästchen (`common.done_button`: grün mit Haken / gestrichelt offen; Ablauf, Vorlesungs- und
  Übungsseite). Übungsseite nur Blatt, Musterlösung, „Rückmeldung aus dem Chat“ (Lief gut / Lief schlecht,
  `units.exercise_feedback`, data["exercise_feedback"][unit_id]; Popover mit Frage zum Kopieren für den Claude-Chat),
  Fragen (keine eigene Lösung, keine Karten). Die Rückmeldung fließt über `learning.feedback_block` in Karten,
  Ausdünnen und Quiz ein und über `exams.weak_points` in die Korrektur (Quiz-Freitext, Klausuraufgaben). Priorität einer Karte
  direkt an der Karte umstellbar (`study.priority_picker`: Focus Mode und Durchsehen). `module_view.py` (Reiter Ablauf / Lernen & Klausur /
  Definitionen / Dateien / Notizen), `module_tabs/` (Vorlesungs- und Übungsseiten, Lernen mit Reiter Klausuraufgaben (`exam_tasks_tab`: echte
  Altklausur-Aufgaben nur zu den gewählten, schon gehörten Vorlesungen, Auswerten/Korrigieren/Tipp/Tutor), Tutor …).

## Neues Lernsystem (`planner.LEARNING_V2 = True`, seit 07.11.2026; Plan: `UMSETZUNGSPLAN.md`)
Pro Vorlesung: Nacharbeiten → Vorlesungs-Check → Übungsblatt → Wochentraining. `False` stellt das alte
Karteikarten-/Quiz-System mit allen Lernständen wieder her (Code bleibt; Tests dafür mit Fixture `old_system`).
- **Daten bleiben:** `utils/migration.py` läuft einmal pro Modul (`learning_version = 2`): Backup aller JSONs nach
  `data/backups/vor-lernsystem-2_<Zeit>/` (Cloud-Sync lädt `backups/` nur bei Bedarf), Karten bleiben Byte für Byte in
  `cards` (nur Markierung `cards_archived` mit Prüfsumme), Gegenprobe, sonst nichts speichern. Vorher schon
  nachbereitete Vorlesungen → `legacy_lectures` (kein Check-To-do, nur Wochentraining). Alte Karten nur noch unter
  Einstellungen → Ausgeblendet (`views/archive_view.py`); Umrechnung Gar nicht/Etwas → schwer, Gut → mittel,
  Perfekt → einfach (`mastery.ARCHIVE_GRADE`). Karten nie löschen.
- **Nacharbeiten** (`views/module_tabs/nacharbeiten.py`): 1 Folien sichten (Raster, Klick aufs Bild = nicht relevant,
  `doc.excluded_slides`; `topics.suggest_exclusions` schlägt Wiederholungen aus früheren VL und Titel/Orga-Folien
  ohne KI vor) · 2 alle zählenden Folien genau lesen (Haiku, `topics.read_all`) · 3 Hinweise zur Quiz-Erstellung:
  Umfang ganze VL / Folie x–y (`notes.scope`; Rest wird der nächsten VL angeboten: `offered_carry`), Wichtig
  (`emphasized`), Streichen (`skip`), Sonstiger Hinweis (`card_hint`, Vorrang), eigene Notizen · 4 Minithemen
  (`topics.create_topics`, Sonnet; ordnet alte Karten zu → `archive_map`; Definitionen → Reiter Definitionen ohne
  Karte) = Nacharbeiten erledigt. Ausgelassen wird NUR, was sie ausgeschlossen hat; Beispiele nie abfragen, außer
  sie sagt es. Kein Tutor, kein Lehrbuch, keine Klausuraufgaben im neuen System.
- **Wissensstand je Minithema** (`utils/mastery.py`): FSRS je Minithema, Leiter Single → Multiple Choice → Freitext
  (Rechen-Minithemen enden bei MC/Zahl), falsch → Stufe runter, Tipp benutzt → zählt wie schwer, Übungs-Rückmeldung
  „schlecht“ → sofort fällig (`sessions.map_feedback`, Haiku). Archiv nur Hinweis (Reihenfolge, Einstieg MC bei
  „sicher“), gilt nicht als abgefragt.
- **Fragenspeicher** (`utils/question_bank.py`): Frage höchstens 3-mal, mind. 1 andere Session dazwischen; Klausurstil-
  Profil je Modul (einmal erzeugt) + Regeln im gecachten Systemprompt; nur Folien der benötigten Minithemen; alle
  neuen Fragen einer Session in einer Anfrage, inkl. 3 Tipps, Begründung je Option, Musterlösung. Kein Formel-Tippen:
  Rechnen nur als Rechenweg-Auswahl oder Kopfrechnen mit glattem Ergebnis (Zahlfeld, exakt); Taschenrechner/Notizblatt
  bestimmen den Aufwand. Freitext bewertet Haiku (`grade_text`).
- **Sessions** (`utils/sessions.py`, Ansicht `views/session_ui.py`, Fokus-Modus): Vorlesungs-Check genau 15 Fragen,
  ≤ 30 Min, alle Minithemen der VL so weit möglich; Wochentraining 5/10/15 Fragen, fortlaufend nummeriert, Auswahl:
  offen aus Checks → Übungs-Schwächen → fällig → nie gefragt aus alten VL → Rest. Selbstbewertung Schwer (rot) /
  Mittel (orange) / Einfach (grün), auch nach falscher Antwort. Seiten: `views/check_center.py` (PAGES["cards"]),
  `views/training_center.py` (PAGES["quiz"]).
- **To-dos** (`planner.generate_todos`, `units.open_tasks`): je VL in fester Reihenfolge Nacharbeiten (step 1),
  „Vorlesung X [Modul] Check“ (2, gleiche Frist, Schlüssel `…:check`), Übungsblatt (3), Wochentraining (4,
  `planner.training_windows`: nach dem Blatt, spätestens Tag vor der nächsten VL; erst ab Umstellung; ein Training
  hakt alle offenen Trainings-To-dos des Moduls ab). Aufholplan auf Heute (`utils/catchup.py`): dringende Blätter
  zuerst, dann Rangfolge ExRW/I&F > Statistik/Mathe > VWL, älteste VL zuerst; Zeitbudget Mo 2 h, Di 4 h, Mi 6 h,
  Do 2 h, Fr–So je 4 h (Einstellungen), Blatt 3 h.
- Modul: Ablauf mit Schritt-Pillen je VL (`views/progress.py`), Reiter „Wissensstand“ (statt Lernen & Klausur, mit
  Altklausuren). Keine Emojis in der Oberfläche (Material-Symbole statt ✓ ○ ↩ ↔).

## Regeln für KI-Inhalte
- Karteikarten nur aus Folien/Skript + Nachbereitung; Altklausuren und Übungsblätter des Moduls fließen immer als
  Maßstab ein (`learning.exam_style_material`), was relevant ist. Kurze Karten, Anzahl nach Ermessen (keine feste
  Zahl, so wenige wie möglich, bei dichtem Stoff auch bis ~30), Antwort ≤ ~25 Wörter, Erklärung höchstens ~80 Wörter,
  keine Doppelungen, keine Theorie-Details/Herleitungen – Rechnen und
  Anwenden übt das Quiz (Typ „Übungsaufgaben“, Stil der Übungen/Altklausuren). Nachbereitung entscheidet: „Hinweis zur
  Kartenerstellung“ hat höchste Priorität (im Karten-Prompt ganz oben und als Erinnerung am Ende, auch beim
  Nachholen, Ausdünnen und Umformulieren; Feld hervorgehoben), „Sehr wichtig“ → high, „Nicht so wichtig“ → low oder keine Karte, „Streichen“ →
  keine Karte, nicht Erwähntes ohne Klausurbezug → überspringen. Keine Karten,
  die Beispiele abfragen; jede Definitionskarte → auch Reiter Definitionen. Lehrbuch nur im Tutor. Jede Seite: Karte
  oder Grund fürs Überspringen. „Karten ausdünnen“ (`learning.propose_slim`/`apply_slim`) räumt bestehende Karten
  einer Einheit auf – erst Vorschlag, dann Übernehmen.
- Karten entstehen nur auf Klick (nach der Nachbereitung), nie automatisch.
- Modelle: Zusammenfassung Haiku 5.5, Karten Sonnet 5.5, Tutor Sonnet 5.5, Antwort-/Kartenprüfung Haiku 5.5
  (änderbar in den Einstellungen). Kein Opus (aus `ai.MODELS` entfernt, gespeicherte Opus-Wahl → Sonnet, models_version 3).
- Quiz: jede Frage hat `hint` (Tipp zum Aufklappen: Zeichen/Notation, Ansatz, ohne Lösung; fehlt er, holt „Tipp
  anzeigen“ ihn per Haiku) und `option_notes` (je Option richtig/falsch + warum, `quiz_center.option_breakdown`).
  Freitext: „Korrigieren lassen“ → `exams.grade_answer`/`show_grading` mit errors (was falsch · warum · richtig).
- Nachbereiten (Reiter der Vorlesung, Schritte in `lecture_page._review_tab`): 1 · Notizen mit „Sehr wichtig“,
  „Nicht so wichtig“, „Streichen“, „Hinweis zur Kartenerstellung“ (Felder in `units.NOTE_FIELDS`; Schlüssel
  emphasized/briefly/skip/card_hint – kein Feld für genannte Beispiele) · 2 · Seiten genau lesen
  (`_exact_read`, beliebige Seiten, Abbildungsseiten vorausgewählt, `read_pages_visual(update_prep=False)`) ·
  3 · Karteikarten erstellen (auf Klick, Abdeckung, prüfen, ausdünnen) · 4 · Karten durchsehen
  (`study.browse_cards`: einzeln durchblättern oder Liste; Feedback → `learning.rewrite_card`, kann auf 2–3 Karten
  aufteilen, Rückgängig entfernt die Teilkarten; bearbeiten, löschen) · „Nachbereitung abschließen“ → Reiter Lernen
  (nur noch Abfrage, Quiz, Tutor). Kein Abtippen der Papier-Mitschrift mehr; bei „Seiten genau lesen“ werden die
  Folien mit Abbildungen als Bild gezeigt (`lecture_page._page_previews`).
- Mathe: Einheit 3 (Selbststudium) ist eine eigene Einheit (`"self_study": true`, Datum 20.10.) mit eigener Seite.
- **Vorbereiten (abgeschaltet, `planner.PREP_ENABLED = False`)** – auf Wunsch der Nutzerin vorerst entfernt, Code
  komplett erhalten; `True` stellt alles wieder her: Reiter „Vorbereiten“ (`lecture_page._prep_tab`,
  `common.lecture_tabs()`), To-dos „Vorlesung vorbereiten“ (`planner.generate_todos`, `units.open_tasks`), Häkchen
  „Vorbereitet“ (Ablauf, Vorlesungskopf, Kapitelstatus im Wochenplan), Frist in den Einstellungen, Zusammenfassung
  automatisch nach dem Upload (`files.uploader`, `bulk_upload`). So funktionierte sie: Haiku, effort low; Must-Watch
  (2–3 Folien), Tabelle Folie | Begriff | Kurzerklärung | Worauf achten, Zusammenfassung entlang der Folien als
  Stichpunkte (3–6 verständliche Unterpunkte, ergänzend zur Folie, ohne Vorwissen verständlich), 5 Quizfragen im
  Klausurformat – kein Fließtext, alles mit Foliennummer. Entstand erst, nachdem bei Seiten mit Abbildungen gewählt war,
  welche genau gelesen werden (`learning.pending_figures`), ohne Abbildungen direkt nach dem Upload; Skript-Teil der
  Vorlesung floss ein. Legte Formel-Vorschläge in `formula_inbox` ab (Reiter Formeln & Notizen). Tests dafür setzen
  `PREP_ENABLED` per monkeypatch auf True.
- Vermerke in den Notizen („nicht relevant“, „kommt dran“) und die Kategorien gelten für Karten, Ausdünnen und Quiz.
- Quiz: Themenschwerpunkte nach Häufigkeit/Punkten in den Altklausuren (plus letzte Klausur-Analyse), aber nur Stoff
  aus dem Kontext (bereits gehörte/gewählte Vorlesungen).
- Keine erklärenden Hinweistexte in der Oberfläche ergänzen (Nutzerin hat sie bewusst entfernen lassen).
- PDFs zuerst nur als Text lesen; Seiten mit Abbildungen vorschlagen, genau lesen nur nach Auswahl.

## Testen
- `ruff check --select F,E9 --line-length 120 .`
- `python -m pytest tests -q` (Schnelltest: alle Seiten und Module öffnen; räumt `data/` selbst auf)
- Abhängigkeiten installiert der SessionStart-Hook (`.claude/hooks/session-start.sh`) in Cloud-Sitzungen automatisch.
