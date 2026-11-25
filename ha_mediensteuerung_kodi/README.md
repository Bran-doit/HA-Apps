# HA-Mediensteuerung auf Kodi

**Veröffentlichungskandidat 0.5.0 für eine eigenständige Home-Assistant-App (amd64). Noch nicht im stabilen App-Katalog freigegeben.**

Die Erweiterung verbindet deutsche Sprach- und Textbefehle mit der Kodi-Bibliothek. Der Container enthält eine eigene AppDaemon-Laufzeit, eine Home-Assistant-Integration und die Dashboard-Karte. Optional lässt sich Emby als Medienquelle oder Wiedergabe-Backend verwenden.

## Funktionen

- Film-, Serien- und Episodensuche, auch nach Genre, Schauspieler, Jahr, Laufzeit und Gesehen-Status.
- Suche nach zuletzt hinzugefügten Folgen und Staffeln anhand des Bibliotheksdatums.
- Auswahl bei mehreren Treffern; bereits laufende Wiedergabe lässt sich optional ersetzen.
- Mehrere Kodi-Player mit Raumaliasen; automatische Raumzuordnung über das Assist-Eingabegerät.
- Dashboard mit Status, Textbefehl-Test, Interpretation, Konfiguration und Befehlsbeispielen.
- Geeignete Film-/Serienlisten lassen sich über Kodi anzeigen; Episodenlisten verwenden das Dashboard.
- Optionaler Kodi-App-Start über konfigurierte Android-TV-Remote-/Sony-Steuerung.
- Identitätsprüfung bei Emby/Kodi-Zuordnungen und Bereinigung nachweislicher Seriendubletten in Suchergebnissen.

## Voraussetzungen und Einrichtung

Benötigt werden Home Assistant, ein amd64-System mit Supervisor, erreichbare Kodi-JSON-RPC-Schnittstellen und passende Bibliotheksmetadaten. Für Emby sind Serverzugang und ein eigenes Benutzerprofil erforderlich. Eine zusätzliche lokale KI ist für den Suchparser nicht nötig.

Der Einrichtungsmodus installiert die HA-Begleitdateien mit Sicherung; HA-Konfiguration und Neustart bleiben bewusste Schritte: [Installation, Konfiguration und Betrieb](DOCS.md). Vor Änderungen ein Backup erstellen. Der Ordner wird bewusst nicht als App im Supervisor-Katalog angeboten.

Beispiele: „Suche Filme mit Harrison Ford“, „Suche die neueste Staffel von Andor“, „Suche die nächste ungesehene Folge von Andor“, „Kodi spiel den ersten Film“. Raumangaben wie „im Wohnzimmer“ haben Vorrang vor der Zuordnung des Spracheingabegeräts.

## Grenzen

„Neueste“ bedeutet zuletzt zur Bibliothek hinzugefügt, nicht zuletzt veröffentlicht. Eine später ergänzte Folge kann eine ältere Staffel als zuletzt hinzugefügt kennzeichnen. Bei fehlenden Datumswerten erfolgt eine Fehlermeldung. Kodi-Dubletten werden nur bei übereinstimmenden Identitätsdaten zusammengeführt; die Datenbank selbst bleibt unverändert.

Die App benötigt Schreibzugriff auf die HA-Konfiguration sowie Lesezugriff auf App-Konfigurationen für die Umzugsprüfung. Die Eingabegeräte-Zuordnung liest Home Assistants lokale Geräte-/Raumregistrierung. Emby-Funktionen hängen von Profilrechten und den Fähigkeiten der ausgewählten Clients ab. Das bereinigte Exportpaket wurde nicht auf einer frischen HA-Testinstanz installiert.

## Entwicklung, Updates und Lizenz

Offline-Prüfung: `python ha_mediensteuerung_kodi/tools/check.py` aus dem Repository-Hauptverzeichnis. Optional zusätzlich `node --check ha_mediensteuerung_kodi/homeassistant/www/ha-medien-kodi/card.js`.

Dieser Branch enthält den installierbaren Containerkandidaten und seine Prüfungen. Eine stabile Veröffentlichung und eine echte Supervisor-Testinstallation stehen noch aus. Versionsquelle ist config.yaml (0.5.0); das Integrationsmanifest muss dazu passen. Build-Artefakte sind Testpakete, kein öffentlicher Updatekanal. [Freigabeablauf](RELEASE.md).

[Änderungsverlauf](CHANGELOG.md) · [Projektregeln](AGENTS.md) · [Lizenzstatus](LICENSE.md) · [Fremdkomponenten](THIRD_PARTY.md)
