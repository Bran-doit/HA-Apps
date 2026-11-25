# Repository-App: Einrichtung, Umzug und Wiederherstellung

## Status und vorgesehener Installationsweg

Version 0.5.0 ist ein Kandidat auf dem Entwicklungsbranch. Erst nach erfolgreicher Container- und Supervisor-Prüfung und Veröffentlichung des Images wird der App-Eintrag auf main freigegeben. Vorher funktioniert der stabile Hinzufügen-Link noch nicht für diese App. Die folgenden Schritte beschreiben den vorgesehenen Ablauf nach Freigabe.

1. Repository `https://github.com/Bran-doit/HA-Apps` im Home-Assistant-App-Store hinzufügen.
2. Unter **Bran-doit HA Apps** die **HA-Mediensteuerung auf Kodi** installieren (zunächst nur amd64).
3. Ein vollständiges HA-Backup inklusive alter AppDaemon-Konfiguration und HA-Konfiguration anlegen.
4. App zunächst mit `mode: setup` starten. Sie schreibt nur die mitgelieferten Projektdateien und eine leere Player-Konfiguration, falls noch keine vorhanden ist. Eine bestehende players.json wird nie ersetzt. Dateien, die gegenüber dem zuletzt installierten Stand geändert wurden, werden zunächst abgewiesen.
5. Bei bewusstem Umzug vorhandener Projektdateien `replace_existing_files: true` aktivieren und setup erneut ausführen. Vorher das Backup prüfen. Die App sichert betroffene Dateien zusätzlich unter `/data/backups`. Danach diese Option wieder ausschalten.
6. Die unten beschriebenen HA-Einträge für Packages, Dashboard und JavaScript-Ressource prüfen/ergänzen. Die App verändert `configuration.yaml` nicht automatisch. Die Integration erfordert einen geplanten HA-Neustart; dieser wird nicht automatisch ausgelöst.
7. Nur den bisherigen AppDaemon-Eintrag `ha_mediensteuerung_kodi` mit `disable: true` deaktivieren; andere AppDaemon-Apps weiterlaufen lassen. Abwarten, bis AppDaemon die Änderung geladen hat. Die neue App verweigert `mode: run`, solange sie einen aktiven alten Eintrag findet.
8. `mode: run` wählen und die neue App starten. Im Dashboard Player-Konfiguration und Status prüfen, zuerst einen Text-Suchbefehl ohne Wiedergabe testen. Erst danach Sprachsteuerung und tatsächliche Wiedergabe testen.
9. Nach erfolgreicher Prüfung nach Bedarf „Beim Booten starten“ aktivieren. Der Auslieferungsstandard ist manuell.

## App-Optionen

- `mode`: `setup` installiert Begleitdateien und wartet; `run` startet die Mediensteuerung.
- `replace_existing_files`: standardmäßig false. Nur für einen bewussten, zuvor gesicherten Umzug oder zur bewussten Übernahme lokaler Dateiänderungen einschalten. Es werden ausschließlich mitgelieferte Projektdateien ersetzt, niemals players.json.
- `legacy_appdaemon_slug`: standardmäßig `a0d7b954_appdaemon`. Bei abweichender alter App den tatsächlichen Ordnernamen eintragen. Daraus werden aktive Medien-Einträge geprüft und vorhandene Wiedergabe-/Ausgabepräferenzen einmalig übernommen. Andere Apps und deren Einstellungen werden nicht verändert.

## Speicher und Backup

Die eigene Laufzeit und Einstellungen liegen unter `/data/appdaemon` und `/data/media`. Home Assistants private Player-Konfiguration bleibt unter `/config/ha_medien_kodi_private/players.json` (im Container `/homeassistant/...`). Vollständige Sicherungen müssen daher **diese App und die HA-Konfiguration** enthalten. Ein App-Backup allein enthält nicht alle Zugangsdaten. Kein privates Backup nach GitHub hochladen.

Bei Wiederinstallation nach Deinstallation zuerst die gesicherte HA-Konfiguration und die App-Daten wiederherstellen. Eine Neuinstallation ohne Backup rekonstruiert keine verlorenen Passwörter oder Player-Einstellungen. Ein bloßes Container-Update behält `/data` und die HA-Dateien.

Rollback: neue App stoppen, zusammengehörige HA-Projektdateien aus dem vollständigen Backup beziehungsweise `/data/backups/<Zeitpunkt>` anhand des dortigen Manifests zurückspielen, HA-Konfiguration prüfen und bei Integrationstausch HA neu starten. Erst dann den alten AppDaemon-Eintrag reaktivieren. Nicht beide Instanzen parallel starten. Keine alten Container mit neueren Begleitdateien mischen.

## Bestehende manuelle Struktur und HA-Konfiguration

Die folgenden Pfade und YAML-Einträge bleiben auch für die Container-App gültig. Die manuelle Kopieranleitung ist nur für Entwicklung bzw. den bisherigen AppDaemon-Betrieb; bei Verwendung der neuen App kopiert der Setup-Modus diese Dateien.


## Komponenten und Pfade

| Quelle | Ziel |
| --- | --- |
| `appdaemon/apps/ha_mediensteuerung_kodi/` | AppDaemon-Konfiguration: `apps/ha_mediensteuerung_kodi/` |
| `appdaemon/apps/apps.yaml` | Eintrag in vorhandene AppDaemon-`apps.yaml` übernehmen, nicht die Datei ersetzen |
| `homeassistant/custom_components/ha_medien_kodi/` | HA: `/config/custom_components/ha_medien_kodi/` |
| `homeassistant/packages/ha_medien_kodi.yaml` | HA: `/config/packages/ha_medien_kodi.yaml` |
| `homeassistant/dashboards/ha_medien_kodi.yaml` | HA: `/config/dashboards/ha_medien_kodi.yaml` |
| `homeassistant/www/ha-medien-kodi/card.js` | HA: `/config/www/ha-medien-kodi/card.js` |

AppDaemon benötigt Zugriff auf die HA-Konfiguration unter `/homeassistant`; seine eigene Konfiguration liegt unter `/config`. Die Pfade sind aktuell im Code festgelegt. Home Assistant und AppDaemon dürfen nicht denselben `/config`-Pfad verwechselt bekommen. Das Projekt ersetzt keine vorhandene AppDaemon-Konfiguration oder Zugangsdaten.

## Manuelle Erstkonfiguration (Entwicklungsweg)

1. Home-Assistant-Backup sowie AppDaemon-Dateien und private Medienkonfiguration sichern. Zuerst in einer Testumgebung arbeiten.
2. Die Komponenten gemäß Tabelle kopieren. Vorhandene YAML-Strukturen zusammenführen, nicht überschreiben.
3. HA-Verzeichnis `/config/ha_medien_kodi_private` anlegen. Nur wenn noch keine `players.json` existiert, mit folgendem Inhalt initialisieren und vor fremdem Zugriff schützen:

   ```json
   {"revision": 0, "default_player": "", "players": [], "backend": "kodi", "emby": {"enabled": false}}
   ```

4. Packages aktivieren, falls noch nicht vorhanden:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

5. Das YAML-Dashboard in der vorhandenen Lovelace-Konfiguration ergänzen:

   ```yaml
   lovelace:
     dashboards:
       ha-medien-kodi:
         mode: yaml
         title: Mediensteuerung
         icon: mdi:kodi
         show_in_sidebar: true
         filename: dashboards/ha_medien_kodi.yaml
   ```

6. JavaScript als Lovelace-Ressource vom Typ `module` unter `/local/ha-medien-kodi/card.js?v=16.0.2` registrieren. Bei YAML-Ressourcen unter der bestehenden `lovelace.resources`-Liste ergänzen; bei Storage-Ressourcen die Dashboard-Ressourcenverwaltung verwenden. Custom-Element-Namen nicht eigenständig umnummerieren.
7. HA-Konfiguration prüfen. Die neue Integration erfordert einen geplanten HA-Neustart; die AppDaemon-Anwendung anschließend laden. Dieses Repository führt keine dieser Aktionen automatisch aus.
8. Als HA-Administrator im Tab Konfiguration Kodi-Geräte hinzufügen oder aus HA übernehmen, Zugangsdaten eingeben und die Verbindung testen. Ein aktiviertes Gerät als Standard wählen. Raumaliase müssen eindeutig sein. Die private Konfigurationsdatei niemals nach GitHub kopieren.
9. Optional Emby-Verbindung und Profil einrichten. Kodi oder Emby als Wiedergabe-Backend wählen. Für Emby ein konkretes Wiedergabegerät auswählen; eine neue Sitzung desselben Geräts wird erneut zugeordnet.
10. Mit einem Suchbefehl und dem Dashboard-Modus „Ohne Wiedergabe“ beginnen. Eine tatsächliche Wiedergabe erst bewusst testen.

## Sprachzuordnung

Die mitgelieferte Satz-Automation übergibt `trigger.device_id` als Session an den Dienst `ha_medien_kodi.process`. Der Parser akzeptiert Medien-Codewörter wie Film, Staffel und Folge. Bestehende LMS-/KI-Automationen sind installationsabhängig und nicht Teil dieses Exports; überlappende Trigger vor Inbetriebnahme prüfen.

Expliziter Player/Raum hat Vorrang. Eine bestehende Trefferauswahl bleibt bei ihrem Ziel. Ansonsten wird der HA-Raum des Eingabegeräts mit den Kodi-Raumaliasen verglichen. Ohne Zuordnung gilt der Standardplayer; Mehrdeutigkeit oder ein deaktiviertes zugeordnetes Gerät führen zu einer Meldung. Dashboard-Textbefehle verwenden diese Mikrofonzuordnung nicht.

## Daten, Backup und Updates

Private Player- und Emby-Zugangsdaten: HA `/config/ha_medien_kodi_private/players.json`. AppDaemon schreibt Status, Verlauf und Einstellungen unter `/config/ha_mediensteuerung_kodi`. Dashboard-Vorschaubilder liegen in HA unter `/config/www/ha-medien-kodi/posters`. Diagnosen können Mediennamen, Geräteadressen und Pfade enthalten: vor Weitergabe prüfen.

Bei manuellen Updates zuerst Code und diese Daten sichern. Nur Laufzeitdateien aktualisieren; `players.json`, Benutzereinstellungen und bestehende YAML-Konfiguration erhalten. Die Container-App bringt eine getestete dateibasierte Übernahme mit; eine reale Supervisor-Installation und ein vollständiger Upgrade-/Rollback-Test sind vor stabiler Freigabe noch erforderlich.

## Fehlerbehebung

- Konfigurationsfehler der Karte: Ressourcen-URL, geladenes JavaScript, Elementnamen und Browsercache prüfen.
- Leere Konfiguration: Existenz und Zugriffsrechte der privaten Startdatei prüfen.
- Kodi nicht erreichbar: Netzwerk, HTTP-Port, Kodi-Webserver und Zugangsdaten prüfen.
- Falscher Raum: HA-Gerätebereich, eindeutige Raumaliase und Session-/Geräteübermittlung prüfen.
- Mehrdeutiger Titel: Jahr und Titel prüfen; verschiedene Serien werden nicht allein wegen eines gleichen Namens vereinigt.
- Kein Hinzufügedatum: Bibliotheksmetadaten korrigieren. Die Suche ersetzt es nicht durch Staffel- oder Folgennummer.

Die mitgelieferten Tests prüfen Parser, Adapter und Konfigurationslogik mit Testdaten. Sie ersetzen keine Erstinstallations-, Upgrade-, Bild-/Ton- oder Geräteprüfung.
