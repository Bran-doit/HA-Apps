# Bran-doit HA Apps

Repository für Home-Assistant-Apps (früher Add-ons). Jede App erhält eine eigene Beschreibung, Konfiguration, Versionsnummer und Änderungshistorie.

[![Repository zu Home Assistant hinzufügen](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FBran-doit%2FHA-Apps)

## Verfuegbare Apps

- **Shopping Sync** - synchronisiert Home-Assistant-Todo-Listen mit einer mobilen Shopping-App ueber Firebase und bietet eine Ingress-Konfigurationsseite.

## In Home Assistant einbinden

Voraussetzung: Home Assistant mit Supervisor/App-Store, regulär Home Assistant OS. Eine reine Home-Assistant-Container-Installation bietet diesen Store nicht.

Unter **Einstellungen → Apps → App installieren → Menü ⋮ → Repositories** folgende Adresse hinzufügen (ältere Oberflächen nennen den Bereich Add-ons / Add-on-Store):

```text
https://github.com/Bran-doit/HA-Apps
```

Alternativ den Hinzufuegen-Link oben verwenden. Jede App wird einzeln angeboten; die Repository-Adresse bleibt gleich.

## Installation und Updates

Nach Veröffentlichung eine App im Store auswählen, die Voraussetzungen und Dokumentation lesen und installieren. Konfiguration und Start erfolgen anschließend in Home Assistant. Neue Versionen werden anhand der jeweiligen App-Konfiguration erkannt; automatische Updates werden pro App in Home Assistant eingestellt.

Ein GitHub-Release allein installiert nichts. Bestehende Installationen aus anderen Repositories werden nicht automatisch übernommen: Repository-Adresse und App-Slug beeinflussen die Identität. Vor einem Umzug müssen Backup und Datenmigration geprüft werden.

## Entwicklung

Entwicklung erfolgt auf `codex/<thema>`, stabile Versionen auf `main`. Jede Anwendung erhält einen eigenen Ordner direkt im Repository, beispielsweise `meine_app/`. Es werden keine funktionslosen Beispiel-Apps im Store veröffentlicht.

Siehe [Arbeitsanweisungen](AGENTS.md) und [Veröffentlichungsablauf](CONTRIBUTING.md).

## Referenzen

[Repository-Struktur](https://contributors.home-assistant.io/apps/guides/repository/) · [Veröffentlichung](https://contributors.home-assistant.io/apps/guides/publishing/)

## Entwicklungsstände auf diesem Branch

- [Arcaden Games: Pac-Man und Pong](arcaden_games/README.md) – Quellsicherung, noch nicht stabil freigegeben. [Änderungen](arcaden_games/CHANGELOG.md).
