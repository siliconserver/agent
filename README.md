# AGENT (Atemschutz-Geräteträger-Eignungs- & Nachweis-Tool)

AGENT ist eine Web-App für Feuerwehren, mit der die Atemschutzbeauftragten den
Überblick über ihre Atemschutzgeräteträger (AGT) behalten: Wer ist einsatzbereit,
wessen G26 läuft bald ab, wer braucht noch eine Belastungsübung oder
UVV-Unterweisung? AGENT rechnet die Tauglichkeit automatisch aus, erinnert die
Geräteträger per E-Mail und schickt der Wehrführung jede Woche einen Bericht.
Alles läuft auf eurem eigenen Server, die Daten bleiben bei euch.

## Funktionen

- **Geräteträger verwalten**: Name, Kontakt, G26 gültig bis, letzte
  Belastungsübung, UVV-Unterweisung, letzte AGT- und CSA-Einsätze, PA- und
  CSA-Tauglichkeit, aktiv/inaktiv. Die Liste lässt sich per Klick auf die
  Spaltenüberschriften sortieren, inaktive Geräteträger lassen sich ausblenden.
- **Automatische Tauglichkeitsprüfung**: Ein AGT gilt automatisch als nicht
  tauglich, wenn die G26 abgelaufen ist oder im laufenden und letzten
  Kalenderjahr keine Belastungsübung oder keine UVV-Unterweisung stattfand.
  Die Prüfung läuft täglich zur eingestellten Uhrzeit und auf Knopfdruck.
- **Dashboard und Berichte**: Wie viele AGT sind aktiv, tauglich, untauglich
  (als Zahl und in %), wessen G26 läuft in den nächsten 3 Monaten ab oder ist
  schon abgelaufen, wem fehlt Belastungsübung oder UVV-Unterweisung.
- **Belastungsübungen planen**: Termine anlegen und pro Termin bis zu 10 AGT
  eintragen (6 fest, 4 auf Rückfrage). Die Teilnehmer bekommen sofort eine Mail
  und 3 Tage vorher eine Erinnerung mit der Liste der anderen Teilnehmer. Nach
  dem Termin wird die Übung automatisch beim AGT als „letzte Belastungsübung“
  eingetragen. Ältere Jahre bleiben im Archiv.
- **E-Mails**: G26-Erinnerung an den Geräteträger, wenn die Untersuchung in
  90 Tagen abläuft (optional mit Kopie an eine feste Adresse), und ein
  wöchentlicher Bericht an die Wehrführung. Alle Texte sind in der
  Weboberfläche anpassbar.
- **Export**: Geräteträger als CSV, Berichte und Terminübersichten als PDF.
- **Backups**: Tägliche Sicherung der Datenbank, dazu manuelle Sicherung,
  Download und Wiederherstellung direkt in der Weboberfläche.
- **Benutzer und Rollen**: Admins dürfen alles, Viewer nur lesen. Optional
  Zwei-Faktor-Anmeldung mit einer Authenticator-App (Google Authenticator, Authy …).
- **App fürs Handy**: Im Browser „Zum Home-Bildschirm hinzufügen“, dann startet
  AGENT wie eine eigene App im Vollbild.

## Auf dem eigenen Server starten

Du brauchst einen Server (oder Raspberry Pi, NAS …) mit
[Docker](https://docs.docker.com/engine/install/) und Docker Compose.

1. **Herunterladen**: Die aktuelle Version unter
   [Releases](https://github.com/siliconserver/agent/releases/latest) als ZIP
   oder tar.gz laden und auf dem Server entpacken. Gebraucht werden daraus nur
   `docker-compose.yml` und `.env.example`.

2. **Einstellungen anlegen**:
   ```bash
   cp .env.example .env
   ```
   In der `.env` mindestens diese Werte ändern:
   - `POSTGRES_PASSWORD` (und dasselbe Passwort in `DATABASE_URL`)
   - `SECRET_KEY`: ein langer Zufallswert, z. B. aus `openssl rand -hex 32`
   - `ADMIN_USERNAME` / `ADMIN_PASSWORD`: dein Login
   - `SMTP_*` und `ADMIN_EMAIL`, damit Erinnerungen und Wochenbericht verschickt werden
   - optional `IMPRESSUM_URL` und `DATENSCHUTZ_URL`, wenn AGENT öffentlich
     erreichbar ist. Die Links erscheinen dann unten auf jeder Seite.

3. **Starten**:
   ```bash
   docker compose pull
   docker compose up -d
   ```

4. **Öffnen**: Im Browser `http://<server>:8085` aufrufen (Port über
   `AGENT_PORT` in der `.env` änderbar) und mit dem Admin-Login aus der `.env`
   anmelden. Der Admin wird beim ersten Start automatisch angelegt.

5. **Einrichten**: Unter **Einstellungen** die Uhrzeiten für Prüfung, Mails und
   Backups, die Mailtexte und weitere Benutzer festlegen.

Die `.env` enthält Passwörter. Sie gehört nicht in ein Git-Repository und sollte
nur für den Server-Benutzer lesbar sein (`chmod 600 .env`). Für den Zugriff aus
dem Internet gehört AGENT hinter einen Reverse-Proxy mit HTTPS (z. B. Caddy,
Traefik oder nginx).

### Aktualisieren

Im Ordner mit der `docker-compose.yml`:

```bash
docker compose pull && docker compose up -d
```

Standardmäßig läuft immer die neueste Version. Wer bei einer festen Version
bleiben will, trägt sie in der `.env` bei `AGENT_TAG` ein (z. B. `AGENT_TAG=2.0`).
Was sich in einer Version geändert hat, steht im [Changelog](CHANGELOG.md) und in
der App unter „Über AGENT“.

### Wo liegen meine Daten?

Alles liegt im Ordner `data/` neben der `docker-compose.yml`:

```
data/
  postgres/   # die Datenbank
  backups/    # tägliche und manuelle Backups (.sql.gz)
```

Für einen Umzug auf einen anderen Server kopierst du den ganzen Ordner
(inklusive `data/` und `.env`) und startest dort mit `docker compose up -d`.

### Backup wiederherstellen

Unter **Einstellungen → Backups** bei einem Backup auf „Wiederherstellen“
klicken. Achtung: Das ersetzt alle aktuellen Daten durch den Stand des Backups.
Die `.sql.gz`-Dateien liegen zusätzlich unter `data/backups` und können von
dort mit einem eigenen Skript weggesichert werden.

## Selbst bauen

Wer das Image lieber selbst baut, klont das Repository und startet mit:

```bash
docker compose up -d --build
```

## Lizenz

MIT-Lizenz, siehe [LICENSE](LICENSE).
