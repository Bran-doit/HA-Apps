# HA-Apps: Entwicklung und Veröffentlichung

## Ziel und aktuelle Ausgangslage

- Öffentliches Home-Assistant-App-Repository: https://github.com/Bran-doit/HA-Apps. Apps wurden früher Add-ons genannt; dies ist kein HACS-Repository.
- Stable-/Standardbranch: main. Zentrale Metadaten: repository.yaml.
- Aktuell nur Repository-Grundstruktur, keine Apps, keine Build-/Release-Automation und kein geprüfter Live-Installationsweg. Dies nicht als fertige installierbare Software darstellen.
- Diese Datei gilt für alle Agenten/Chats im Repository. Aktuelle Nutzeranweisungen haben Vorrang. Bestehende fremde Änderungen bewahren.

## Struktur und Dokumentation

- Je App einen eigenen Ordner direkt im Repository, mit config.yaml, README.md, DOCS.md, CHANGELOG.md und passenden Lizenzhinweisen.
- README.md dient als formatierte App-Seite; DOCS.md erklärt Konfiguration, Installation, Betrieb, Daten, Backup, Fehlerbehebung und Grenzen in Home Assistant.
- Die Haupt-README ist die verlinkte Übersicht aller wirklich verfügbaren Apps und enthält die stabile Repository-Adresse.
- Dockerfile und Runtime-Dateien sowie bei Bedarf build.yaml, Übersetzungen, icon.png/logo.png und AppArmor-Konfiguration hinzufügen. Nur tatsächlich benötigte Dateien und Rechte verwenden.
- Keine ausführbaren Dummy-Apps oder falschen Architekturversprechen anlegen. Keine Zugangsdaten, privaten Konfigurationen oder Benutzerdaten hochladen.

## Entwicklung und Freigabe

- Entwicklungsstände auf codex/<thema> sichern. Öffentlich sichtbare Entwicklungsbranches sind keine Geheimhaltung.
- Nur auf ausdrücklichen Veröffentlichungsauftrag eine installierbare Version freigeben. Ein Upload zur Sicherung ist keine Release-Freigabe.
- main ist der stabile Katalog. Supervisor liest dessen config.yaml-Dateien unabhängig von GitHub Releases. Bereits ein Versionswechsel auf main kann ein Update anbieten; [skip ci] verhindert diese Erkennung NICHT.
- Vor jedem Upload vorhandene Workflows lesen; nicht davon ausgehen, dass die aktuell fehlende Automation noch fehlt.
- Reine Dokumentationspflege darf auf Nutzerauftrag ohne Versionswechsel erfolgen, sofern sie keine Container-Veröffentlichung auslöst.

## Versionen und Container

- config.yaml: version als maßgebliche Quelle mit MAJOR.MINOR.PATCH ohne führende Nullen. Jede App unabhängig versionieren.
- Für reguläre Verteilung vorzugsweise vorgebaute öffentliche GHCR-Images verwenden. Unterstützte Architekturen aus dem tatsächlichen Zielsystem und erfolgreichen Builds ableiten.
- Zuerst den freigegebenen Entwicklungscommit bauen, testen und unveränderlich mit dem Versions-Tag veröffentlichen. Alle deklarierten Architekturen und anonymen Image-Download prüfen. Erst danach exakt denselben App-Stand samt neuer config.yaml-Version auf main übernehmen.
- image enthält den passenden Image-Namen; der Supervisor zieht die zu version passende Version. Keine latest-Tags als Ersatz für versionierte Releases.
- Nie bestehende Image-Tags oder Releases mit verändertem Inhalt überschreiben. Fehlgeschlagene Builds dürfen keine nicht herunterladbare Version im stabilen Katalog hinterlassen.
- Ohne image baut der Supervisor lokal aus dem Dockerfile: diesen Weg nur bewusst vereinbaren, reproduzierbar prüfen und dokumentieren.
- Einen konkreten CI-/Release-Workflow erst mit der ersten echten App einrichten und seine Befehle hier dokumentieren. Aktuelle offizielle Builder-Anleitung verwenden, keine veralteten Build-Actions ungeprüft übernehmen.

## Prüfungen und Upgrades

- config.yaml und repository.yaml mit den aktuellen Supervisor-Vorgaben validieren; Konfigurationsschema und Standardwerte prüfen.
- Für alle ausgewiesenen Architekturen Container bauen und relevante automatisierte Tests ausführen; Start, Konfiguration, Logs und gegebenenfalls Ingress prüfen.
- Vor Freigabe Versionshinweise, App-Anleitung, DOCS und Hauptübersicht aktualisieren. Aktuelle Tests und Einschränkungen ehrlich berichten.
- Persistente Daten außerhalb flüchtiger Container-Schichten, üblicherweise /data, erhalten. Migrationen, Backup und Wiederherstellung testen und dokumentieren.
- Repository-URL und slug stabil halten. Wechsel von lokalen Apps oder fremden Repositories nicht als automatisches Upgrade darstellen; vorher die Identität, Backup- und Migrationsstrategie prüfen.
- Inkompatible Änderungen im CHANGELOG hervorheben und gegebenenfalls breaking_versions gemäß aktueller Supervisor-Spezifikation setzen.
- Veröffentlichungslauf und Downloads bis zum Ergebnis prüfen. Ohne Zugriff auf eine passende Home-Assistant-Testinstanz keine Live-Installation behaupten.
- GitHub-Veröffentlichung berechtigt nicht zur Installation, Aktualisierung oder zum Neustart eines laufenden Home Assistant. Dafür ist ein entsprechender Nutzerauftrag erforderlich.
