# Installation und Wiederherstellung

## Store-App im Entwicklungsstand

Die App enthält eine eigene AppDaemon-Laufzeit. Ihre Verwaltungsseite öffnet sich über „Weboberfläche öffnen“ in Home Assistant. Die App speichert ihre Laufzeitkonfiguration und Gesprächsdaten unter `/data/ki_kindersicherung`.

Für einen Test auf einer separaten Home-Assistant-Instanz sind die Dateien unter `source/home_assistant` weiterhin erforderlich. Dazu die Paketdatei unter `packages/ki_kindersicherung.yaml` und die Sprachsätze unter `custom_sentences/de/ki_kindersicherung.yaml` ablegen. Die Paketeinbindung ist unten beschrieben. Die Store-App verwendet für ihre Verwaltung Ingress, daher entfällt das manuelle Lovelace-iframe.

Vor einem späteren Umstieg die bisherige Laufzeitkonfiguration sichern. Beide AppDaemon-Instanzen dürfen die Kindersicherung wegen gleicher Events und Entitäten nicht gleichzeitig ausführen. Eine Übernahme der bisherigen Daten ist Teil der noch ausstehenden Live-Prüfung. Die direkte TV-Ausgabe ist in diesem Teststand deaktiviert. Der Browserzugriff über Ingress und die reguläre Sprachausgabe über Home Assistant sind die vorgesehenen Testpfade.

## Manuelle Installation mit bestehendem AppDaemon

Voraussetzungen sind Home Assistant, AppDaemon mit verbundenem HASS-Plugin und aktiviertem HTTP-Dienst, ein unterstützter Konversationsagent und eine TTS-Entität. Der Installer benötigt PowerShell und Schreibzugriff auf beide Konfigurationsordner. Die AppDaemon-Konfiguration muss im Add-on unter `/config` eingebunden sein.

1. Home Assistant und AppDaemon sichern. Bei einer bestehenden Installation die alte AppDaemon-Registrierung nach der Sicherung entfernen, wenn sie in einer anderen YAML-Datei steht.
2. Den Repository-Stand herunterladen und aus diesem Verzeichnis installieren. Die Beispieladressen durch die vom Browser erreichbaren Adressen ersetzen.

   ```powershell
   .\Install-KI-Kindersicherung.ps1 -ConfigRoot '\\homeassistant\config' `
     -AppDaemonRoot '\\homeassistant\addon_configs\a0d7b954_appdaemon' `
     -AppDaemonUrl 'http://homeassistant.local:5050' `
     -HomeAssistantUrl 'http://homeassistant.local:8123'
   ```

3. In der vorhandenen `configuration.yaml` die folgenden Einträge mit den bestehenden Abschnitten zusammenführen. Bei einem anderen Paketverzeichnis die installierte Paketdatei dorthin verschieben.

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   lovelace:
     dashboards:
       ki-kindersicherung:
         mode: yaml
         title: Kindersicherung
         icon: mdi:shield-account
         show_in_sidebar: true
         require_admin: true
         filename: ki_kindersicherung_dashboard.yaml
   ```

4. Die Home-Assistant-Konfiguration prüfen und Home Assistant sowie AppDaemon neu starten. Im Dashboard Konversationsagent, TTS, Sprachgerät und Mediengeräte einstellen. Erst danach die Kindersicherung aktivieren und zunächst mit dem Dummy-Player testen.
5. Für Sprachbefehle eine deutsche Assist-Pipeline verwenden. Falls ein externer Konversationsagent die Skripte aufrufen soll, die Kindersicherungs-Sprachbefehle für Assist freigeben.

## Betrieb und Daten

Die optionale TV-Ausgabe setzt die getrennt installierten Skripte `script.tv_display_anzeigen` und `script.tv_display_beenden` voraus. TV-Audio benötigt außerdem Zugriff auf den Home-Assistant-TTS-Dienst. AppDaemon und seine Verwaltungsendpunkte nur im vertrauenswürdigen lokalen Netz betreiben. Bei HTTPS für Home Assistant muss auch die eingebettete AppDaemon-Seite über HTTPS erreichbar sein.

Der Installer erhält eine vorhandene Laufzeitkonfiguration und sichert überschriebene Zieldateien unter `backups/`. Für eine vollständige persönliche Wiederherstellung zusätzlich den AppDaemon-Ordner `ki_kindersicherung/` privat sichern. Er kann Gesprächsverläufe und lokale Einstellungen enthalten. Bei unverändertem Dashboard-Menü prüfen, ob noch ein altes Storage-Dashboard dieselbe URL belegt. Bei fehlender Sprache die AppDaemon-Logs und die konfigurierten TTS- und Agent-Entitäten prüfen.
