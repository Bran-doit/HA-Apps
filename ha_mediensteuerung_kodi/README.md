# HA-Mediensteuerung auf Kodi

**Entwicklungsstand für eine vorhandene AppDaemon-Installation. Kein eigenständiges Supervisor-Add-on, kein HACS-Paket und noch keine freigegebene Erstinstallation.**

Die Erweiterung verbindet deutsche Sprach- und Textbefehle mit der Kodi-Bibliothek. Sie besteht aus einer AppDaemon-Anwendung, einer Home-Assistant-Integration und einer Dashboard-Karte. Optional lässt sich Emby als Medienquelle oder Wiedergabe-Backend verwenden.

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

Benötigt werden Home Assistant, eine vorhandene AppDaemon-Umgebung mit Python ab 3.10, erreichbare Kodi-JSON-RPC-Schnittstellen und passende Bibliotheksmetadaten. Für Emby sind Serverzugang und ein eigenes Benutzerprofil erforderlich. Eine zusätzliche lokale KI ist für den Suchparser nicht nötig.

Die Einrichtung erfolgt derzeit manuell: [Installation, Konfiguration und Betrieb](DOCS.md). Vor Änderungen ein Backup erstellen. Der Ordner wird bewusst nicht als App im Supervisor-Katalog angeboten.

Beispiele: „Suche Filme mit Harrison Ford“, „Suche die neueste Staffel von Andor“, „Suche die nächste ungesehene Folge von Andor“, „Kodi spiel den ersten Film“. Raumangaben wie „im Wohnzimmer“ haben Vorrang vor der Zuordnung des Spracheingabegeräts.

## Grenzen

„Neueste“ bedeutet zuletzt zur Bibliothek hinzugefügt, nicht zuletzt veröffentlicht. Eine später ergänzte Folge kann eine ältere Staffel als zuletzt hinzugefügt kennzeichnen. Bei fehlenden Datumswerten erfolgt eine Fehlermeldung. Kodi-Dubletten werden nur bei übereinstimmenden Identitätsdaten zusammengeführt; die Datenbank selbst bleibt unverändert.

Die Konfiguration setzt bestimmte AppDaemon-Mounts voraus. Die Eingabegeräte-Zuordnung liest Home Assistants lokale Geräte-/Raumregistrierung. Emby-Funktionen hängen von Profilrechten und den Fähigkeiten der ausgewählten Clients ab. Das bereinigte Exportpaket wurde nicht auf einer frischen HA-Testinstanz installiert.

## Entwicklung, Updates und Lizenz

Offline-Prüfung: `python ha_mediensteuerung_kodi/tools/check.py` aus dem Repository-Hauptverzeichnis. Optional zusätzlich `node --check ha_mediensteuerung_kodi/homeassistant/www/ha-medien-kodi/card.js`.

Dieser Branch dient der Quellcodesicherung und Prüfung. Keine automatische Aktualisierung bestehender Installationen, kein Release, kein Container. Die vorhandene Integrationsversion 0.4.0 bleibt unverändert; der Git-Commit identifiziert diesen Entwicklungsstand.

[Änderungsverlauf](CHANGELOG.md) · [Projektregeln](AGENTS.md) · [Lizenzstatus](LICENSE.md) · [Fremdkomponenten](THIRD_PARTY.md)
