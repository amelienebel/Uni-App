# 🎓 BWL-Lernplattform LMU

Persönliche Streamlit-Lernplattform für das BWL-Studium an der LMU München – mit Wochenplanung,
Klausur-Countdown, Folienanalyse, Spaced Repetition, Formelsammlung, Altklausur-Analyse und KI-Tutor (Claude).

## Schnellstart

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # danach ANTHROPIC_API_KEY eintragen
streamlit run app.py
```

Ohne API-Key läuft die App im **Offline-Modus**: Textextraktion, heuristische Folienanalyse, Formelerkennung,
Lernkarten aus Formeln/Notizen, Quiz aus Formelsammlung und Karten, Signalwort-Analyse, Export und Planung
funktionieren vollständig. Chats, KI-Zusammenfassungen und KI-Korrektur benötigen den Key.

## Auf Handy und Mac nutzen

Die App lässt sich kostenlos online stellen (Streamlit Community Cloud) und als App-Symbol auf Handy und Mac
ablegen. Daten bleiben über einen privaten GitHub-Speicher erhalten, ein Passwort schützt den Zugang.
👉 Schritt-für-Schritt ohne Programmierkenntnisse: **[ANLEITUNG.md](ANLEITUNG.md)**

## Navigation

| Bereich | Inhalt |
|---|---|
| 🏠 **Wochenübersicht & Lernplan** | Klausur-Countdown, Wochenraster aus dem Stundenplan, generierte To-dos mit Fristen (Vorlesung vor-/nachbereiten, Übungsblatt, Wiederholung, Altklausur), Fortschrittsbalken pro Modul, priorisierter Lernfahrplan |
| **Heute** | Termine, fällige To-dos, Karteikarten, Tages-Podcast, Klausurplan und Schwachstellen auf einen Blick |
| **Klausur-Lernplan** | Verteilt Kapitel-Wiederholung, Schwachstellen und Altklausuren automatisch auf die Tage bis zu den Klausuren |
| 📚 **Modul-Bereiche** | Pro Modul 3 Reiter: **Ablauf** (Kapitel mit Vorlesungen, Übungen und Tutorien – jede Vorlesung/Übung hat eine eigene Seite mit Dateien, Vorbereitung, Nachbereitung und Lernen) · **Lernen & Klausur** (mehrere Vorlesungen auswählen: Karteikarten, Quiz, Tutor, Altklausuren) · **Formeln & Notizen** |
| 📐 **Zentrale Formelsammlung** | Alle Formeln modulübergreifend, filter- und durchsuchbar, LaTeX-Rendering mit `st.latex`, Markdown-Download |
| 📂 **Bulk-Upload** | Viele PDFs oder Moodle-ZIP-Ordner auf einmal; automatische Zuordnung zu Modul, Dokumenttyp und Kapitel, vor dem Import korrigierbar |
| 📥 **Export & Backup** | Notizen, Zusammenfassungen, Formeln, Karten als Markdown oder PDF; komplettes Backup/Restore als ZIP |
| ⚙️ **Einstellungen & Klausurtermine** | Klausurtermine, Semesterzeitraum, Stundenplan, Lernparameter, KI-Modell und Effort |

## Wichtige Funktionen im Detail

- **Klausurdruck in der Wiederholung:** Je näher die Klausur (≤ 45 / 21 / 7 Tage), desto kürzer die Intervalle
  (Faktor 0,8 / 0,6 / 0,4) und desto höher die Priorität fälliger Karten. Zusätzlich wird jedes Intervall so gedeckelt,
  dass jede Karte vor der Klausur noch mindestens einmal drankommt (`utils/spaced_repetition.py`).
- **Bewertung:** „Gar nicht kann“, „Etwas kann“, „Gut kann“, „Perfekt kann“ → SM-2-Logik (Anki-Prinzip).
- **To-dos ↔ Kapitelstatus:** Abhaken von „Vorlesung vorbereiten/nachbereiten/Übungsblatt“ setzt den Kapitelstatus –
  daraus berechnet sich der Fortschrittsbalken (70 % Kapitel, 30 % Kartenbeherrschung).
- **Folien-Zusammenfassung:** wird direkt nach dem Hochladen erstellt. **Karteikarten** decken den gesamten Stoff ab (Folien + Nachbereitung) und werden beim Abschließen der Nachbereitung automatisch erstellt bzw. ergänzt.
- **Signalwort-Analyse:** erkennt Operatoren wie „Erläutern Sie“, „Berechnen Sie“, „Zeigen Sie rechnerisch“,
  „Bilden Sie die Buchungssätze“, ordnet Anforderungsbereiche zu und erklärt, wie die Antwort aufgebaut sein muss.

## Projektstruktur

```
app.py                      Haupteinstieg, Seitenleiste & Routing
config.json                 Module, Kapitel, Stundenplan-Vorlagen, Schlüsselwörter, Basisformeln
utils/
  config.py                 Laden der Konfiguration
  storage.py                JSON-Persistenz in data/ + st.session_state
  pdf_parser.py             Text-/Formelextraktion (pdfplumber, Fallback pypdf), Auto-Zuordnung, ZIP-Import
  spaced_repetition.py      SM-2 mit Klausurdruck, Prioritäten, Prognose
  planner.py                Semesterwochen, To-dos, Fortschritt, Lernempfehlungen
  exam_analysis.py          Operatoren-/Signalwort-Analyse
  ai.py                     Anthropic-API (Streaming, strukturierte Ausgaben, Fehlerbehandlung)
  export.py                 Markdown-/PDF-Export, Backup/Restore
  cloud_sync.py             Optionaler Cloud-Speicher: spiegelt data/ in ein privates GitHub-Repository
views/
  dashboard.py, module_view.py, formulas.py, bulk_upload.py, export_view.py, settings_view.py, common.py
  module_tabs/              syllabus, preparation, review, flashcards, formulas_tab, exams, tutor
data/                       Deine Lerndaten (nicht im Git, siehe .gitignore)
```

## Anpassen & Erweitern

- **Weiteres Modul:** einfach einen Eintrag in `config.json` → `modules` ergänzen (id, name, short, icon, keywords,
  schedule, chapters, base_formulas). Es erscheint automatisch überall.
- **Stundenplan & Kapitel:** Die Vorgaben in `config.json` sind **Beispielwerte**. Trage deinen echten LSF-Stundenplan
  unter ⚙️ Einstellungen ein und passe die Kapitel im Reiter „Ablauf“ (⚙️ Kapitel bearbeiten) an den tatsächlichen Vorlesungsverlauf an.
- **KI-Modell:** Standard ist Claude Opus 5.5 mit Effort „Mittel“. Sonnet 5.5 bzw. Haiku 5.5 sind günstiger.
  Für Opus/Sonnet ist der serverseitige Fallback (`fallbacks="default"`) aktiv: Lehnt das Modell eine Anfrage ab,
  übernimmt automatisch ein anderes Modell.

## Datenschutz

Alle Daten liegen lokal im Ordner `data/`. An die Anthropic-API gehen nur die Inhalte, die du für eine KI-Funktion
explizit auslöst (z. B. Folientext bei „Folien analysieren“). Der API-Key wird nur aus `.env` gelesen und nie angezeigt.

## Push-Erinnerungen & Tages-Podcast

- **Push:** über die kostenlose App *ntfy* (Thema steht unter Einstellungen). Die App plant beim Öffnen die
  Erinnerungen der nächsten 3 Tage ein (nur wenn Karteikarten fällig sind).
- **Podcast:** an Vorlesungstagen ca. 10 Minuten Audio (zwei Stimmen, edge-tts) zu den Vorlesungen des Tages,
  erstellt aus Folien und Nachbereitung.
