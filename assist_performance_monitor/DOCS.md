# Installation und Betrieb

## Zweck

Die App ist der installierbare Transport für die Custom Integration. Sie
kopiert beim Start ausschließlich diese Ziele:

- `/config/custom_components/assist_performance_monitor`
- `/config/assist-performance.yaml`

Vorhandene Dateien werden vorher unter `/data/backups/<Zeitstempel>` gesichert.
Die gespeicherten Messwerte der Integration in Home Assistants `.storage`
werden nicht verändert.

## Installation

1. Das Repository `https://github.com/Bran-doit/HA-Apps` im Home-Assistant-App-
   Store hinzufügen.
2. **Assist Performance Monitor** installieren.
3. Die App einmal starten und das Protokoll auf Fehler prüfen.
4. Home Assistant manuell neu starten.
5. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** den
   **Assist Performance Monitor** einrichten.

Die App startet Home Assistant aus Sicherheitsgründen nicht selbst neu.

## Dashboard

Damit das mitgelieferte YAML-Dashboard in der Seitenleiste erscheint, muss der
folgende Eintrag mit der bestehenden `lovelace`-Konfiguration zusammengeführt
werden:

```yaml
lovelace:
  mode: storage
  dashboards:
    assist-performance:
      mode: yaml
      title: Assist Performance
      icon: mdi:chart-timeline-variant-shimmer
      show_in_sidebar: true
      require_admin: false
      filename: assist-performance.yaml
```

Vor dem Neustart die Home-Assistant-Konfiguration prüfen.

## Aktualisierung

Nach einem App-Update die App erneut starten. Sie sichert die installierte
Integration und kopiert den enthaltenen Stand nach `/config`. Anschließend ist
ein manueller Home-Assistant-Neustart erforderlich.

## Daten und Backup

- App-Sicherungen liegen persistent unter `/data/backups` und sind Bestandteil
  eines Home-Assistant-Backups der App.
- Aggregierte Messwerte bleiben in Home Assistants eigener `.storage`-Datei.
- Das Repository enthält weder lokale Konfigurationen noch Tokens, Passwörter,
  Recorder-Daten oder erkannte Sprachtexte.

## Grenzen

Die Integration nutzt intern `KEY_ASSIST_PIPELINE`, `pipeline_debug` und für
den initialen Trend-Backfill die interne Recorder-History-API. Diese
Schnittstellen sind nicht dauerhaft stabil. Die App selbst überwacht die
Integration nicht und ersetzt keine Home-Assistant-Diagnose.

Dieser Entwicklungsstand wurde noch nicht als Container für alle angegebenen
Architekturen gebaut und noch nicht aus dem öffentlichen App-Store installiert.

