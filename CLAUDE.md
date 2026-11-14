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
Pro Vorlesung 6 Schritte (seit 10.11.2026): 1 Upload → 2 Nacharbeit → 3 Check 1 → 4 Übungsblatt → 5 Check 2 →
6 Wochentraining. Kein Aufholplan mehr (`catchup.py` gelöscht, Nutzerin plant selbst). `False` stellt das alte
Karteikarten-/Quiz-System mit allen Lernständen wieder her (Code bleibt; Tests dafür mit Fixture `old_system`).
- **Daten bleiben:** `utils/migration.py` läuft einmal pro Modul (`learning_version = 2`): Backup aller JSONs nach
  `data/backups/vor-lernsystem-2_<Zeit>/` (Cloud-Sync lädt `backups/` nur bei Bedarf), Karten bleiben Byte für Byte in
  `cards` (nur Markierung `cards_archived` mit Prüfsumme), Gegenprobe, sonst nichts speichern. Vorher schon
  nachbereitete Vorlesungen → `legacy_lectures` (kein Check-To-do, nur Wochentraining). Alte Karten nur noch unter
  Einstellungen → Ausgeblendet (`views/archive_view.py`); Umrechnung Gar nicht/Etwas → schwer, Gut → mittel,
  Perfekt → einfach (`mastery.ARCHIVE_GRADE`). Karten nie löschen.
- **Upload** (Reiter „Upload“, Schlüssel weiterhin `nachbereitet`; `views/module_tabs/nacharbeiten.py`): KEIN
  Folienraster – 1 Umfang & Hinweise: je Foliendatei „Von/Bis Folie“ und „Genau lesen“ Alle / Nur mit Abbildungen /
  Keine plus „Nicht genau lesen (Folien)“ als Bereichsliste (`notes.scopes[doc] = {from, to, read, text_only}`,
  `topics.exact_candidates`, `parse_pages`), Wichtig (`emphasized`), Streichen (`skip`), Sonstiger Hinweis
  (`card_hint`, Vorrang), eigene Notizen; automatisch ausgelassene Folien (Titel/Orga, schon in früheren VL –
  `topics.suggest_exclusions`, `doc.excluded_slides`) nur als Liste mit „Doch lesen“ · 2 „Nacharbeiten abschließen“
  liest die ausgewählten Folien gründlich (Haiku, `topics.read_all`, Pakete à 12, bei abgeschnittener Antwort
  `ai.TruncatedError` → Paket halbieren; jedes Paket sofort gespeichert, „Weiter lesen“) und erstellt die Minithemen
  (`topics.create_topics`, Sonnet; lange Unterlagen in Abschnitten à 60 Seiten, zu lang → halbieren; ordnet alte
  Karten zu → `archive_map`; Definitionen → Reiter Definitionen ohne Karte) = Upload erledigt. Ausgelassen wird NUR, was sie ausgeschlossen hat; Beispiele nie abfragen, außer
  sie sagt es. Kein Tutor, kein Lehrbuch, keine Klausuraufgaben im neuen System.
- **Nacharbeit** (Reiter „Nacharbeit“, `utils/nacharbeit.py`, Schlüssel `nacharbeit`): Vorlesung im externen
  Claude-Chat mit dem Tutor-Prompt (`nacharbeit.TUTOR_PROMPT`, Popover zum Kopieren) nacharbeiten, Zusammenfassung
  (SICHER / WACKELIG / NICHT VERSTANDEN / NICHT GESCHAFFT / ALS NÄCHSTES ÜBEN) einfügen → data["nacharbeit"][VL],
  Haiku ordnet sie den Minithemen zu (`map_summary` → `mastery.apply_nacharbeit`: sicher → Einstieg MC, sonst SC und
  offen bis zur sicheren richtigen Antwort; `mastery.weak_notes` fließt in neue Fragen und die Korrektur ein).
- **Check 1 / Check 2** (Reiter „Checks“, Seite „Checks“): `sessions.halves` teilt die Minithemen an einer
  Themengrenze nahe der Mitte (nach Check 1 bleibt dessen Hälfte fest, `part_ids`); jedes Minithema der Hälfte
  kommt dran (auch > 15 Fragen), Schwaches aus Nacharbeit/Übung bekommt eine zweite Frage, bei wenig Stoff bis 15
  aufgefüllt (max. 3 je Minithema). Session hat `part`; alte Checks ohne `part` = ganze Vorlesung
  (`sessions.single_check` → keine Nacharbeit-/Check-2-To-dos). Check 2 fällig am Tag nach dem Übungsblatt
  (`planner.check2_due` = `step_due(…, "check2")`).
- **Wissensstand je Minithema** (`utils/mastery.py`): FSRS je Minithema, Leiter Single → Multiple Choice → Freitext
  (Rechen-Minithemen enden bei MC/Zahl), falsch → Stufe runter, Tipp benutzt → zählt wie schwer, Übungs-Rückmeldung
  „schlecht“ → sofort fällig (`sessions.map_feedback`, Haiku). Archiv nur Hinweis (Reihenfolge, Einstieg MC bei
  „sicher“), gilt nicht als abgefragt.
- **Fragenspeicher** (`utils/question_bank.py`): Frage höchstens 3-mal, mind. 1 andere Session dazwischen; Klausurstil-
  Profil je Modul (einmal erzeugt) + Regeln im gecachten Systemprompt; nur Folien der benötigten Minithemen; alle
  neuen Fragen einer Session in einer Anfrage, inkl. 3 Tipps, Begründung je Option, Musterlösung. Kein Formel-Tippen:
  Rechnen nur als Rechenweg-Auswahl oder Kopfrechnen mit glattem Ergebnis (Zahlfeld, exakt); Taschenrechner/Notizblatt
  bestimmen den Aufwand. Freitext bewertet Haiku (`grade_text`).
- **Sessions** (`utils/sessions.py`, Ansicht `views/session_ui.py`, Fokus-Modus): Checks siehe oben (~30 Min je 15
  Fragen); Wochentraining 5/10/15 Fragen, fortlaufend nummeriert, Auswahl (`sessions.training_focus`): Probleme aus
  Checks (letzte Antwort falsch/teilweise/schwer, `mastery.is_problem`) → Übungs-Schwächen → offene Nacharbeit →
  offen aus Checks; etwa ein Viertel reserviert für Wiederholung (fällig → nie gefragt aus alten VL → schwächste). Selbstbewertung Schwer (rot) /
  Mittel (orange) / Einfach (grün), auch nach falscher Antwort. Seiten: `views/check_center.py` (PAGES["cards"]),
  `views/training_center.py` (PAGES["quiz"]).
- **To-dos** (`planner.generate_todos` → `planner.lecture_steps_todos`, `units.open_tasks`): je VL in fester
  Reihenfolge Upload (step 1, Schlüssel `…:nachbereitet`), Nacharbeit (2, `…:nacharbeit`), „Vorlesung X [Modul]
  Check 1“ (3, `…:check`), Übungsblatt (4), Check 2 (5, `…:check2`), Wochentraining (6, je Vorlesung, Schlüssel am
  Blatt `…:ex:…:training`, ohne Blatt `…:vl:…:training`; erst ab Umstellung; ein Training hakt alle offenen
  Trainings-To-dos des Moduls ab, die schon begonnen haben).
- **Fristen** (seit 14.11.2026, `planner.step_due`, `STEP_DAYS`): Upload am festen Upload-Tag
  (`deadlines.upload_weekday`: Mathe/ExRW Mo, VWL/I&F Di, Statistik Do), dann +2 Nacharbeit, +4 Check 1,
  +6 Übungsblatt, +8 Check 2, +10 Wochentraining (Mathe: Mi, Fr, So, Di, Do der Folgewoche). Blatt ↔ Vorlesung:
  `planner.sheet_lectures` (mit Kapitel: erste freie VL desselben Kapitels vor der Besprechung; ohne Kapitel: letzte
  freie VL vor der Besprechungswoche, z. B. I&F Blatt 1 → VL 27.10.); Blätter ohne Vorlesung behalten die alte Frist
  (`_old_exercise_due`, alte Wochentage `review_weekday`/`exercise_weekday` nur noch fürs alte System).
- **Frühere Vorlesungen** (`legacy_lectures`, vor der Umstellung nachbereitet): Nacharbeit und Check 1/2 freiwillig
  möglich (Schritt-Pille „optional“, gepunktet, anklickbar; Seite Checks → Abschnitt „Frühere Vorlesungen“), ohne
  To-do und ohne Frist.
- **Übungs-Rückmeldung** (`sessions.map_feedback`): Haiku bekommt alle Minithemen bis zur Vorlesung des Blatts (die
  des Blatts mit *), damit Schwächen auch früheren Minithemen zugeordnet werden; Neuzuordnung ersetzt alte Zuordnungen
  des Blatts (`FEEDBACK_MAP_VERSION` 2 → einmal alles neu zuordnen).
- Modul: Ablauf mit anklickbaren Schritt-Pillen je VL (`progress.step_buttons`, 6 Schritte: Upload/Nacharbeit/Check 1/2
  öffnen den Reiter der Vorlesung, ein angefangener Check läuft direkt weiter, Übungsblatt öffnet das Blatt, Wochentraining die Seite), auch
  im Kopf der Vorlesungsseite; Reiter „Wissensstand“ (statt Lernen & Klausur, mit Altklausuren). Keine Emojis in der
  Oberfläche (Material-Symbole statt ✓ ○ ↩ ↔ ◀ ▶). Keine Kostenangaben („ca. x Cent“) in der Oberfläche.
- Aufgabenarten überall mit Etikett (`common.kind_badge`/`KIND_STYLE`: Upload blau, Nacharbeit gelb, Check 1/2
  violett, Übungsblatt orange, Wochentraining grün; Gruppen in `common.GROUPS` in Schrittreihenfolge), To-dos haben `short`/`chip`. Offene Aufgaben früherer Wochen wandern mit
  (`planner.overdue_before`, `carried` → bei heute; auch eigene To-dos). Kein „Fortschritt pro Modul“ in der
  Wochenübersicht. Check/Training/Frage-Ansicht in Modulfarbe (CSS-Schlüssel `ckrow_`, `ckhead_`, `trhead_`, `qcard_`,
  `sesshead_` in `app.py`).
- Eine Foliendatei für mehrere Termine (z. B. ExRW 2.11.–7.12.): Umfang je Datei und Vorlesung (`notes.scopes`,
  `topics.doc_range`, im Formular „Von/Bis Folie“); endet der Umfang vor dem Dateiende, bietet die nächste VL
  „Weiter ab Folie x“ an → `doc.shared_units` + Bereich ab x (`topics.accept_carry`, `is_shared`); Raster zeigt bei
  übernommenen Dateien erst ab dieser Folie; Wiederholungs-Erkennung vergleicht eine Datei nie mit sich selbst.
- Mathe: Blatt n gehört zu Einheit/Vorlesung n (Blatt 3 → Einheit 3 Selbststudium); `exercise_chapters_version` in
  config.json verwirft einmalig von Hand gesetzte Blatt-Kapitel. Blatt-Frist = Sonntag der Vorlesungswoche (siehe
  Fristen; `exercise_shift_days: -7` gilt nur noch für Blätter ohne Vorlesung und im alten System).
- Quiz-Antworten: jede Option als eigener Block (`quiz_center.option_breakdown`, CSS `opt_hit/wrong/missed/neutral`),
  Erklärung in Absätzen (`quiz_center.paragraphs`; Prompt verlangt 2–4 Absätze). Feedback je Frage
  (`session_ui._feedback` → `sessions.question_feedback`): „Fehler“ lässt Claude die Frage gegen die Folien prüfen,
  korrigiert sie und wertet die Antwort neu (Freitext: nicht gewertet, `item.void`); gemeldete Fragen werden nicht
  wiederverwendet, Hinweise fließen in neue Fragen zum Minithema ein (`sessions.feedback_notes`).
- Heute/Wochenplan: To-dos mit Priorität stehen oben unter „Als Nächstes“ (1 zuerst, mit Aufgaben-Symbol), der Rest
  darunter je Tag nach Kategorie (`common.grouped`: Nacharbeiten, Check, Übungsblatt, Wochentraining, Sonstiges;
  `common.prio_button`, todos.json → `_prio`, tippen schaltet 1 → 2 → 3 → keine). Stundenplan kompakt (Container
  `ttgrid`, eine Zeile „Modul Art / Zeit“, leere Zeitblöcke der Woche ausgeblendet, Raum nur beim Drüberfahren).
- Falsch hochgeladene Vorlesung verschieben: Upload-Reiter → „In andere Vorlesung verschieben“ (`utils/move.py`:
  Dateien, Hinweise, Minithemen, Wissensstand, Fragen, Definitionen, Checks, Nacharbeit, Erledigt-Stand; Verweise alter Karten
  im Quellmodul werden gelöst).
- Check/Training: „Zurück“ zeigt frühere Fragen nur zum Lesen (`session_ui._view`), „Weiter“ führt zur aktuellen.

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
