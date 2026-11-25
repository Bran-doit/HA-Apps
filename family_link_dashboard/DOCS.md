# Installation, Betrieb und Grenzen

## Voraussetzungen

Eine separat eingerichtete [noiwid/HAFamilyLink](https://github.com/noiwid/HAFamilyLink)-Integration mit gerätebezogenem Tagesnutzungssensor (`attributes.apps`: `package`, `name`, `minutes`) und vier App-Listensensoren. Ausgangsentwicklung mit Version 2.2.6; beim Export war auf dem Quellsystem 2.9.2 installiert. Daraus folgt keine vollständige Kompatibilitätszusage für alle Versionen.

AppDaemon mit HASS-Plugin und Python mit `zoneinfo`; vorhandene Home-Assistant-Verbindung verwenden. Diese Erweiterung benötigt weder einen eigenen Google-Login noch einen neuen Token im Browser. HAFamilyLink nutzt eine inoffizielle Google-Schnittstelle und kann bei Änderungen ausfallen.

## 1. Archivierung einrichten

`appdaemon/fl_usage_archive.py` in das bestehende AppDaemon-Apps-Verzeichnis kopieren. `examples/apps.yaml` in die eigene AppDaemon-Konfiguration übernehmen. Quelle, Ziel, Zeitzone und persistenten Archivpfad anpassen. Nicht eine vorhandene `apps.yaml` überschreiben. Das Archivverzeichnis muss vom AppDaemon-Prozess beschreibbar und persistent sein.

Das Skript reagiert auf Quelländerungen und prüft zusätzlich alle fünf Minuten. Es schreibt atomar eine JSON-Datei und veröffentlicht `sensor.child_tablet_usage_history`. Es verändert keine Family-Link-Sperren oder Limits. Kein automatischer Neustart oder Live-Installer ist enthalten.

## 2. Karte installieren

`frontend/usage-card.js` nach `/config/www/family-link/usage-card.js` kopieren. Vorher die generischen Bezeichner anpassen:

- `FL_SOURCE`: gerätebezogener Tagesnutzungssensor.
- `FL_BASE`: gemeinsames Präfix der vier App-Listensensoren.
- `sensor.child_tablet_usage_history`: an beiden Stellen auf den gewählten Archiv-Zielsensor ändern.
- `FL_KEY`: für mehrere Tablets pro Tablet einen eigenen Browser-Speicherschlüssel vergeben.
- `/family-link/apps`: anpassen, falls der Dashboard-Pfad anders lautet.

Home Assistant: Einstellungen → Dashboards → Ressourcen, als JavaScript-Modul `/local/family-link/usage-card.js?v=1` eintragen. Nach Updates Versionsparameter erhöhen und Browser neu laden. Die Datei enthält nur Darstellungscode, keine privaten Zugangsdaten.

## 3. Dashboard

`examples/dashboard.yaml` in ein neues Dashboard übernehmen oder dessen Karten in vorhandene Ansichten einfügen. Die Beispieldatei enthält Nutzung und App-Auswahl. Bereits vorhandene Wochenpläne und Schalter müssen nicht ersetzt werden. Die Erweiterung wird nicht über den Supervisor-App-Katalog installiert.

Rot zeigt die von HAFamilyLink gemeldete Tablet-Nutzung; Schwarz ANTON (`com.solocode.anton`). Die Farben weiterer Apps werden deterministisch vergeben und können sich bei vielen Apps wiederholen. Auswahlhäkchen ändern nur das Diagramm, keine Freigaben. Die Auswahl gilt pro Browser/Origin, nicht global für alle Geräte.

Maximieren: Schaltfläche rechts oben. Schließen: × oder Escape. Maus zeigt Tageswerte; Antippen fixiert die Auswahl. Pfeiltasten sowie Home/End wählen einen Tag. Escape am Diagramm löst die Markierung. Es wird ein Tageshöchststand angezeigt, kein interpolierter Messwert zu einer Uhrzeit.

## Daten, Sicherung und Wiederherstellung

Im Archiv stehen Datum, Nutzungsminuten, App-Namen und Paketnamen. Diese Daten bleiben in der eigenen Installation. Archivdatei und AppDaemon-Konfiguration in das persönliche Backup aufnehmen, **nicht** in Git committen. Zur Wiederherstellung bei gestopptem Archivskript die Datei an denselben persistenten Pfad zurückspielen und das Skript wieder laden. Vorhandene JSON-Dateien werden übernommen, es gibt keine Migration des Formats in dieser Erstfassung.

Maximal 90 erfasste Tage bleiben gespeichert (keine Garantie von exakt 90 Kalendertagen). Ältere Kalendertage ohne Messungen fehlen. HA-Recorder-Verlauf wird ergänzend abgefragt, ist aber nicht Voraussetzung für neue Archivdaten. Bei Neustart wird das Archiv eingelesen; der Sensor wird mit dem nächsten gültigen Quellzustand veröffentlicht.

## Fehlerbehebung und Grenzen

- Leere Karte: Entitätsnamen, JavaScript-Ressource und Browserkonsole prüfen.
- Kein Archivsensor: AppDaemon-Log, Importpfad, HASS-Plugin und Schreibrechte prüfen.
- Lücken: Quelle liefert keine Daten oder wurde erst kürzlich eingerichtet; keine künstlichen Nullen ergänzen.
- Ungültige Archivdatei: sichern und JSON reparieren bzw. ein persönliches Backup wiederherstellen; keine automatische Löschung.
- App-Listen beruhen auf den Angaben der Integration. Systemkomponenten werden anhand von Paketnamen gefiltert; das ist keine sichere System-App-Erkennung.
- Tageshöchststände werden monoton gesammelt. Nachträgliche Abwärtskorrekturen des Google-Zählers werden nicht übernommen. Zuordnung erfolgt nach dem Zeitstempel des HA-Quellzustands; verspätete Google-Daten um Mitternacht können ungenau sein.
- Eine leere vollständige App-Liste wird als null App-Minuten interpretiert; gekürzte Listen werden als unvollständig behandelt. Maßgeblich ist die Qualität der gelieferten Quelldaten.
- Die AppDaemon-Entität ist ein veröffentlichter Zustand, kein separat registriertes Gerät. Die Archivattribute können bei sehr vielen Apps groß werden.

## Validierung

`python -m unittest discover -s family_link_dashboard/tests` und `node --check family_link_dashboard/frontend/usage-card.js` aus dem Repository-Verzeichnis. Keine Container-Builds oder Live-Neuinstallation für dieses Paket behauptet.
