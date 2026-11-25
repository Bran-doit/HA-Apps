# Einrichtung und Betrieb

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

Bei manuellen Updates zuerst Code und diese Daten sichern. Nur Laufzeitdateien aktualisieren; `players.json`, Benutzereinstellungen und bestehende YAML-Konfiguration erhalten. Dieser Entwicklungsstand hat keinen automatischen Updatekanal und keine geprüfte Migration zu einem eigenständigen Add-on.

## Fehlerbehebung

- Konfigurationsfehler der Karte: Ressourcen-URL, geladenes JavaScript, Elementnamen und Browsercache prüfen.
- Leere Konfiguration: Existenz und Zugriffsrechte der privaten Startdatei prüfen.
- Kodi nicht erreichbar: Netzwerk, HTTP-Port, Kodi-Webserver und Zugangsdaten prüfen.
- Falscher Raum: HA-Gerätebereich, eindeutige Raumaliase und Session-/Geräteübermittlung prüfen.
- Mehrdeutiger Titel: Jahr und Titel prüfen; verschiedene Serien werden nicht allein wegen eines gleichen Namens vereinigt.
- Kein Hinzufügedatum: Bibliotheksmetadaten korrigieren. Die Suche ersetzt es nicht durch Staffel- oder Folgennummer.

Die mitgelieferten Tests prüfen Parser, Adapter und Konfigurationslogik mit Testdaten. Sie ersetzen keine Erstinstallations-, Upgrade-, Bild-/Ton- oder Geräteprüfung.
