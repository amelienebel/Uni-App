# Umsetzungsplan: Neues Lernsystem (Vorlesungs-Check + Wochentraining)

Stand: 07.11.2026 · Status: **Antworten eingearbeitet, wartet auf das endgültige Go** – es ist noch nichts umgesetzt.

---

## 0. Was ich im bestehenden Code vorgefunden habe

| Bereich | Heute | Datei(en) |
|---|---|---|
| Speicher | Pro Modul eine JSON-Datei `data/modules/<modul>.json`, gespiegelt in dein privates GitHub-Daten-Repo (jede Änderung = eigener Commit, also eine Versionsgeschichte) | `utils/storage.py`, `utils/cloud_sync.py` |
| Karteikarten | Liste `cards` im Modul: Frage, Antwort, Erklärung, Quellen (Datei + Seiten), Vorlesung (`unit`), Priorität, FSRS-Werte (`stability`, `difficulty`, `due`, `reps`, `lapses`), **Verlauf `history`** mit jeder Bewertung (0 Gar nicht · 1 Etwas · 2 Gut · 3 Perfekt) | `utils/spaced_repetition.py`, `views/cards_center.py`, `views/module_tabs/study.py` |
| Quiz | Liste `quizzes` (nur die letzten 30 werden gehalten) | `views/quiz_center.py`, `views/module_tabs/exams.py` |
| Nacharbeiten | Notizen (Sehr wichtig / Nicht so wichtig / **Streichen** / Hinweis), Seiten genau lesen (mit Folienbildern), Karten erstellen, Karten durchsehen | `views/module_tabs/lecture_page.py`, `utils/learning.py` |
| Übungs-Rückmeldung | „Lief gut / Lief schlecht“ je Übung (`exercise_feedback`) | `views/module_tabs/exercise_page.py` |
| To-dos | Nachbereiten, Übungsblatt, „Lernkarten wiederholen“ (pro Woche) | `utils/planner.py`, `utils/units.py` |
| Schwachstellen | aus Karten-Bewertungen pro Kapitel | `utils/weakness.py` |
| Backup | ZIP-Download/-Wiederherstellung in den Einstellungen | `utils/export.py`, `views/export_view.py` |

Karten werden außerdem gelesen von: Heute, Wochenübersicht, Ablauf, Push-Benachrichtigungen, Export, Definitionen.

---

## 1. Datensicherheit: Backup, Archiv, Migration (wichtigste Regel)

### 1.1 Backup vor jeder Migration
1. **Automatisch:** Bevor ein Modul migriert wird, kopiert die App alle Lerndaten (alle Modul-JSONs, `settings.json`,
   `todos.json`, Zusatzdateien) unverändert nach `data/backups/vor-lernsystem-2_<Datum-Uhrzeit>/`.
   Dieser Ordner wird wie alles andere in dein GitHub-Daten-Repo hochgeladen. Er liegt also auch online.
   PDFs werden nicht mitkopiert: Sie werden von der Migration nicht angefasst und liegen schon im Daten-Repo.
2. **Zusätzlich:** In den Einstellungen gibt es einen Knopf „Komplett-Backup herunterladen (ZIP)“, wie heute.
   Ich empfehle, ihn vor dem ersten Start einmal zu drücken.
3. **Dritte Sicherheitsebene:** Das GitHub-Daten-Repo speichert jede frühere Version der Dateien.
4. Ein Backup wird nur angelegt, wenn die Migration wirklich etwas ändert. Erscheinen die Daten danach
   unverändert, gibt es kein zweites Backup.

### 1.2 Archivierung: Karten bleiben, wo sie sind
- Die Karten bleiben **genau an ihrer Stelle** in `cards`. Nichts wird kopiert, verschoben oder gelöscht.
  Frage, Antwort, FSRS-Werte und der komplette Verlauf bleiben **Byte für Byte gleich**.
- Neu kommt nur ein Modul-Eintrag dazu: `cards_archived = {"at": <Zeitpunkt>, "count": <Anzahl>, "backup": <Ordner>}`.
- Die App liest daran ab: Karten werden nicht mehr gelernt, sondern nur noch im neuen Bereich
  **Einstellungen → „Ausgeblendet“** angezeigt (nur lesen, mit Suche, Filter nach Modul/Vorlesung und Anzeige
  des Lernstands).
- Die alten Quizze (`quizzes`) bleiben ebenfalls unverändert gespeichert.

### 1.3 So läuft die Migration ab (pro Modul, beim ersten Öffnen nach dem Update)
1. Prüfen: Steht `learning_version` schon auf 2? Dann nichts tun. Die Migration läuft also nur einmal.
2. Backup anlegen (1.1).
3. Prüfwerte merken: Zahl der Karten, Zahl aller Verlaufseinträge, Prüfsumme der Karten-Daten.
4. Nur **neue** Felder ergänzen: `cards_archived`, leere Speicher für `topics`, `mastery`, `questions`,
   `sessions`, `learning_version = 2`.
5. Gegenprobe: Zahl der Karten, Verlaufseinträge und Prüfsumme müssen gleich sein. Wenn nicht, wird **nicht
   gespeichert**, das Modul bleibt im alten Zustand, und eine Fehlermeldung nennt den Backup-Ordner.
6. Erst danach wird gespeichert.

Die **Zuordnung** der Karten zu Minithemen ist ein späterer, eigener Schritt (siehe 8). Sie schreibt nur in die
neuen Felder und ändert keine Karte.

### 1.4 Rückweg
Es gibt einen Schalter `LEARNING_V2` (wie heute `PREP_ENABLED`). Auf „aus“ zeigt die App wieder das alte
Karteikartensystem mit allen Lernständen. Der alte Code bleibt dafür erhalten und wird nur ausgeblendet.

---

## 2. Neues Datenmodell (pro Modul-JSON, alles zusätzlich)

```text
topics:      { "<vorlesungs-id>": {
                 "created_at", "model", "status": "fertig",
                 "topics": [ { "id", "title", "slides": [{doc_id, pages}],
                               "minitopics": [ { "id", "title", "slides": [{doc_id, pages}],
                                                 "kind": "wissen" | "anwendung" | "rechenweg" | "kopfrechnen",
                                                 "importance": "hoch" | "normal" | "niedrig",
                                                 "excluded": false, "excluded_by": "Streichen-Notiz" | "Folie ausgeblendet" | "von Hand" } ] } ] } }

mastery:     { "<minithema-id>": {
                 "level": "sc" | "mc" | "freitext",          # aktuelle Schwierigkeitsstufe
                 "stability", "difficulty", "due", "last_seen",  # Spaced Repetition (FSRS) je Minithema
                 "asked": 0, "first_asked": <Datum oder leer>,   # Abdeckung
                 "history": [ {date, source: "check" | "training" | "uebung", question_id,
                               correct: true/false/teilweise, self: "schwer" | "mittel" | "einfach"} ],
                 "archive_hint": {"cards": n, "score": 0..1, "label": "schwach" | "mittel" | "sicher"},
                 "exercise_flags": [ {exercise_id, "gut" | "schlecht", text} ] } }

questions:   [ { "id", "minitopic_id", "lecture_id", "level", "type": "sc" | "mc" | "freitext" | "zahl",
                 "question", "options", "correct", "option_notes",
                 "hints": [Stufe 1, Stufe 2, Stufe 3], "explanation",
                 "sample_answer", "key_points",                 # bei Freitext: Musterlösung + Bewertungspunkte
                 "number_answer",                               # bei Kopfrechnen: genaues Ergebnis
                 "calc": "keins" | "rechenweg" | "kopf" | "notizblatt" | "taschenrechner",
                 "slides": [{doc_id, pages}], "created_at",
                 "used_in": [Session-Nummern], "retired": false } ]

sessions:    [ { "id", "kind": "check" | "training", "lecture_id" (beim Check), "number" (Wochentraining Nr.),
                 "label": "Vorlesung 3 Mathe Check" | "Wochentraining 2 Mathe",
                 "settings": {n, taschenrechner, notizblatt}, "started_at", "finished_at",
                 "items": [ {question_id, answer, correct, grading, self, hints_used} ] } ]
```

- **Abdeckung** = Minithemen einer Vorlesung, die nicht ausgeschlossen sind und schon mindestens einmal
  abgefragt wurden (`first_asked`). Daraus entsteht die Abdeckungsliste (abgefragt / offen) und die
  Fortschrittsanzeige je Vorlesung.
- **Wissensstand** je Minithema = Stufe + FSRS-Erinnerungswahrscheinlichkeit, angezeigt als
  „neu / unsicher / wird sicher / sicher“.

---

## 3. Nacharbeiten (Reiter der Vorlesung)

Die Schritte nach dem Hochladen der Folien:

1. **Folien sichten (automatisch, kostenlos):** Die App vergleicht jede Folie mit den Folien aller früheren
   Vorlesungen des Moduls (Textvergleich auf dem Gerät, keine KI-Kosten) und erkennt:
   - **schon dagewesen:** Die Folie war fast wortgleich schon in Vorlesung X, z. B. eine Wiederholung zu Beginn.
   - **Titel / Gliederung / Organisatorisches:** sehr wenig Text oder typische Wörter wie „Agenda“, „Gliederung“,
     „Klausur“, „Termine“, „Literatur“, „Kontakt“.

   Diese Folien werden **vorab als „nicht relevant“ markiert** (grau, mit Grund-Etikett wie „schon in VL 2“ oder
   „Organisatorisches“). Du kannst jede Markierung mit einem Klick zurücknehmen. Erst wenn du den Schritt
   bestätigst, gilt sie als dein Ausschluss.
2. **Folienraster:** Alle Folien erscheinen als Bilder (Handy: eine Spalte, Tablet/Mac: drei Spalten).
   **Ein Klick auf das Bild** (bzw. den Knopf direkt darunter) schaltet um: „wichtig“ ↔ „nicht relevant“.
   Nicht relevante Folien werden grau. Gespeichert wird das am Dokument (`excluded_slides` mit Grund
   „von dir“, „schon in VL x“, „Organisatorisches“).
3. **Alles genau lesen:** Danach werden **alle nicht ausgeschlossenen Folien genau gelesen**, inklusive
   Grafiken, Tabellen und Formeln. Die Auswahl „welche Seiten genau lesen“ fällt weg. Kosten mit Haiku:
   ca. 0,04 Cent pro Folie, also **ca. 1–2 Cent pro Vorlesung** bei 30–50 Folien.
4. **Hinweise zur Quiz-Erstellung** (ersetzt die bisherigen Notizfelder „Sehr wichtig / Nicht so wichtig /
   Streichen / Hinweis zur Kartenerstellung“):
   - **Umfang:** Auswahl „Ganze Vorlesung“ oder „Folie [von] bis [bis]“ (zwei Zahlenfelder), z. B. wenn ihr nur
     bis Folie 34 gekommen seid. Folien außerhalb des Umfangs werden wie „nicht relevant“ behandelt. Kommen sie
     in der nächsten Vorlesung dran, gehören sie dort dazu (siehe offene Frage A).
   - **Wichtig:** wird gründlich und öfter abgefragt.
   - **Streichen:** wird nie abgefragt (z. B. „Herleitung von … nicht relevant“).
   - **Sonstiger Hinweis:** wird bei jeder Fragen-Erstellung zu dieser Vorlesung ganz oben mitgegeben und am
     Ende noch einmal erinnert (wie heute der Kartenhinweis).
   - Das freie Notizfeld für deine eigenen Mitschriften bleibt. Bisherige Einträge in „Nicht so wichtig“ und
     „Hinweis zur Kartenerstellung“ bleiben gespeichert und werden weiter berücksichtigt (als „seltener“ bzw.
     als sonstiger Hinweis), das Feld „Nicht so wichtig“ erscheint aber nicht mehr.
   - **Feste Regel:** Beispiele aus der Vorlesung werden **nie** als auswendig zu lernender Stoff abgefragt.
     Sie dürfen höchstens als Vorlage für eigene Anwendungsaufgaben dienen. Ausnahme: Du schreibst unter
     „Wichtig“ oder „Sonstiger Hinweis“, dass ein Beispiel gelernt werden soll.
5. **Themen & Minithemen:** „Nacharbeiten abschließen“ lässt Claude (Sonnet) die Vorlesung in Themen und
   Minithemen zerlegen. Grundlage sind die nicht ausgeschlossenen, genau gelesenen Folien im Umfang, der
   Skript-Teil und deine Hinweise. Danach siehst du den Themenbaum und kannst einzelne Minithemen ausschließen.
   - Ausgelassen wird nur: ausgeschlossene Folien, Folien außerhalb des Umfangs, „Streichen“ und von dir
     ausgeschlossene Minithemen. Alles andere wird ein Minithema.
   - Danach ist „Nacharbeiten“ abgehakt, und der Vorlesungs-Check ist frei.

## 4. Wissensstand und Schwierigkeit je Minithema

**Spaced Repetition** (FSRS wie bisher, aber je Minithema statt je Karte). Antwort und Selbstbewertung werden
zu einer FSRS-Bewertung kombiniert:

| Antwort | Selbstbewertung | FSRS-Bewertung |
|---|---|---|
| falsch | egal | „Nochmal“ (kommt bald wieder) |
| teilweise richtig (Freitext) | egal | „Schwer“ |
| richtig | schwer (rot) | „Schwer“ |
| richtig | mittel (orange) | „Gut“ |
| richtig | einfach (grün) | „Leicht“ |

**Schwierigkeitsleiter je Minithema** (in **allen** Modulen, auch Mathe und ExRW):
Single Choice → Multiple Choice → Freitext.
- Hochstufen: richtig mit „mittel“ oder „einfach“ → eine Stufe höher. Richtig mit „einfach“ bei schon stabilem
  Minithema darf eine Stufe überspringen. Damit kann ein sicheres Thema direkt auf Freitext abgefragt werden.
- Zurückstufen: falsch → eine Stufe runter (nie unter Single Choice). Zweimal hintereinander „schwer“ → bleibt
  auf der Stufe.
- **Ausnahme Rechnen:** Minithemen der Art „rechenweg“ oder „kopfrechnen“ haben kein Freitext-Niveau (du sollst
  keine Formeln tippen). Ihre oberste Stufe ist eine schwierige Multiple-Choice-Frage zum Rechenweg bzw.
  Kopfrechnen (siehe 7).
- Übungs-Rückmeldung „lief schlecht“ zu einem Minithema → Stufe höchstens Multiple Choice, sofort fällig.
  „Lief gut“ → leicht stabiler, gilt aber **nicht** als abgefragt.

---

## 5. Vorlesungs-Check (ersetzt „Karteikarten“)

- Name: „Vorlesung 3 Mathe Check“. Er ist auf der Vorlesungsseite (Schritt nach dem Nacharbeiten) und auf der
  neuen Seite **Vorlesungs-Check** in der Seitenleiste zu finden. Diese Seite zeigt alle Vorlesungen aller
  Module mit Status offen / erledigt / Ergebnis.
- **Genau 15 Fragen**, geplant auf höchstens etwa 30 Minuten: Jede Frage bekommt eine geschätzte Dauer
  (Single Choice ca. 1 Minute, Multiple Choice ca. 1,5, Kopfrechnen/Anwendung ca. 2–3, Freitext ca. 3–4), und
  die Auswahl bleibt unter 30 Minuten. Die Zeit wird oben angezeigt, ist aber kein Zwang.
- Vor dem Start fragt die App wie beim Wochentraining: **Taschenrechner ja / nein**, **Notizblatt ja / nein**
  (die Anzahl ist fest 15).
- Auswahl der Minithemen: zuerst „Wichtig“, dann so viele verschiedene Minithemen wie möglich (jedes
  höchstens einmal), Mischung aus Wissensfragen und kleinen Anwendungsaufgaben. Stil nach Klausurformat und
  Altklausuren des Moduls.
- Schon im ersten Check dürfen einige Freitext-Fragen dabei sein (Erklärfragen in Worten), auch in Mathe und
  ExRW. Der Großteil startet aber bei Single bzw. Multiple Choice.
- Hat die Vorlesung mehr als 15 Minithemen, bleiben die übrigen in der Abdeckungsliste als **offen**. Sie haben
  im nächsten Wochentraining Vorrang (siehe 6).
- Ein Check kann wiederholt werden. Gezählt wird für die To-dos der erste abgeschlossene Durchgang.

## 6. Wochentraining (ersetzt „Quiz“)

- Name fortlaufend je Modul: „Wochentraining 1 Mathe“, „Wochentraining 2 Mathe“ …
- Vor dem Start: **Fragen 5 / 10 / 15**, **Taschenrechner ja / nein**, **Notizblatt ja / nein**.
- Stoff: alle schon gehaltenen Vorlesungen des Moduls, auch die aus der Zeit vor dem neuen System.
- **Fragenauswahl** (in dieser Reihenfolge, bis die Anzahl erreicht ist):
  1. **Offene Minithemen aus Vorlesungs-Checks** (Pflicht: spätestens jetzt). Sind es mehr als gewählte Fragen,
     kommen die ältesten zuerst, und die App merkt sich den Rest für das nächste Training. Auf der Startseite
     steht dann z. B. „Noch 7 offene Minithemen, wähle 15 Fragen, damit alles drankommt.“
  2. Minithemen mit **„lief schlecht“** aus den Übungen.
  3. **Fällige** Minithemen laut Spaced Repetition, schwache zuerst. Grundlage sind Check-Ergebnisse und
     Trainings.
  4. **Noch nie abgefragte** Minithemen aus Vorlesungen vor dem neuen System. Die alten Karten bestimmen dabei
     nur die Reihenfolge (schwache zuerst), nicht den Wissensstand.
  5. Auffüllen nach Klausurgewicht (Themenhäufigkeit in Altklausuren), höchstens 2 Fragen aus derselben
     Vorlesung hintereinander.
- Am Ende: Ergebnis, Abdeckung, welche Minithemen sicherer geworden sind und was beim nächsten Mal drankommt.

## 7. Regeln für Rechenaufgaben (gelten für Check und Training)

Es gibt nur diese Aufgabenarten:
- ohne Rechnen (Wissen, Verständnis, Zuordnen),
- **Rechenweg** als Single oder Multiple Choice („Welcher Ansatz bzw. Schritt ist richtig?“),
- **Kopfrechnen** mit eindeutigem, glattem Ergebnis: Eingabe in ein Zahlenfeld, nur exakter Vergleich, keine
  Toleranz, keine Formeleingabe.

Aufwand je nach Auswahl:

| Taschenrechner | Notizblatt | Erlaubt |
|---|---|---|
| nein | nein | ohne Rechnen, Rechenweg, Kopfrechnen in **einem** Schritt mit kleinen Zahlen |
| nein | ja | Kopfrechnen in **2–3 Schritten** mit glatten Zwischenergebnissen |
| ja | egal | auch krummere Zahlen, dann aber als Single/Multiple Choice mit Zahlen-Optionen statt Eingabefeld |

Freitext gibt es nur für Erklärfragen in Worten.

## 8. Archiv der alten Karteikarten („Ausgeblendet“)

- **Zuordnung:** Sobald eine Vorlesung Minithemen hat, ordnet Claude Haiku jede alte Karte dieser Vorlesung
  einem Minithema zu (Liste von Karten-Frage + Minithemen-Titeln, sehr günstig). Ersatzweise passiert die
  Zuordnung über die gemeinsamen Folienseiten. Gespeichert wird nur `archive_map = {karten-id: minithema-id}`.
  Die Karte selbst bleibt unverändert.
- **Umrechnung 4 → 3 Stufen:**

| Alt | Neu | Begründung |
|---|---|---|
| 0 Gar nicht | schwer (und falsch) | nicht gewusst |
| 1 Etwas | schwer | nur teilweise gewusst |
| 2 Gut | mittel | gewusst, mit Nachdenken |
| 3 Perfekt | einfach | sofort gewusst |

- **Startwert je Minithema:** Mittelwert der letzten drei umgerechneten Bewertungen aller zugeordneten Karten,
  dazu FSRS-Stabilität und Fehlversuche. Ergebnis: „Hinweis: schwach / mittel / sicher“.
  Das ist ausdrücklich **nur ein Hinweis**: Das Minithema gilt weiter als „noch nicht gelernt“ und „noch nicht
  abgefragt“. Der Hinweis beeinflusst nur die Reihenfolge (schwach zuerst) und die Einstiegsstufe (siehe offene
  Frage 6).
- Der Bereich „Ausgeblendet“ zeigt alle Karten mit Lernstand (umgerechnete Stufe, letzte Bewertung) und dem
  zugeordneten Minithema.

## 9. Gemeinsame Bausteine beider Sessions (eine Komponente für beide)

- Fokus-Ansicht wie heute (ohne Seitenleiste), Fortschrittsbalken „Frage 4 von 15 · ca. 12 Min übrig“.
- **Tipp-Knopf** mit drei Stufen. Jeder Klick zeigt die nächste Stufe; gespeichert wird, wie viele Stufen du
  gebraucht hast. Eine benutzte Stufe drückt die Bewertung leicht (zählt wie „schwer“).
- Nach dem Antworten: **warum richtig oder falsch**, bei Auswahlfragen für jede Option einzeln (wie im aktuellen
  Quiz).
- **„Passende Folien anzeigen“**: zeigt die Folienbilder des Minithemas, wie früher bei den Karten.
- **Freitext:** Claude (Haiku) bewertet anhand der gespeicherten Musterlösung und Bewertungspunkte, mit Fehlern
  „was falsch · warum · richtig“.
- **Selbstbewertung:** drei große farbige Knöpfe ohne Emojis: „Schwer“ rot, „Mittel“ orange, „Einfach“ grün.
  Am Handy stehen sie unten nebeneinander. Sie erscheinen **auch nach einer falschen Antwort**.
- **Kein Tutor** mehr (auch nicht als Rückfrage zur Frage). Das machst du in deinem eigenen Claude-Chat.
- Eine Session kann unterbrochen und später fortgesetzt werden (Zwischenstand wird gespeichert).

## 10. Kosten sparen (API)

1. **Fragenspeicher:** Jede Frage wird gespeichert und wiederverwendet, **höchstens 3-mal insgesamt** und frühestens,
   wenn **mindestens 1 andere Session** des Moduls dazwischen lag. Danach wird sie stillgelegt, und für dieses
   Minithema entsteht eine neue Frage.
2. **Klausurstil-Profil je Modul:** Altklausuren und Übungsblätter werden einmal zu einem kompakten Stilprofil
   zusammengefasst (Aufgabentypen, Operatoren, Schwierigkeit, typische Fallen, 3 Beispielaufgaben, ca. 1.500
   Wörter). Bisher gehen bei jeder Erstellung bis zu 50.000 Zeichen Altklausur mit. Das Profil wird nur neu
   erstellt, wenn neue Altklausuren hochgeladen werden.
3. **Nur der nötige Stoff:** Für neue Fragen bekommt Claude nur die Folienseiten und Notizen der betroffenen
   Minithemen, nicht die ganze Vorlesung.
4. **Gebündelt erzeugen:** eine Anfrage pro Session für alle neuen Fragen. Dabei entsteht pro Minithema gleich
   die nächste Stufe mit (Vorrat). Der Stoff wird so einmal bezahlt und reicht für zwei Sessions.
5. **Alles bei der Erstellung mitliefern:** Tipps (3 Stufen), Begründung je Option, Musterlösung. Nach dem
   Antworten ist kein weiterer Aufruf nötig.
6. **Auswahlfragen und Kopfrechnen prüft die App selbst** (kostenlos). Nur Freitext geht an Haiku.
7. **Prompt-Caching:** fester Regel-Teil plus Stilprofil als gecachter System-Prompt (spart bei Folgeaufrufen
   bis zu 90 % auf diesen Teil).
8. **Günstige Modelle, wo es reicht:** Haiku für Karten-Zuordnung, Übungs-Rückmeldung zuordnen,
   Freitext-Bewertung. Sonnet für Minithemen und Fragen.
9. **Kosten vorher anzeigen** („ca. 9 Cent“) wie heute.

Grobe Schätzung: Minithemen pro Vorlesung ca. 5–10 Cent (einmalig), Vorlesungs-Check ca. 8–12 Cent,
Wochentraining mit Wiederverwendung ca. 2–6 Cent, Freitext-Bewertung unter 0,1 Cent.

## 11. Navigation, Modul-Ansicht, Tages- und Wochenplan

- Seitenleiste: „Karteikarten“ → **„Vorlesungs-Check“**, „Quiz“ → **„Wochentraining“**.
- **Modul → Ablauf:** Jede Vorlesung ist eine Zeile mit vier Schritt-Markierungen
  (Nacharbeiten · Check · Übungsblatt · Wochentraining), jeweils erledigt (grün mit Haken), offen (gestrichelt)
  oder überfällig (rot umrandet). Dazu ein Abdeckungsbalken („9 von 12 Minithemen abgefragt“) und ein farbiger
  Wissensstand. Ein Klick öffnet den passenden Schritt.
- **Reiter „Lernen & Klausur“** wird zu **„Wissensstand“**: Themenbaum aller Vorlesungen mit Farbe je Minithema,
  Abdeckung je Vorlesung, Start Wochentraining, darunter **Altklausuren** (Hochladen und Speichern wie bisher).
  **Tutor** wird ganz entfernt (auch auf der Vorlesungsseite). **Klausuraufgaben** werden vorerst ausgeblendet
  (Code und ausgelesene Aufgaben bleiben gespeichert). Karteikarten, Quiz und Schwachstellen fallen weg.
- **Definitionen:** Neue Einträge entstehen aus den Minithemen der Art „Definition“. Alle bisherigen
  Definitionen bleiben erhalten.
- **To-dos pro Vorlesung, immer in dieser Reihenfolge:**
  1. „Vorlesung X nacharbeiten (Folien hochladen, kommentieren, genau lesen)“: Frist wie bisher
  2. „Vorlesung X [Modul] Check“: gleiche Frist (direkt danach)
  3. „Übungsblatt …“: das Blatt zum Kapitel dieser Vorlesung, Frist wie bisher
  4. „Wochentraining [Modul] (inkl. Übungen und früherer Vorlesungen)“: einmal pro Woche und Modul. Möglich ab
     der Übungsblatt-Frist, **spätestens am Tag vor der nächsten Vorlesung des Moduls**. Erledigt, sobald im
     Zeitraum ein Training abgeschlossen ist.

  Ein Übungsblatt gehört zu einem Kapitel, also oft zu mehreren Vorlesungen. Es erscheint deshalb bei der
  **letzten** Vorlesung dieses Kapitels.
- **Rückstand erkennen und aufholen:** Heute bekommt oben einen Kasten **„Aufholplan“**, sobald etwas überfällig
  ist.
  - **Modul-Rangfolge:** 1. ExRW und I&F · 2. Statistik und Mathe · 3. VWL (in den Einstellungen änderbar).
  - **Reihenfolge:**
    1. Übungsblätter, deren Besprechung in den nächsten 2 Tagen ist (feste Termine), mit dem nötigen
       Nacharbeiten bzw. Check der zugehörigen Vorlesungen davor.
    2. Je Modul die **älteste** offene Vorlesung zuerst (Stoff baut aufeinander auf), Module nach Rangfolge.
    3. Je Modul ein kurzes Wochentraining (5 Fragen) pro Woche, auch im Rückstand.
  - **Zeitbudget** (in den Einstellungen änderbar): Mo 2 h · Di 4 h · Mi 6 h · Do 2 h · Fr–So zusammen 12 h
    (als Start 4 h pro Tag, pro Woche anpassbar, weil das je nach Terminen schwankt).
  - **Geschätzte Dauer:** Übungsblatt 3 h · Nacharbeiten 1 h · Vorlesungs-Check 30 min · Wochentraining
    10–30 min. Die App lernt aus deinen tatsächlichen Zeiten nicht dazu (bewusst einfach gehalten), du kannst die
    Werte aber in den Einstellungen anpassen.
  - Die App verteilt Rückstand und laufende Aufgaben auf die Tage. Passt etwas nicht mehr in die Woche, zeigt sie
    ehrlich an, wann du voraussichtlich aufgeholt hast.
- Push-Benachrichtigungen erinnern an fällige Checks und Trainings statt an Karten.

## 12. Design

- Fortschritt sichtbar: Abdeckungsringe je Vorlesung, Wissensstand-Balken je Modul, Wochenziel
  („2 von 5 Trainings“), Lerntage in Folge, Ergebnisseite mit „sicherer geworden“.
- Farben: rot / orange / grün nur für Bewertung und Wissensstand, sonst Modulfarben. Icons über Material-Symbole.
- **Keine Emojis**: Ich ersetze auch die Zeichen ✓ ○ ↩ ↔ in der Oberfläche durch Material-Symbole.
- Handy: Session einspaltig, große Antwortflächen, Bewertung und „Weiter“ unten in Daumennähe, Folienbilder in
  voller Breite.

## 13. Betroffene Dateien

| Neu | Inhalt |
|---|---|
| `utils/topics.py` | Minithemen erzeugen, Ausschlüsse, Abdeckung |
| `utils/mastery.py` | Wissensstand, FSRS je Minithema, Stufenleiter, Umrechnung, Archiv-Hinweise |
| `utils/question_bank.py` | Fragen erzeugen, wiederverwenden, stilllegen, Stilprofil |
| `utils/sessions.py` | Auswahl für Check und Training, Auswertung, Zeitbudget |
| `utils/migration.py` | Backup, Archivierung, Prüfung |
| `views/check_center.py` | Seite „Vorlesungs-Check“ |
| `views/training_center.py` | Seite „Wochentraining“ |
| `views/session_ui.py` | gemeinsame Frage-Ansicht (Tipp, Folien, Bewertung, Freitext) |
| `views/archive_view.py` | Einstellungen → Ausgeblendet |

Geändert werden: `app.py`, `views/common.py` (Seiten), `lecture_page.py` (Nacharbeiten-Schritte, Folien
ausblenden), `ablauf.py`, `learn.py`, `module_view.py`, `today_view.py`, `dashboard.py`, `planner.py`,
`units.py` (To-dos), `exercise_page.py` (Zuordnung der Rückmeldung), `settings_view.py`, `notify.py`, `export.py`,
`ai.py` (Schemas), `CLAUDE.md`, Tests.
Erhalten, aber ausgeblendet: `cards_center.py`, `quiz_center.py`, `study.py`, Karten-Teile in `learning.py`.

## 14. Reihenfolge der Umsetzung

Jeder Schritt wird getestet und hochgeladen. Bis Schritt E bleibt die App für dich wie heute.

| Schritt | Inhalt |
|---|---|
| A | Migration + Backup + Archiv-Markierung (noch ohne sichtbare Änderung), mit Tests zum Datenerhalt |
| B | Themen-Modell: Minithemen beim Nacharbeiten, Folien ausblenden am Bild, Themenbaum |
| C | Wissensstand-Logik und Fragenspeicher (Stufen, FSRS je Minithema, Wiederverwendung, Stilprofil) |
| D | Gemeinsame Frage-Ansicht + Vorlesungs-Check |
| E | Wochentraining + Umschalten der Navigation, Karten wandern nach „Ausgeblendet“ |
| F | Archiv-Zuordnung, Übungs-Rückmeldung → Minithemen, Minithemen für frühere Vorlesungen nachholen |
| G | Ablauf mit Schritten, To-dos in fester Reihenfolge, Aufholplan |
| H | Design-Durchgang, Emojis raus, Handy-Feinschliff, CLAUDE.md |

Du kannst nach D/E schon testen. Ich würde A–E zusammen ausliefern (dann funktioniert der neue Ablauf
vollständig) und F–H direkt danach.

## 15. Deine Entscheidungen (07.11.)

1. Alle Folien werden genau gelesen. Ein Klick aufs Bild schließt eine Folie aus. Wiederholte Folien aus früheren
   Vorlesungen sowie Titel-/Orga-Folien werden automatisch vorgeschlagen.
2. Hinweise zur Quiz-Erstellung: Umfang (ganze Vorlesung oder Folie x bis y), Wichtig, Streichen, Sonstiger
   Hinweis. Beispiele werden nie abgefragt, außer du sagst es.
3. Freitext auch in Mathe und ExRW, schon im ersten Check.
4. Fristen wie vorgeschlagen. Wochentraining spätestens am Tag vor der nächsten Vorlesung des Moduls.
5. Taschenrechner/Notizblatt auch beim Check vorher abfragen.
6. Archiv-Einstieg: egal → Minithemen mit Archiv-Hinweis „sicher“ starten mit Multiple Choice, alle anderen mit
   Single Choice.
7. Rangfolge ExRW, I&F > Statistik, Mathe > VWL. Zeitbudget siehe 11. Übungsblätter mit 3 h eingeplant.
8. Frühere Vorlesungen: kein Check, nur Wochentraining. Minithemen per Knopf gesammelt anlegen.
9. Definitionen aus Minithemen.
10. Tutor komplett raus, Klausuraufgaben vorerst raus, Altklausuren bleiben.
11. Wiederverwendung: frühestens nach 1 anderen Session, höchstens 3-mal.
12. Bewertungsknöpfe auch nach falscher Antwort.

## 16. Noch offen (kurz)

A. **Umfang „bis Folie x“:** Sollen die restlichen Folien automatisch der nächsten Vorlesung zugeschlagen werden
   (dann werden sie dort abgefragt), oder trägst du das in der nächsten Vorlesung selbst ein? Mein Vorschlag:
   automatisch vormerken. Die nächste Vorlesung zeigt sie dann als „noch offen aus VL x“, und du bestätigst.
