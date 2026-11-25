# Arcaden Games – Pac-Man und Pong
Entwicklungsfassung für Home Assistant mit Supervisor, ausschließlich Pac-Man, Pong und gemeinsame Controller-Einrichtung. Kein freigegebenes Update der lokalen 29-Spiele-Sammlung.

## Funktionen
- Pac-Man: allein, zu zweit abwechselnd oder gleichzeitig im gleichen Labyrinth; eigene Punkte und Leben, gemeinsame Superpillen-Wirkung, Tunnel, Rundensteigerung und Arcade-Klänge.
- Pong: gegen den Computer oder zu zweit.
- Gemeinsame Controllerprofile pro Browser, optionale Profile je Spiel, Pause und Spieleübersicht.
- Separate Adressen `/pacman/` und `/pong/`; mehrere Geräte spielen unabhängig.

## Installation und Bedienung
Noch nicht im stabilen App-Katalog freigegeben. Lokale Entwicklung und Voraussetzungen: [DOCS.md](DOCS.md). Nach Bereitstellung Übersicht unter `http://HOME-ASSISTANT-IP:8100/`; Steuerung unter `/settings.html`. Die Spieladressen lassen sich in einer bestehenden TV-Webseiten-Installation nutzen; diese Integration ist nicht enthalten.

Controller auf dem tatsächlichen TV-Browser einrichten. Profile und Toneinstellungen bleiben im Browser; Ingress und LAN-Adresse haben getrennte Speicherbereiche. Website-Daten löschen entfernt Einstellungen, HTTP-Cache umgehen nicht.

## Grenzen
Der zusätzliche Dialog direkt nach der Mehrspieler-Auswahl ist noch offen; der Modus wird bisher unter Pac-Man/Einstellungen gewählt. Container-Builds für die geerbten Architekturangaben, Home-Assistant-Testinstallation und Migration sind für diese reduzierte Fassung nicht geprüft. Diese Fassung nicht über die vollständige Sammlung installieren.

[Änderungen](CHANGELOG.md) · [Betrieb](DOCS.md) · [Lizenz](LICENSE.md)
