# Family Link Dashboard und Nutzungsverlauf

Entwicklungsstand für eine **manuell installierte Lovelace-/AppDaemon-Erweiterung**, keine im Supervisor installierbare App. Es gibt weder Container-Image noch Architektur- oder Release-Zusage. Daher enthält dieser Ordner bewusst kein Supervisor-`config.yaml` und keinen Dummy-Dockerfile.

## Funktionen

- Sieben Tageswerte als Linien: Tablet gesamt rot, ANTON schwarz, weitere Apps mit stabilen Farben.
- Auswahlhäkchen in vier App-Listen: Tageslimits, unbegrenzte Zeit, gesperrte Apps und Apps ohne eigenes Limit.
- Browserlokale Auswahl, maximierte Ansicht, gemeinsame Werteanzeige per Maus, Touch und Tastatur.
- AppDaemon archiviert Tageshöchststände und App-Minuten; maximal 90 erfasste Tage, die letzten sieben gespeicherten Tage werden als Sensorattribute bereitgestellt.
- Fehlende Werte bleiben Lücken. Kein minutengenauer Verlauf, keine nachträgliche Rekonstruktion fehlender Tage.

## Ausdrückliche Herkunft und Drittanbieter

**Die zugrunde liegende Google-Family-Link-Anbindung stammt von [noiwid/HAFamilyLink](https://github.com/noiwid/HAFamilyLink), nicht von diesem Projekt.** Dessen Python-Integration, insbesondere `custom_components/familylink/sensor.py`, liefert die verwendeten App-Listen und Nutzungswerte. Das Dashboard-Konzept wurde durch die [Dashboard-Beispiele des Autors](https://github.com/noiwid/HAFamilyLink/tree/main/examples) einschließlich der Weekly Limits Card angeregt. Die hier enthaltene Karte und Archivierung sind eine separate Ergänzung; die fremde Integration und ihr Anmeldedienst werden nicht mitgeliefert.

Das Archivskript setzt [AppDaemon](https://github.com/AppDaemon/appdaemon) und dessen `hassapi` voraus; die Oberfläche verwendet [Home Assistant](https://github.com/home-assistant/core) und Lovelace. Weitere Herkunfts- und Lizenzhinweise: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Installation und Prüfstand

Siehe [DOCS.md](DOCS.md). Alle Beispiel-Entitäten müssen zur eigenen Installation passen. Es werden keine Google-Cookies, Token, privaten Konfigurationen, Screenshots oder Nutzungsarchive veröffentlicht.

Die Ausgangsversion wurde auf einer bestehenden Home-Assistant-/AppDaemon-Installation eingesetzt. Die anonymisierte Veröffentlichung ist kein getestetes Supervisor-Paket. Prüfungen für diesen Entwicklungsstand stehen unter `tests/`; es werden ausschließlich künstliche Daten verwendet.
