# Drittanbieter und Herkunft

## noiwid/HAFamilyLink

- Quelle: https://github.com/noiwid/HAFamilyLink
- Autoren/Maintainer: noiwid und die im Upstream-Repository genannten Mitwirkenden.
- Zugrunde liegende Python-Skripte: `custom_components/familylink/`, insbesondere `sensor.py`; der separate Auth-Dienst gehört zum Upstream-Projekt.
- Dashboard-Referenzen: `examples/lovelace-dashboard.yaml` und `examples/weekly-limits-card.yaml`.
- Lizenz und Copyright des Upstreams: https://github.com/noiwid/HAFamilyLink/blob/main/LICENSE

**Die Family-Link-Schnittstelle und deren Datenbeschaffung sind ausdrücklich Leistungen dieses Drittprojekts.** Diese Veröffentlichung beansprucht daran keine Urheberschaft. Die Upstream-Dateien werden nicht gebündelt; sie sind separat nach deren Anleitung und Lizenz zu installieren. Der Upstream nennt seinerseits die Vorarbeiten von tducret/familylink und Vortitron/HAFamilyLink; diese werden hier nicht als eigene Arbeiten dargestellt.

## AppDaemon

https://github.com/AppDaemon/appdaemon — externe Laufzeit und HASS-Plugin (`appdaemon.plugins.hass.hassapi`). Deren APIs werden importiert, nicht mitgeliefert. Lizenz: https://github.com/AppDaemon/appdaemon/blob/dev/LICENSE.md

## Home Assistant

https://github.com/home-assistant/core und https://github.com/home-assistant/frontend — externe Plattform, Zustände, History-API und Lovelace. Lizenzhinweise im jeweiligen Repository. Keine Home-Assistant-Quelldateien werden gebündelt.

## Abgrenzung

`frontend/usage-card.js` und `appdaemon/fl_usage_archive.py` sind die in diesem Projekt entstandenen Ergänzungen. Sie nutzen die vorgenannten Drittkomponenten. Keine Verbindung zu oder Unterstützung durch Google, ANTON oder Mojang wird behauptet. App-Namen und Paketnamen dienen ausschließlich der technischen Zuordnung.
