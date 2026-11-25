# Gemeinsame Entwicklungs- und Veröffentlichungsregeln

Diese Regeln gelten für alle Projekte unter E:\Codex\Projekte und alle Agenten/Chats, die in diesen Projektordnern arbeiten. Projektspezifische AGENTS.md-Dateien ergänzen diese Grundlage. Aktuelle ausdrückliche Nutzeranweisungen haben Vorrang. Diese Regeln können auf Wunsch angepasst werden.

## Entwicklung und Sicherung

- Entwicklungsstände und Veröffentlichungen klar trennen. Ein Auftrag zum Bearbeiten, Testen oder Sichern ist kein Auftrag zur Veröffentlichung.
- Zwischenstände bei autorisiertem GitHub-Upload auf einem Entwicklungsbranch sichern, standardmäßig codex/<thema>. Nicht auf einen Branch hochladen, dessen Workflow dadurch eine Veröffentlichung auslöst.
- Vor Uploads die vorhandenen Workflows und ihre Auslöser prüfen. main enthält für den vereinbarten Ablauf nur freigegebene Stände; nicht pauschal annehmen, dass jedes Projekt bereits so eingerichtet ist.
- Entwicklungsbranches eines öffentlichen Repositorys sind ebenfalls öffentlich. Geheimnisse, Zugangsdaten, lokale Einstellungen, Nutzerdaten und Diagnoseartefakte nicht veröffentlichen.
- Bei einem neuen Projekt die geltenden Regeln und die tatsächliche Veröffentlichungskonfiguration zuerst lesen. Lokale Änderungen anderer Chats oder des Nutzers erhalten.

## Veröffentlichung

- Nur auf ausdrücklichen Veröffentlichungsauftrag veröffentlichen. Ein bereits erteilter Auftrag gilt für die zugehörigen notwendigen Schritte; keine wiederholte Bestätigung verlangen.
- Vor der Veröffentlichung Umfang und Ziel prüfen, passende Tests durchführen, Anleitung und Änderungsverlauf aktualisieren und Versionsangaben konsistent setzen.
- Fertige Änderungen erst nach diesen Prüfungen auf den Veröffentlichungsbranch übernehmen beziehungsweise den vorgesehenen Release-Auslöser betätigen.
- Versionshinweise müssen Funktionen, relevante Fehlerkorrekturen, Voraussetzungen und gegebenenfalls notwendige Umstellungsschritte verständlich beschreiben. Keine nicht nachgewiesenen Testergebnisse behaupten.
- Veröffentlichungslauf bis zum Ergebnis verfolgen. Paket, Version, Download-Adresse und gegebenenfalls Update-Index prüfen. Fehler beheben oder verbleibende Hindernisse klar melden; eine Veröffentlichung erst nach erfolgreicher Prüfung als erledigt bezeichnen.
- Veröffentlichung auf GitHub und Installation auf einem laufenden Gerät/Server sind getrennte Aktionen. Ohne entsprechenden Auftrag keine Installation, kein Upgrade und keinen Neustart des laufenden Systems durchführen. Automatische Updates hängen zusätzlich von dessen Einstellungen ab.

## Versionierung

- Für veröffentlichte Versionen MAJOR.MINOR.PATCH ohne führende Nullen verwenden, beispielsweise 0.2.0, 0.2.1, 0.3.0 und 1.0.0. Projektspezifische Plattformanforderungen beachten.
- PATCH für Fehlerkorrekturen, MINOR für neue kompatible Funktionen, MAJOR für inkompatible Änderungen verwenden. Vor 1.0 inkompatible Änderungen ausdrücklich dokumentieren.
- Nicht für jeden Commit eine öffentliche Version vergeben. Git-Commits identifizieren Zwischenstände. Versionssprünge sind erlaubt, veröffentlichte Updates müssen gegenüber dem vorherigen Stand höher sein.
- Veröffentlichte Versionen, Tags und Pakete nicht nachträglich mit geändertem Inhalt überschreiben. Für Änderungen eine neue Version erstellen. Veränderliche Update-Indizes dürfen auf neue unveränderliche Pakete umgestellt werden.
- LMS: install.xml ist die Quelle für die Plugin-Version. Version in ZIP und repo.xml muss übereinstimmen. ZIP mit Versionsnummer benennen, LMS-SHA1-Prüfsumme automatisch berechnen und den Index erst aktualisieren, wenn die referenzierten Downloads verfügbar sind.
- Android: versionName als lesbare Version pflegen und versionCode für jedes zur Aktualisierung verteilte neue Build monoton erhöhen. Paketidentität und erforderliche Signaturkontinuität erhalten. Keine separate manuell gepflegte Versionsliste als konkurrierende Quelle einführen.

## Dokumentation und Automatisierung

- Pro Repository eine README mit Übersicht und Installation pflegen; pro Plugin/App eine verständliche Anleitung und einen CHANGELOG mit Versionshistorie vorsehen. Vorhandene sinnvolle Dateinamen/Formate beibehalten.
- Lizenz und bei Bedarf THIRD-PARTY-Hinweise mitführen; keine fremden Lizenzbedingungen verändern.
- Technische Veröffentlichung möglichst automatisieren: Tests, Paketbau, Prüfsummen, Release und Update-Index. Automatisierung ersetzt nicht die inhaltliche Pflege der Dokumentation und die ausdrückliche Freigabe.
- Projektspezifische AGENTS.md soll Veröffentlichungsbranch, Auslöser, Versionsquelle, Testbefehle und Veröffentlichungsziele dokumentieren. Für Arbeit in GitHub/Cloud die relevanten Regeln auch im jeweiligen Repository bereitstellen, da diese lokale übergeordnete Datei dort nicht automatisch verfügbar ist.
- Bei Widersprüchen oder Änderungsbedarf die Regeln gezielt mit dem Nutzer anpassen. Keine Veröffentlichungskonfiguration stillschweigend lockern.

## Formatierte Projekt- und Plugin-Seiten auf GitHub

- Jedes Plugin und jede App erhält im eigenen Ordner eine README.md als von GitHub gerenderte Beschreibungsseite. Die README.md im Repository-Hauptverzeichnis dient als Übersicht mit direkten Links zu den einzelnen Seiten und Änderungsverläufen.
- Plugin-Seiten beschreiben Zweck, Funktionen, Voraussetzungen, Installation, Bedienung/Einstellungen, Grenzen, Updates und Lizenz. Technische Details und APIs über passende Dokumente verlinken. Bestehende nützliche README.txt-Dateien erhalten; überlappende Angaben konsistent halten.
- Diese Seiten bei Funktionsänderungen und vor Veröffentlichungen mitpflegen. Keine nicht belegten Funktionen, Plattformen oder Testergebnisse versprechen.
- Ausdrücklich beauftragte reine Dokumentationsänderungen an GitHub-Seiten dürfen ohne Binärveröffentlichung auf dem Hauptbranch bereitgestellt werden. Vorher Auslöser prüfen und für diesen einzelnen Dokumentationscommit einen unterstützten Mechanismus zum Unterdrücken des Release-Laufs verwenden. Tests für Codeänderungen oder Veröffentlichungen niemals auf diesem Weg umgehen.
- Dokumentation im Plugin-Ordner wird gegebenenfalls ins nächste ZIP aufgenommen. Bereits veröffentlichte Pakete nicht wegen Dokumentationsänderungen überschreiben; beim nächsten Paketbau eine neue Version verwenden.

## Home-Assistant-Apps (Add-ons)

- Zielrepository für die gemeinsame App-Sammlung: https://github.com/Bran-doit/HA-Apps. Dessen AGENTS.md vor Arbeiten lesen. Nicht mit HACS-Integrationen oder LMS-Repositories verwechseln.
- repository.yaml im Hauptverzeichnis, je App ein eigener Ordner mit config.yaml, README.md, DOCS.md, CHANGELOG.md und Lizenzhinweisen. Die Hauptübersicht verlinkt die App-Seiten und den Hinzufügen-Link für Home Assistant.
- config.yaml/version ist die Versionsquelle. Entwicklungsstände auf separaten Branches halten; der stabile Branch darf nur installierbare Versionen anbieten. Supervisor erkennt Änderungen im stabilen Katalog unabhängig von einem GitHub-Release oder [skip ci].
- Bei vorgebauten Images erst alle zugesagten Architekturen bauen, testen und unter unveränderlichen Versions-Tags öffentlich bereitstellen; danach den passenden Stand samt Versionsangabe im stabilen Katalog freigeben. Keine ungetesteten Architekturen zusagen.
- Repository-Adresse und App-Slug stabil halten. Umzüge von lokalen Apps oder anderen Repositories brauchen eine geprüfte Backup-/Migrationsstrategie und sind nicht automatisch normale Updates.
- Persistente Daten und Konfiguration erhalten; Migrationen, Start und Updates prüfen. Veröffentlichung und Live-Installation getrennt autorisieren. Ohne Testinstanz keine erfolgreiche Home-Assistant-Installation behaupten.

## Thunderbird-Add-ons

### Ziel und Ablage

- Zielrepository: https://github.com/Bran-doit/TB-Addons. Vor Arbeiten dessen aktuellen Inhalt, AGENTS.md, Standardbranch und Workflows prüfen. Der initial geprüfte Standardbranch ist main; es wurde durch diese Richtlinienänderung noch keine Build- oder Update-Automation eingerichtet.
- Mehrere unabhängige Add-ons dürfen in dieser Sammlung liegen. Für neue Projekte addons/<slug>/ als Ausgangsstruktur verwenden; vorhandene sinnvolle Strukturen nicht ungefragt verschieben. Jedes Add-on erhält eigene Quellen, manifest.json, README.md, CHANGELOG.md und Lizenz-/Fremdkomponentenhinweise. Die Haupt-README verlinkt die einzelnen formatierten Add-on-Seiten und Downloads.
- Die jeweilige README beschreibt Funktionen, unterstützte Thunderbird-Versionen, erforderliche Berechtigungen, Installation, Bedienung, Einstellungen, Updateweg und bekannte Grenzen. Betriebs- oder Kontodaten, E-Mails, Adressbücher, Profile, Zugangsdaten und Testdaten mit persönlichen Inhalten nicht hochladen.
- Für reine GitHub-/Cloud-Chats die relevanten Regeln im Repository verfügbar machen: AGENTS.md als Einstieg mit verbindlichem Verweis auf eine dort vorhandene Upload-Richtlinien.md. Ein Verweis allein auf diese lokale Windows-Datei reicht dort nicht aus.

### Identität, Version und Kompatibilität

- version in manifest.json ist die maßgebliche Add-on-Version, unabhängig je Add-on. Für freigegebene Updates eine höhere MAJOR.MINOR.PATCH-Version verwenden. manifest_version bezeichnet dagegen das Erweiterungsformat und darf nicht als Release-Zähler hochgezählt werden.
- browser_specific_settings.gecko.id ist die dauerhafte Add-on-ID. Bei bestehenden Erweiterungen unverändert übernehmen; keine neue ID pro Version erzeugen. Ein ID-Wechsel ist kein normales Update und kann Einstellungen bzw. Zuordnung verlieren.
- Mindestversion über browser_specific_settings.gecko.strict_min_version passend zu verwendeten APIs festlegen. Höchstversion, sofern erforderlich (insbesondere bei Experiment-APIs), bewusst setzen. Manifest V2/V3 und verfügbare APIs anhand der tatsächlich unterstützten Thunderbird-Versionen prüfen; Firefox-Kompatibilität nicht pauschal übernehmen.
- Einstellungen und gespeicherte Daten erhalten. Falls eine Datenmigration nötig ist, alte Version und neue Version mit demselben Add-on-ID testen und Migration, Backup sowie Grenzen dokumentieren.

### Paketierung und Veröffentlichung

- Entwicklung auf codex/<thema>; Veröffentlichung nur auf ausdrücklichen Auftrag. Ein GitHub-Upload oder Merge allein darf keine unbeabsichtigte Änderung des stabilen Update-Kanals bewirken. Bestehende Auslöser vor Upload prüfen.
- Installierbares Artefakt ist je Add-on eine versionierte XPI-Datei, z. B. <slug>-1.2.3.xpi. XPI ist ein ZIP-Archiv; manifest.json liegt direkt in dessen Wurzel, nicht in einem zusätzlichen Projektordner. Alle benötigten Laufzeitdateien mitliefern, Entwicklungsreste und Geheimnisse ausschließen.
- GitHubs automatisch erzeugte Quellcode-ZIPs sind keine fertigen installierbaren Add-on-Pakete. XPI separat als Release-Datei bereitstellen. Bei mehreren Add-ons Tags/Release-Namen eindeutig halten, z. B. <slug>-v1.2.3.
- Version im Paket, Release und gegebenenfalls Update-Manifest müssen übereinstimmen. SHA256 der fertigen XPI berechnen; veröffentlichte Versionen und Dateien nicht mit geändertem Inhalt ersetzen.
- Vor Freigabe Manifest/JSON, Paketinhalt und referenzierte Dateien prüfen, passende Codeprüfungen ausführen sowie Installation, Kernfunktionen und Upgrade in einer geeigneten Thunderbird-Testumgebung testen. Keine erfolgreiche Laufzeitprüfung behaupten, wenn keine Testinstanz verfügbar ist. Signierungs- oder Store-Anforderungen von Firefox nicht ungeprüft auf Thunderbird übertragen.

### Installation und automatische Updates

- Thunderbird bindet nicht wie LMS oder Home Assistant eine allgemeine GitHub-Repository-Adresse als Add-on-Katalog ein. Die Erstinstallation einer selbst verteilten Erweiterung erfolgt über die veröffentlichte XPI und „Add-on aus Datei installieren“ in der Add-on-Verwaltung. Temporäres Laden zum Entwickeln ist keine dauerhafte Installation.
- GitHub-Releases allein bewirken keine automatischen Thunderbird-Updates. Pro Add-on den Vertriebskanal eindeutig festlegen und dokumentieren: addons.thunderbird.net (ATN), selbst gehostete Updates oder bewusst manuelle XPI-Updates. Keine parallelen konkurrierenden Updatequellen stillschweigend einrichten und keine ATN-Veröffentlichung ohne Auftrag vornehmen.
- Für selbst gehostete Updates browser_specific_settings.gecko.update_url im ausgelieferten Manifest auf eine dauerhaft erreichbare HTTPS-JSON-Updateadresse setzen. Deren Schema vor Einrichtung gegen aktuelle Thunderbird-/Gecko-Vorgaben prüfen. Ein gemeinsames updates.json kann mehrere Add-ons über ihre jeweiligen IDs im addons-Objekt führen; andere Einträge bei Updates erhalten.
- Je Update Version, direkten HTTPS-XPI-Download (update_link), SHA256 als update_hash und passende Kompatibilitätsangaben pflegen. Keine GitHub-HTML-Dateiansicht oder flüchtigen Download-Link als Updateadresse verwenden. Konkrete stabile Adresse erst nach Einrichtung und Abrufprüfung dokumentieren, nicht als bereits funktionsfähig voraussetzen.
- Zuerst die fertige XPI veröffentlichen und ohne Anmeldung herunterladen/prüfen; erst danach den stabilen Update-Index aktualisieren. Bestehende Installationen benötigen die Updateadresse bereits in ihrer installierten Version. Fehlt sie, ist gegebenenfalls eine einmalige manuelle Installation einer entsprechend vorbereiteten Version nötig; gleiche ID erhalten.
- Updateadresse stabil halten. Beim Umzug die bisherige Quelle erreichbar halten und einen getesteten Übergang planen. Ob automatisch installiert wird, hängt zusätzlich von Thunderbird-Einstellungen, Kompatibilität und gegebenenfalls erforderlicher Berechtigungsbestätigung ab.
- Veröffentlichung berechtigt nicht zum Eingriff in ein produktives Thunderbird-Profil. Installation, Neustart und Datenmigration auf dem Gerät erfordern einen entsprechenden Nutzerauftrag.

### Referenzen für spätere Bearbeitung

- Thunderbird MailExtensions und Manifest: https://developer.thunderbird.net/add-ons/mailextensions
- Thunderbird-Paketierung: https://developer.thunderbird.net/add-ons/hello-world-add-on
- Gecko-Update-Manifest (Mozilla; Thunderbird-Anwendbarkeit vor Umsetzung prüfen): https://extensionworkshop.com/documentation/manage/updating-your-extension/
