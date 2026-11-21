# Changelog

Alle relevanten Änderungen an AGENT. Neueste Version oben.
Diese Datei wird auch auf der Seite „Über AGENT“ angezeigt; die oberste Version ist die App-Version.

## 2.1 (2026-11-21)
- Fristregel für UVV-Unterweisung und Belastungsübung vereinheitlicht: „jährlich“ heißt einmal pro Kalenderjahr. Ein Nachweis gilt im Jahr, in dem er absolviert wurde, und im ganzen folgenden Jahr (UVV am 25.10.2026 → gültig bis 31.12.2027). Fehlt ein Datum, ist der AGT untauglich
- Die Prüfung steckt an einer zentralen Stelle und wird überall gleich verwendet: täglicher Tauglichkeitslauf, Dashboard, Geräteträger-Liste, Berichte, PDF-/CSV-Export und Wochenreport
- Geräteträger-Liste, Detailansicht und CSV-Export zeigen „UVV gültig bis“ und „Belastungsübung gültig bis“ (31.12. des Folgejahres), abgelaufene Fristen in Rot
- Neuer Bericht „Läuft zum 31.12. ab“: aktive AGT, deren UVV-Unterweisung oder Belastungsübung aus dem Vorjahr stammt, im Dashboard, unter Berichte, im PDF-Bericht und im Wochenreport

## 2.0 (2026-10-24)
- Erste öffentliche Version in einem eigenen Repository, fertige Docker-Images unter `ghcr.io/siliconserver/agent`
- Neue Releases und Images entstehen automatisch, sobald eine neue Version in dieser Datei auf `main` landet
- „Über AGENT“ zeigt den kompletten Changelog und verlinkt das Projekt auf GitHub (Quellcode, Issues, Changelog)
- Impressum- und Datenschutz-Link im Fußbereich sind jetzt pro Installation einstellbar (`IMPRESSUM_URL`, `DATENSCHUTZ_URL`) und werden ohne Eintrag ausgeblendet
- Zeitzone (`TZ`) und Port (`AGENT_PORT`) sind in der `.env` einstellbar
- Die BCC-Adresse der G26-Erinnerung ist jetzt standardmäßig leer und bleibt leer, wenn man sie in den Einstellungen löscht
- Der Offline-Cache der Handy-App wird bei jeder neuen Version automatisch erneuert

## 1.9 (2026-10-03)
- Geräteträger-Liste überarbeitet: Spalte „Aktiv“ entfernt (inaktive AGT sind ohnehin ausgegraut), dafür „UVV Unterweisung“ ergänzt
- Als App auf dem Handy installierbar (Progressive Web App) und mehrere Darstellungsfehler auf dem Handy behoben
- Neues Logo, Seite „Über AGENT“, Fußbereich mit Version
- Zwei-Faktor-Anmeldung mit Authenticator-App und Profil-Menü mit eigener Passwortänderung
- Belastungsübungs-Termine mit AGT-Zuweisung, PDF-Export, Zuweisungs- und Erinnerungsmails
- Geräteträger-Liste sortierbar, inaktive Geräteträger ausblendbar, Geräteträger löschbar
- Dashboard und PDF-Bericht listen taugliche und untaugliche AGT namentlich

## 1.0 (2026-08-23)
- Initialer Stand: Geräteträger-Verwaltung, automatische Tauglichkeitsprüfung, G26-Erinnerungen, Wochenreport, Berichte, CSV-/PDF-Export, Benutzer und Rollen, Einstellungen mit Zeitplan, E-Mail-Texten und Backups
