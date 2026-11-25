# Eine App hinzufügen und veröffentlichen

## Benötigte Angaben

Vor dem ersten App-Import: Quellprojekt, Zweck, Home-Assistant-Installation und Prozessorarchitektur feststellen. Bestehende Konfiguration und Speicherorte prüfen, wenn eine bereits installierte Anwendung übernommen werden soll.

## Geplante Struktur je App

```text
HA-Apps/
├── repository.yaml
├── README.md
├── AGENTS.md
└── meine_app/
    ├── config.yaml
    ├── Dockerfile
    ├── README.md
    ├── DOCS.md
    ├── CHANGELOG.md
    └── LICENSE
```

Dies ist eine Strukturvorlage, keine bereits enthaltene Anwendung. Weitere Dateien hängen von der konkreten App ab. README beschreibt die App; DOCS erklärt Bedienung und Optionen. In config.yaml stehen unter anderem Name, Slug, Version, Beschreibung und unterstützte Architekturen sowie gegebenenfalls das veröffentlichte Image.

## Freigabeablauf

1. Änderungen auf einem Entwicklungsbranch vorbereiten.
2. Version, Dokumentation und Änderungsverlauf aktualisieren; Konfiguration und Verhalten testen.
3. Nach Veröffentlichungsauftrag Images für alle zugesagten Architekturen aus dem geprüften Stand bauen und unter neuen unveränderlichen Tags bereitstellen.
4. Image-Verfügbarkeit ohne Anmeldung und die Installation/Upgrade-Fähigkeit prüfen.
5. Erst danach den zugehörigen stabilen App-Stand auf main übernehmen. Supervisor kann die neue Version dann erkennen.
6. Release-Hinweise veröffentlichen und den tatsächlich erreichten Prüfstand dokumentieren.

Die Build-Automation wird mit der ersten echten App eingerichtet. Derzeit gibt es keine automatische Container-Veröffentlichung. Eine höhere Version im stabilen config.yaml darf nicht auf ein noch fehlendes Image verweisen.

[Offizielle App-Konfiguration](https://contributors.home-assistant.io/apps/reference/configuration/) · [Offizielle Veröffentlichung](https://contributors.home-assistant.io/apps/guides/publishing/)
