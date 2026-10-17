# LifeAIManager — Automatisierter Schul- & Lebensmanager

## Zielf

Dieses System ist ein persönliches Projekt, welches mir bei der Organisation meiner Schullaufbahn helfen soll. Ich nutze es selber täglich, um alle meine Aufgaben und anstehenden Termine in der Schule im Blick zu behalten.

## Architektur

n8n läuft bei mir in einem Docker-Container auf meinem Raspberry Pi 5, meine Python-Skripte dagegen laufen direkt auf dem Pi selbst außerhalb von Docker und werden von n8n per SSH aufgerufen. Gesteuert wird das ganze System von 3 n8n-Workflows. Es beginnt mit dem WebUntis-Workflow: Dieser fragt über SSH an, das read_untis.py-Skript auszuführen, sammelt dann alle Daten, baut sie zu einer JSON um und speichert sie in einer Datei ab (untis_latest.json). Dieser Workflow läuft unter der Woche jede Stunde von 7-21 Uhr und sonntags zweimal um 18 und 21 Uhr.

Der Logineo-Workflow für den Schul-Messenger läuft auf einem eigenen, am Stundenplan orientierten Zeitplan und liest sich zu Beginn erstmal die zuletzt gespeicherte untis_latest.json durch, um den aktuellen Untis-Stand mit einzubeziehen. Danach führt er per SSH das read_messages.py aus und gruppiert die ganzen Daten nach Fächern und sortiert dann Textnachrichten und Anhänge. Der Text wird Pseudomysiert und dann an Claude weitergeleitet, wo dieser von Sonnet 5 verarbeitet wird und sauber JSON ausgibt, was dann über das vault_io.py-Skript geprüft und im Obsidian-Vault gespeichert wird. Die Anhänge werdern wenn sie eine PDF sind ausgelessen Pseudomysiert und an Claude weitergegeben und werden anschließend mit allen anderen Datein in den passenden Fach-Ordner sortiert und abgelegt.

Ich habe mich aktiv gegen eine richtige Datenbank (SQL, MongoDB) entschieden, weil ich die Möglichkeit haben wollte, sowohl auf meinem Handy als auch auf meinem PC direkt über die Obsidian-App auf alle meine Dateien zuzugreifen, die dann von Syncthing synchronisiert werden.

Der letzte Workflow sammelt dann alle bisher gesammelten und zusammengefassten Daten aus dem Vault und gibt sie wieder zu Sonnet 5, der daraus dann ein kurzes Briefing schreibt und dieses dann direkt als Push-Benachrichtigung in die WebApp lädt.

Alle gesammelten Daten werden dann sauber in der LifeAI-WebApp wiedergegeben: sowohl die Aufgaben und Notizen, die im Vault gespeichert sind, als auch die aktuellen WebUntis-Daten werden mit gezeigt und können jederzeit geöffnet werden. Zudem besitzt die WebApp eigene Endpunkte, z. B. kann ich die Aufgaben direkt innerhalb der WebApp als gemacht abhaken, was dann wieder im Vault gespeichert wird. Die WebApp besteht aus einem JS-Frontend und einem FastAPI-Server. Erreichbar ist die App von außen über einen Cloudflare-Tunnel, dazu mehr unter Sicherheitsaspekte.

<!-- Optional: Diagramm als Bild einfügen -->

## Datenquellen

### Logineo NRW Messenger (Matrix)

Um an die Daten aus dem Schul-Messenger zu kommen, habe ich die Matrix-API genutzt und mithilfe eines SSO-Login-Tokens eine neue Session mit eigener Device-ID und Access-Token erstellt. Dadurch kann ich den Login immer wieder herstellen, ohne mich neu einzuloggen. Außerdem nutze ich Sync-Tokens, um nur die Events abzufragen, die seit meiner letzten Abfrage passiert sind, um Dopplungen zu vermeiden.

### WebUntis

WebUntis bietet keine Ende-zu-Ende-Verschlüsselung, die Verbindung läuft über HTTPS und nutzt das JSON-RPC-Verfahren, weshalb ich mich jedes Mal neu einloggen muss. Durch das Einloggen bekomme ich von WebUntis meine SessionID, PersonType, PersonID und KlasseID, welche ich dann nutze, um meinen Stundenplan abzufragen. Ich frage immer die nächsten 7 Tage ab, dadurch weiß ich immer frühzeitig Bescheid, wenn sich etwas ändert oder Hausaufgaben bei WebUntis eingetragen wurden. Der Zugriff auf die Klausurdaten in WebUntis ist für Schüler gesperrt, weshalb ich durch WebUntis nicht herausfinden kann, wann meine Klausuren stattfinden.

## Sicherheitsaspekte

Ich habe meine WebApp durch einen Cloudflare-Tunnel mit E-Mail-PIN abgesichert, sodass nur ich (oder jemand mit Zugriff auf meine E-Mail) auf meine Daten zugreifen kann. Dafür habe ich mich entschieden, weil ich nicht wollte, dass mein Raspberry Pi durch einen offenen Port von außen sichtbar wird und meine Daten geschützt sind. Zudem habe ich einen Header-Check eingebaut, sodass selbst wenn ich mal versehentlich meinen Cloudflare-Tunnel umbaue und einen Fehler einbaue, durch den Access umgangen werden kann, meine Daten trotzdem noch sicher sind, da ich erst abfrage, ob bei der Anfrage der von Cloudflare Access geprüfte Header vorhanden ist.

Dadurch, dass ich auf "fremde" Systeme zugreife, habe ich besonders darauf geachtet, dass meine komplette Struktur read-only ist und es keine einzige Methode im Code gibt, die die Möglichkeit hätte, etwas zu schreiben oder eine Authentifizierungsanfrage zu schicken. Eine Ausnahme davon ist mein Vault, doch auch hier führe ich Checks aus, bevor ich etwas schreibe: So prüft das vault_io.py bei jedem Schreibvorgang erst, ob der Dateipfad auch wirklich innerhalb meines Vaults liegt. Das sichert mich auch vor Prompt-Injection-Angriffen.

Alle meine Access Tokens, Passwörter und Secrets sind in Config-Dateien mit chmod 600 abgesichert, sodass nur ich darauf Zugriff habe.

Zugunste des Datenschutzes nutze ich Pseudomysierung um echte nahmen durch Kürzel auszutauschen bevor ich diese an Claude sende, falls die Tabelle fehlt oder es einen fehler bei der Pseudomysierung gibt bricht der Workflow ab.

## Setup

Dieses Repo enthält nur den Code, keine Zugangsdaten oder Laufzeitdaten (siehe `.gitignore`). Um das System selbst zum Laufen zu bringen:

1. **Python-Umgebung einrichten** (für `matrix-client/` und `lifeai-app/` jeweils eigene venv empfohlen):
```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
```

2. **Config-Dateien anlegen** aus den mitgelieferten Vorlagen und mit eigenen Werten befüllen:
```bash
   cp matrix-client/matrix_config.example.json matrix-client/matrix_config.json
   cp matrix-client/untis_config.example.json matrix-client/untis_config.json
   cp lifeai-app/config.example.json lifeai-app/config.json
```
   Rechte einschränken, da hier Zugangsdaten drinstehen:
```bash
   chmod 600 matrix-client/matrix_config.json matrix-client/untis_config.json lifeai-app/config.json
```

3. **Matrix-Login einmalig durchführen** (SSO-Token-Login, siehe `e2ee_login.py`), Access Token + Device-ID in `matrix_config.json` eintragen.

4. **n8n aufsetzen** (eigener Docker-Container), SSH-Zugang vom n8n-Container zum Pi-Host einrichten (eigener Nutzer, Key-Login), Anthropic-API-Credential in n8n hinterlegen.

5. **Cloudflare Tunnel einrichten**, falls Fernzugriff gewünscht ist (Domain bei Cloudflare, `cloudflared` als systemd-Service).

6. **Syncthing installieren**, um das Obsidian-Vault mit anderen Geräten zu synchronisieren.

## Tech-Stack

- **Hardware:** Raspberry Pi 5, Raspberry Pi OS 64-bit Lite
- **Orchestrierung:** n8n (Docker-Container)
- **Datenquellen-Skripte:** Python 3.13, `matrix-nio[e2e]` (Matrix/Logineo), eigene WebUntis-JSON-RPC-Anbindung, `pypdf` + `python-docx` (Textauszug aus Anhängen)
- **KI:** Anthropic Claude API (Sonnet 5 für Briefings, Logineo-Zusammenfassungen)
- **Speicher:** Obsidian-Vault (Markdown-Dateien), Synchronisation über Syncthing
- **WebApp:** FastAPI-Server, Vanilla-JS-Frontend, Service Worker + Web Push (`pywebpush`) für die PWA
- **Zugriff & Sicherheit:** Cloudflare Tunnel, Cloudflare Access (E-Mail-Code-Login)

## Einsatz von KI

Bei der Umsetzung habe ich Claude als Programmier-Assistenten genutzt, vor allem für Code-Bausteine, Debugging und beim nachträglichen Aufräumen des Repos für diese Veröffentlichung. Architektur-Entscheidungen (z. B. Matrix-API statt Browser-Automatisierung, Cloudflare-Zugriffsschutz, Obsidian-Vault statt Datenbank) sowie das Testen und Verstehen des Systems im laufenden Betrieb kamen von mir. Dabei habe ich auch gelernt, wie man mit Git, dem Linux-Terminal und den Einzelteilen des Systems selbst umgeht.

## Lessons Learned

Anfangs hatte ich Probleme, weil die Daten im Schul-Messenger E2E-verschlüsselt sind – ich hatte zuerst Schwierigkeiten, darauf zuzugreifen. Meine ersten Versuche waren, den Messenger im Browser mit Playwright zu steuern, da jedoch alle automatisierten Login-Versuche vom Server blockiert wurden, musste ich hier den doch sichereren Umweg mit der Matrix-API und dem SSO-Login nehmen.

Dadurch, dass die n8n-SSH-Bibliothek älter ist, hatte ich zuerst Probleme mit meinem ed25519-Schlüssel im OpenSSH-Format und bin dann auf einen älteren RSA-Schlüssel im PEM-Format umgestiegen.

Ich habe zudem gelernt, wie man mit dem Linux-Terminal umgeht und wie man Dateien über SCP von Computer zu Computer kopiert.

Zudem habe ich gelernt, dass man vor der Nutzung von Bibliotheken immer gucken sollte, was sie machen und was sie können. Die matrix-nio-Bibliothek hatte anfangs noch Funktionen im Code, die es meinem Programm ermöglicht hätten, Nachrichten zu schreiben und Anfragen zu verschicken, also musste ich diese Funktionen vor der Nutzung löschen.

Ich habe an erster Hand erfahren, dass die KI oft halluziniert. Ich hatte schon oft davon gehört, es jedoch bisher nicht so ernst genommen, weil ich KI nur für Hobbys und grundlegende Recherche genutzt habe, wo es mir oft direkt aufgefallen ist und ich eher darüber gelacht habe. Als hier allerdings auf einmal Aufgaben mit falschem Abgabedatum dastanden, die trotzdem plausibel klangen, habe ich erstmals meinen Prompt verfeinert und das Modell gewechselt – aber auch daraus gelernt, dass ich nicht allen Angaben vertrauen kann.

## Status

Ich nutze das System aktuell schon im regulären Betrieb: Mir werden konkret alle Aufgaben mit Abgabedatum angezeigt, sofern sie auf WebUntis oder im Schul-Messenger notiert wurden. Außerdem kann ich immer meinen aktuellen Stundenplan mit allen Änderungen ansehen und bekomme einmal vor und einmal nach der Schule ein kleines "Briefing", was ich noch machen muss und was heute ansteht.

In der Zukunft würde ich gerne noch alle meine selbst geschriebenen Notizen und erledigten Aufgaben einpflegen sowie ein manuelles Eingabefeld haben, wo ich z. B. nicht in WebUntis oder Logineo hinterlegte Aufgaben eintragen kann. Zudem plane ich, ein kleines Abfragefenster zu erstellen, wo ich dann konkret Fragen zu Arbeitsblatt-Aufgaben oder allgemein zum Vault stellen kann, um mich z. B. ideal auf Klausuren vorzubereiten und einzusehen, was wir z. B. in den letzten 6 Wochen in Mathe gemacht haben.

