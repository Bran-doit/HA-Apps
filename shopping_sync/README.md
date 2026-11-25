# Shopping Sync

Shopping Sync verbindet gleichnamige Home-Assistant-Todo-Listen mit den Listen einer mobilen Shopping-App. Die App laeuft vollstaendig als Home-Assistant-Supervisor-App, verwendet intern AppDaemon und stellt ihre Bedienoberflaeche ueber Home Assistant Ingress bereit.

## Funktionen

- bidirektionale Synchronisation ueber Firebase WebSocket
- Echtzeit- und Bedarfsbetrieb
- automatische Erkennung vorhandener Todo-Listen
- explizite Auswahl einzelner Listen oder Verwendung aller Firebase-Listen
- Status, Live-Protokoll, Diagnose und Konfiguration in der Seitenleiste
- persistente Konfiguration und Protokolle in `/data`

Die Zugangsdaten werden vom Benutzer bei der Installation eingetragen. Dieses Repository enthaelt keine Konten, Kennwoerter, Tokens oder privaten Listen.

## Originaltool und Schnittstelle

Shopping Sync ist eine unabhaengige, inoffizielle Bruecke. Sie spricht die von der urspruenglichen mobilen Shopping-App verwendete Firebase-Realtime-Database- und WebSocket-Schnittstelle und bildet deren Listenmodell auf Home-Assistant-Todo-Entitaeten ab. Die mobile App, ihre Firebase-Infrastruktur, Marken und das zugrunde liegende Datenformat bleiben Eigentum und Verantwortung des jeweiligen Originalprogrammierers. Es besteht keine Zugehoerigkeit oder offizielle Unterstuetzung durch den Programmierer der Original-App.

Der im vorliegenden Quellbestand ueberlieferte Name der Gegenstelle lautet nur `Shopping-App`; ein belastbar verifizierbarer Personen- oder Firmenname des Originalprogrammierers ist darin nicht enthalten. Deshalb wird bewusst keine ungesicherte Namensnennung vorgenommen.

