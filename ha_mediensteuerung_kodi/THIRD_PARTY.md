# Plattformen und Fremdkomponenten

Dieses Verzeichnis enthält Projektcode und Testdaten; keine kopierten Plattform-Runtimes, Medien-Cover oder Bibliotheksdaten.

Zur Laufzeit werden die vorhandenen Installationen von Home Assistant, AppDaemon, Kodi und optional Emby genutzt. Die Python-Integration verwendet dort bereitgestellte Bibliotheken wie aiohttp und voluptuous. Diese Projekte unterliegen ihren eigenen Lizenzbedingungen. Es werden keine Rechte an deren Marken, Code oder Medieninhalten beansprucht. Für ein späteres eigenständiges Containerpaket müssen Abhängigkeiten und Lizenztexte separat inventarisiert werden.

Container 0.5.0: Python 3.12 (Python-Lizenz) und Debian-Basis mit unveränderten enthaltenen Lizenzhinweisen; AppDaemon 4.5.16 (Apache-2.0) sowie Abhängigkeiten gemäß requirements.txt. Python-Wheels einschließlich ihrer dist-info-Lizenzdateien werden unverändert installiert. Der Build fixiert Pakete und SHA256-Werte. Die konkrete Abhängigkeitsliste ist Teil des Quellpakets.
