# Assist Performance Monitor

Diese experimentelle Home-Assistant-App installiert und aktualisiert die
Custom Integration **Assist Performance Monitor** sowie das zugehörige
Dashboard. Die eigentliche Diagnose läuft anschließend im Home-Assistant-
Prozess, weil nur dort der interne Assist-Pipeline-Debugpuffer verfügbar ist.

Die App verändert Home Assistant nicht beim bloßen Installieren. Erst ihr Start
kopiert die Dateien nach `/config`. Eine vorhandene Integrationskopie wird zuvor
im persistenten App-Datenordner gesichert.

Aktueller Stand:

- App-Version: **0.1.0**
- Integrationsversion: **0.2.2**
- Entwicklungsstatus: **experimentell und noch nicht live getestet**

Details stehen in [DOCS.md](DOCS.md).

