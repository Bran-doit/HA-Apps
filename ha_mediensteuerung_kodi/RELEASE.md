# Freigabeplan für 0.5.0

## Bereits vorbereitet

- Eigenständiger amd64-Container mit AppDaemon; keine Abhängigkeit von der vorhandenen AppDaemon-App.
- Per Digest fixiertes Basisimage und mit Version/Hash fixierte Linux-Python-Abhängigkeiten.
- Setup-/Betriebsmodus, Datei-Backups, Konfliktschutz, Rückrollen bei Kopierfehlern und Schutz gegen aktive Altinstanz.
- Private Player-Konfiguration erhalten; Ausgabepräferenzen einmalig übernehmen.
- MIT-Lizenz, Bedienung, Umzugs-/Backup-Anleitung und Offline-Tests.
- Workflow `Mediensteuerung preparation`: Unit-Tests, Containerbau, Smokechecks, Image-Archiv und SHA256. Keine Registry-Veröffentlichung.

## Verbindlich vor Freigabe

1. Erfolgreichen Vorbereitungslauf des exakten Commits prüfen. Das daraus erzeugte Image herunterladen und SHA256 vergleichen; CI-Artefakte sind nur 14 Tage verfügbar und kein Release-Download.
2. App-Metadaten mit aktuellem Supervisor-Schema prüfen. Isolierte HA-Testinstanz auf amd64: frische Installation, Setup, HA-Neustart, Dashboard, Sprachdienst, Playerkonfiguration und Neustartpersistenz testen.
3. Migration mit einer Kopie vorhandener Konfiguration testen: alte App aktiv => neuer Run verweigert; alte App deaktiviert => neue App übernimmt; Einstellungen und Zugangsdaten bleiben erhalten. Upgrade und Rückkehr zur alten Version prüfen. Produktive Installation nur im vereinbarten Wartungsfenster ändern.
4. Das bereits getestete Image unter `ghcr.io/bran-doit/ha-mediensteuerung-kodi-amd64:0.5.0` veröffentlichen. Existiert der Tag bereits, Inhalt nicht ersetzen. Anonymen Download und Digest prüfen. Keine weiteren Architekturen deklarieren.
5. **Vor Merge die vorhandene generische Builder-Automation auf einen Freigabeablauf umstellen, der das bereits veröffentlichte Image nicht erneut baut/überschreibt.** Aktuell würde ein geeigneter main-Push den Builder auslösen. Der Vorbereitungslauf ändert diese produktive Automation bewusst nicht. Die Umstellung separat prüfen und bestehende Apps erhalten.
6. Exakt den geprüften Stand samt config.yaml-Version im stabilen main-Katalog freigeben. Versionshinweise und Hauptübersicht aktualisieren. Nach Abruf des Katalogs prüfen, dass die App im Abschnitt Bran-doit HA Apps erscheint.
7. Optional ein unveränderliches GitHub-Release `ha-mediensteuerung-kodi-v0.5.0` mit Versionshinweisen, SHA256 und Image-Digest erstellen. Erst nach erfolgreichem Download/Installationscheck als veröffentlicht melden.

## Installationsfreigabe

Die Vorbereitung berührt die bestehende Installation nicht. Ein echter Installationstest benötigt eine getrennte Supervisor-Testinstanz oder ein ausdrücklich vereinbartes Wartungsfenster für den produktiven Server. Ein erfolgreicher Docker-Smokecheck ist kein Beleg für eine erfolgreiche HA-Installation.
