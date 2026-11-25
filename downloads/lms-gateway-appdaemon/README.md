# LMS Gateway AppDaemon

Version 1.0.0 des Wiederherstellungspakets.

[ZIP herunterladen](LMS-Gateway-AppDaemon-1.0.0.zip) · [SHA-256](LMS-Gateway-AppDaemon-1.0.0.zip.sha256) · [Änderungsverlauf](CHANGELOG.md)

Das ZIP enthält den Gateway-Code, das Home-Assistant-Sprachpaket, Audio-Blueprints, eine Dashboard-Vorlage und den PowerShell-Installer. Die Anleitung steht im ZIP unter `WIEDERHERSTELLUNG.md`.

Vorausgesetzt werden ein gestartetes AppDaemon-Add-on, ein erreichbarer Lyrion Music Server sowie Schreibzugriff auf die Home-Assistant-Freigaben. Nach dem Entpacken zuerst `./install_appdaemon_port.ps1 -CheckOnly` ausführen. Persönliche Einstellungen können separat aus einem privaten Backup übernommen werden.

Die Installation erfolgt per PowerShell. Dieses Archiv erscheint nicht als App im Supervisor-Store.
