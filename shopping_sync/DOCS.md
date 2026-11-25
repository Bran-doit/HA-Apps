# Installation und Einrichtung

## Installation

1. In Home Assistant **Einstellungen > Apps > App-Store > Repositories** oeffnen.
2. `https://github.com/Bran-doit/HA-Apps` als Repository hinzufuegen.
3. **Shopping Sync** installieren.
4. Vor dem ersten Start die Firebase-Angaben unter **Konfiguration** eintragen.
5. App starten und **In Seitenleiste anzeigen** aktivieren.

## Erforderliche Angaben

- `firebase_api_key`: API-Schluessel der vom Originaltool verwendeten Firebase-Anwendung
- `firebase_email`: Konto-E-Mail der mobilen Shopping-App
- `firebase_password`: Konto-Passwort der mobilen Shopping-App
- `firebase_database_url`: URL der Firebase Realtime Database
- `firebase_project_id` und `firebase_app_id`: optionale Firebase-Projektwerte

Das Home-Assistant-Zugriffstoken wird vom Supervisor bereitgestellt und muss nicht manuell erzeugt werden.

## Listen

Ohne Eintraege in `lists` werden alle von Firebase gemeldeten Listen beruecksichtigt, fuer die eine gleichnamige Todo-Entitaet in Home Assistant existiert. Alternativ lassen sich bestimmte Listennamen vorgeben. Weitere Zuordnungen koennen spaeter auf der Konfigurationsseite verwaltet werden.

## Datensicherung

Konfiguration und Laufzeitdaten liegen im persistenten App-Datenverzeichnis `/data` und werden in Home-Assistant-Sicherungen einbezogen. Zugangsdaten stehen dort im Klartext, weil die Firebase-Anmeldung sie zur Laufzeit benoetigt. Sicherungen sind entsprechend zu schuetzen.

## Migration einer bestehenden Installation

Die App importiert aus Sicherheitsgruenden keine externe Konfiguration automatisch. Werte aus einer bisherigen Windows- oder AppDaemon-Installation muessen einmalig in den App-Optionen eingetragen werden. Nicht beide Installationen gleichzeitig im Echtzeitmodus betreiben.

## Fehlerdiagnose

Die Ingress-Seite zeigt Status, beobachtete Listen, Todo-Entitaeten und Live-Protokolle. Zusaetzlich steht das Containerprotokoll auf der App-Seite unter **Protokoll** bereit.

## Schnittstellenhinweis

Dies ist keine offizielle Erweiterung der mobilen Shopping-App. Die Kopplung beruht auf deren bestehender Firebase-Realtime-Database-/WebSocket-Schnittstelle. Aenderungen am Originaltool oder dessen Backend koennen die Kompatibilitaet beeinflussen.

