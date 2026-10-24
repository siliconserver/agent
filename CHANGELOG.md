# Changelog

Alle relevanten Änderungen an AGENT. Neueste Version oben.
Diese Datei wird auch auf der Seite „Über AGENT“ angezeigt; die oberste Version ist die App-Version.

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
