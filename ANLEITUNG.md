# 📱💻 Lernplattform auf Handy und Mac einrichten

Diese Anleitung braucht **keine Programmierkenntnisse**. Du klickst dich einmal durch fünf Teile, das dauert
etwa 20–30 Minuten. Danach hast du die App als Symbol auf dem Handy und im Dock deines Macs. Beide Geräte
sehen immer denselben Stand.

**So funktioniert es:** Die App läuft kostenlos im Internet bei *Streamlit*. Deine Daten (Notizen, Lernkarten,
PDFs) werden in einem privaten Speicher bei *GitHub* gesichert, den nur du sehen kannst. Die KI kommt von
*Anthropic*. Ein Passwort schützt die App vor fremden Zugriffen.

> 💡 Tipp: Erledige die Schritte am Mac. Lege dir eine Notiz an, in die du die drei „Schlüssel“ aus
> Teil B, C und dein Passwort kurz hineinkopierst – du brauchst sie in Teil D.

---

## Teil A – Privaten Datenspeicher anlegen (2 Minuten)

1. Öffne **github.com** und melde dich an.
2. Klicke oben rechts auf **„+“** → **„New repository“**.
3. Bei **Repository name** eintragen: `uni-app-daten`
4. **„Private“** auswählen (wichtig!).
5. Den Haken bei **„Add a README file“** setzen.
6. Unten auf **„Create repository“** klicken. Fertig.

## Teil B – Schlüssel für den Datenspeicher (5 Minuten)

Damit die App in deinen Speicher schreiben darf, braucht sie einen Schlüssel („Token“).

1. Öffne **github.com/settings/personal-access-tokens/new**
2. **Token name:** `Lernplattform`
3. **Expiration (Ablaufdatum):** die längste mögliche Dauer wählen.
4. **Repository access:** **„Only select repositories“** → im Auswahlfeld **`uni-app-daten`** wählen.
5. Bei **Permissions** → **Repository permissions** den Eintrag **„Contents“** suchen und auf
   **„Read and write“** stellen. (Alles andere so lassen.)
6. Ganz unten **„Generate token“** klicken.
7. Den angezeigten Schlüssel (beginnt mit `github_pat_`) **kopieren** und in deine Notiz einfügen.
   Er wird nur einmal angezeigt!

## Teil C – Schlüssel für die KI (5 Minuten)

1. Öffne **console.anthropic.com** und lege ein Konto an bzw. melde dich an.
2. Unter **Billing / Abrechnung** etwas Guthaben aufladen (z. B. 5–10 €). Dort kannst du auch ein
   **Ausgabenlimit** setzen, damit nie mehr verbraucht wird als gewollt.
3. Unter **API Keys** auf **„Create Key“** klicken, Namen `Lernplattform` eingeben.
4. Den Schlüssel (beginnt mit `sk-ant-`) **kopieren** und in deine Notiz einfügen.

> Ohne diesen Schlüssel funktioniert die App auch – aber ohne KI-Zusammenfassungen und Chats.

## Teil D – App online stellen (10 Minuten)

1. Öffne **share.streamlit.io** und wähle **„Continue with GitHub“**. Bestätige die Anfrage von GitHub.
2. Klicke auf **„Create app“** und wähle die Variante **„aus GitHub“ / „Deploy a public app from GitHub“**.
3. Fülle aus:
   - **Repository:** `amelienebel/uni-app`
   - **Branch:** `claude/streamlit-bwl-learning-platform-c129um`
   - **Main file path:** `app.py`
   - **App URL:** einen Namen nach Wahl, z. B. `bwl-lernen-amelie`
4. Klicke auf **„Advanced settings“**. Wähle bei **Python version** `3.12` (falls angeboten).
   Füge in das Feld **„Secrets“** Folgendes ein und ersetze die Platzhalter durch deine Werte aus der Notiz
   (die Anführungszeichen müssen bleiben):

   ```toml
   ANTHROPIC_API_KEY = "sk-ant-HIER-DEIN-KI-SCHLÜSSEL"
   GITHUB_TOKEN = "github_pat_HIER-DEIN-SPEICHER-SCHLÜSSEL"
   GITHUB_DATA_REPO = "amelienebel/uni-app-daten"
   APP_PASSWORD = "HIER-EIN-EIGENES-PASSWORT"
   ```

   Das Passwort denkst du dir selbst aus – damit meldest du dich später in der App an.
5. **„Save“** und dann **„Deploy“** klicken. Die App wird jetzt gebaut – das dauert beim ersten Mal
   2–5 Minuten. Danach erscheint die Anmeldeseite. 🎉

> Die Adresse deiner App sieht so aus: `https://bwl-lernen-amelie.streamlit.app`

## Teil E – Als App aufs Handy und in den Mac-Dock

Melde dich jeweils zuerst an und lass **„Auf diesem Gerät angemeldet bleiben“** angehakt. **Erst danach** das
Symbol anlegen – dann musst du das Passwort nicht jedes Mal eintippen.

**iPhone (Safari):**
1. App-Adresse in Safari öffnen und anmelden.
2. Unten auf das **Teilen-Symbol** (Quadrat mit Pfeil) tippen → **„Zum Home-Bildschirm“** → **„Hinzufügen“**.

**Android (Chrome):**
1. App-Adresse in Chrome öffnen und anmelden.
2. Oben rechts **⋮** → **„Zum Startbildschirm hinzufügen“** bzw. **„App installieren“**.

**Mac (Safari):**
1. App-Adresse in Safari öffnen und anmelden.
2. In der Menüleiste **„Ablage“** → **„Zum Dock hinzufügen …“** → **„Hinzufügen“**.
   (Mit Chrome: Menü **⋮** → **„Installieren“** bzw. **„Als App installieren“**.)

Jetzt startest du die Lernplattform wie jede andere App über ihr Symbol.

---

## Gut zu wissen

- **Menü auf dem Handy:** Die Navigation (Wochenübersicht, Module, Formelsammlung …) öffnest du über das
  kleine **„>“ oben links**.
- **App „schläft“:** Wird die App einige Zeit nicht benutzt, legt Streamlit sie schlafen. Beim nächsten Öffnen
  erscheint ein Knopf wie **„Yes, get this app back up!“** – draufklicken und ca. eine Minute warten.
  Deine Daten sind dabei sicher, sie werden aus dem GitHub-Speicher wieder geladen.
- **Wird gespeichert?** Unten in der Seitenleiste steht **„☁️ Alles im Cloud-Speicher gesichert“**. Änderungen
  werden spätestens nach einer Minute gesichert; mit **„Jetzt sichern“** geht es sofort.
- **Fotos von Tafelbildern:** Im Reiter *Nachbereitung* kannst du am Handy direkt die Kamera verwenden.
- **Kosten:** Streamlit und GitHub sind kostenlos. Die KI kostet je nach Nutzung – behalte dein Guthaben in der
  Anthropic-Konsole im Blick. Günstigere KI-Modelle kannst du in der App unter ⚙️ Einstellungen wählen.
- **Schlüssel oder Passwort ändern:** Auf share.streamlit.io bei deiner App auf **⋮** → **„Settings“** →
  **„Secrets“**, Wert ändern, speichern.
- **Zusätzliche Sicherung:** Unter 📥 *Export & Backup* kannst du jederzeit ein komplettes Backup als ZIP
  herunterladen.

## Wenn etwas nicht klappt

| Meldung / Problem | Lösung |
|---|---|
| „Cloud-Speicher nicht verbunden: Token ungültig“ | Teil B wiederholen und den neuen Schlüssel unter *Secrets* eintragen. |
| „Repository nicht gefunden“ | Prüfen, ob `GITHUB_DATA_REPO` genau `amelienebel/uni-app-daten` lautet und der Token Zugriff darauf hat (Teil B, Schritt 4). |
| „Kein API-Key – Offline-Modus“ | `ANTHROPIC_API_KEY` in den *Secrets* prüfen (Anführungszeichen!). |
| KI meldet „Rate-Limit“ oder Fehler beim Guthaben | Guthaben in der Anthropic-Konsole aufladen. |
| Nach dem Ändern der Secrets passiert nichts | Bei der App auf share.streamlit.io **⋮** → **„Reboot app“**. |
