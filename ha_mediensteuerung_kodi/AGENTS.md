# Mediensteuerung – Entwicklungsregeln

Zusätzlich gelten die Repository-Regeln in ../AGENTS.md und die für diesen Upload übernommenen Regeln in UPLOAD-RICHTLINIEN.md.

- Dies ist der Kandidat für eine eigenständige Supervisor-App mit AppDaemon-Laufzeit. Keine ungeprüften Architektur-/Installationsversprechen; zunächst nur amd64.
- Entwicklungsbranch: codex/ha-mediensteuerung-kodi. main ist der stabile Katalog und bleibt durch diesen Upload unverändert.
- Die bestehenden Builder-Workflows veröffentlichen bei geeigneten Änderungen auf main. Keine Workflow-Änderung, Tag- oder Release-Erstellung ohne passenden Auftrag.
- Versionsquelle ist config.yaml (0.5.0). Integrationsmanifest muss übereinstimmen. RELEASE.md beschreibt die offenen Freigabeschritte.
- Test: python ha_mediensteuerung_kodi/tools/check.py; JavaScript: node --check ha_mediensteuerung_kodi/homeassistant/www/ha-medien-kodi/card.js.
- Keine Live-Konfigurationen, Schlüssel, Token, private Geräte-IDs, reale IP-Adressen, Diagnoseberichte, Cover oder Hilfsprogramme mit Live-Aufrufen hochladen.
- Live-Installation, Neustart und Migration sind getrennte Aufträge. Keine automatische Medienwiedergabe beim Testen.
- MIT-Lizenz ist freigegeben. Vor Release reproduzierbare Erstinstallation und Upgrade auf einer Supervisor-Testinstanz prüfen.
- medien-prepare.yaml baut/prueft bei Entwicklungsbranch-Push, ohne Registry-Push oder Release. Die generische main-Veröffentlichung muss vor Freigabe an unveränderliche vorab getestete Images angepasst werden.
