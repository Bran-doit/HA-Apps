# Entwicklung, Betrieb und Migration
## Voraussetzungen und Tests
Python 3.13+, Node.js für Syntaxprüfung, Browser mit Canvas/Web Audio und optional Gamepad-API. Docker lädt das Python-Basisimage; die Spiele brauchen danach keine externen Dienste.

`python arcaden_games/tests/check.py` prüft Syntax, Ressourcen und HTTP. `python arcaden_games/server.py` startet Port 8100, über PORT änderbar.

## Daten und Sicherheit
Keine HA-Zugangsdaten oder Supervisor-API-Berechtigung erforderlich. Statischer Server mit Versionsendpunkt. Profile, Ton und Spielstände liegen browserseitig, nicht unter /data; HA-Backups enthalten diese Browserdaten nicht. LAN-Port nur im vertrauenswürdigen Heimnetz verwenden.

## Updates
config.yaml/version ist die Quelle. Quellversion 1.10.2 wurde als Entwicklungsstand übernommen, ohne Release. Vor Freigabe Lizenzentscheidung, Container-Builds aller deklarierten Architekturen, Start/Ingress, Testinstallation und Backup-/Migrationsstrategie prüfen. Eine Repository-App hat gegenüber der lokalen App eine andere HA-Identität. Gleicher Slug allein ist keine Migration. Die vollständige Sammlung darf nicht durch diese Zwei-Spiele-Fassung ersetzt werden. Kein Live-System wurde verändert.

## Fehlersuche
Die Übersicht liest die Paketversion vom Server. Ein altes Containerimage bleibt trotz Cache-Leerung alt. Antworten setzen no-store. Für Ton zuerst eine Taste drücken; Steuerung auf dem tatsächlichen TV-Gerät einrichten.
