# Änderungen

## Unveröffentlicht – Quellcodeexport vom 2026-11-25

- AppDaemon-Anwendung, Home-Assistant-Integration, Dashboard und Satz-Automation zusammengeführt.
- Film-/Seriensuche, Metadatenfilter, Auswahlantworten und mehrere Kodi-Ziele enthalten.
- „Neueste Folge/Staffel“ verwendet Hinzufügedaten; Gesehen-Status und Veröffentlichungsdatum sind davon getrennt.
- Eingangssprachgerät kann den Kodi im selben HA-Raum auswählen.
- Identische Serien- und Episodendubletten werden bei der Suche anhand nachgewiesener Identität behandelt.
- Tests auf die Exportstruktur angepasst; keine privaten Konfigurationen, Laufberichte, Test-Helfer oder Medienbilder aufgenommen.
- Privates Beispielnetz im Dashboard durch eine Dokumentationsadresse ersetzt.

Keine neue Release-Version, keine Container-Veröffentlichung und keine Änderung einer Live-Installation. Integrationsmanifest weiterhin 0.4.0. Historische interne Versionsstände sind keine öffentlich angebotenen Releases.

Prüfung des Exports: 175 Offline-Tests erfolgreich (Python 3.14.7), Python-/JSON-Syntax und JavaScript-Syntax geprüft. Kein Erstinstallations- oder Upgrade-Test und keine Live-Änderung im Rahmen dieses Uploads.
