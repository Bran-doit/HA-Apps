# Mediensteuerung – Entwicklungsregeln

Zusätzlich gelten die Repository-Regeln in ../AGENTS.md und die für diesen Upload übernommenen Regeln in UPLOAD-RICHTLINIEN.md.

- Dies ist eine AppDaemon-/HA-Integration, kein Supervisor-Add-on. Kein Dummy-config.yaml und keine ungeprüften Architektur-/Installationsversprechen hinzufügen.
- Entwicklungsbranch: codex/ha-mediensteuerung-kodi. main ist der stabile Katalog und bleibt durch diesen Upload unverändert.
- Die bestehenden Builder-Workflows veröffentlichen bei geeigneten Änderungen auf main. Keine Workflow-Änderung, Tag- oder Release-Erstellung ohne passenden Auftrag.
- Die Integrationsversion steht in homeassistant/custom_components/ha_medien_kodi/manifest.json; aktuell 0.4.0. Der Git-Commit identifiziert diesen unveröffentlichten Export.
- Test: python ha_mediensteuerung_kodi/tools/check.py; JavaScript: node --check ha_mediensteuerung_kodi/homeassistant/www/ha-medien-kodi/card.js.
- Keine Live-Konfigurationen, Schlüssel, Token, private Geräte-IDs, reale IP-Adressen, Diagnoseberichte, Cover oder Hilfsprogramme mit Live-Aufrufen hochladen.
- Live-Installation, Neustart und Migration sind getrennte Aufträge. Keine automatische Medienwiedergabe beim Testen.
- Vor einem Release Lizenz, reproduzierbare Erstinstallation und Upgrade auf einer Testinstanz klären und prüfen. Der Lizenzstatus ist in LICENSE.md dokumentiert.
