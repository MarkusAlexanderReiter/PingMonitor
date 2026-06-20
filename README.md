# PingMonitor

Ein schlankes Python-Tool, das eine oder mehrere IP-Adressen pingt, jedes Ergebnis
protokolliert und bei nicht erreichbaren Hosts eine E-Mail-Warnung ueber die
**Microsoft Graph API (Outlook)** versendet. Gedacht fuer den unbeaufsichtigten
Betrieb als Windows-Dienst via [NSSM](https://nssm.cc/).

## Funktionsweise

Pro Aufruf wird jeder konfigurierte Host einmal gepingt:

- **Erreichbar:** Ergebnis wird geloggt, sonst passiert nichts.
- **Nicht erreichbar:** Ergebnis wird geloggt und eine Alarm-E-Mail versandt –
  sofern das Rate-Limit (siehe unten) dies zulaesst.

Das Skript fuehrt bewusst **genau einen Durchlauf** pro Aufruf aus. Die
wiederkehrende Ausfuehrung uebernimmt extern NSSM.

### Rate-Limit (Anti-Spam)

Vor dem Versand wird geprueft, wann zuletzt eine E-Mail fuer den jeweiligen Host
gesendet wurde. Liegt das weniger als `rate_limit_hours` (Standard: 24 h) zurueck,
wird **kein** weiterer Alarm gesendet – der fehlgeschlagene Ping wird aber
trotzdem protokolliert. Die Zeitstempel liegen in einer kleinen Zustandsdatei
(`state.json`), bewusst getrennt vom Log, damit Log-Rotation die Logik nicht stoert.

## Projektstruktur

```
pingmonitor/
├── __init__.py
├── __main__.py          # Aufruf via `python -m pingmonitor`
├── main.py              # Einstiegspunkt: Konfig laden → Hosts durchlaufen
├── config.py            # TOML + .env laden und validieren
├── pinger.py            # Ping via icmplib mit System-Ping-Fallback
├── notifier.py          # Microsoft-Graph-Auth und E-Mail-Versand
├── state.py             # JSON-Zustand fuer Rate-Limit
└── logging_setup.py     # Logging mit groessenbasierter Rotation
config.example.toml      # Beispielkonfiguration
.env.example             # Beispiel-Geheimnisse
requirements.txt
```

## Warum TOML als Konfigurationsformat?

TOML wird ab Python 3.11 ohne Zusatzpaket gelesen (`tomllib`), ist streng typisiert
(echte Zahlen/Booleans statt YAML-Mehrdeutigkeiten) und bildet die Hostliste mit
`[[hosts]]`-Tabellen natuerlich ab. YAML braeuchte eine zusaetzliche Abhaengigkeit
ohne echten Mehrwert fuer diesen Anwendungsfall.

## Installation

Voraussetzung: **Python 3.11+**.

```powershell
git clone <repo-url> PingMonitor
cd PingMonitor
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Konfiguration

1. **Konfigurationsdatei anlegen:**

   ```powershell
   Copy-Item config.example.toml config.toml
   ```

   Hosts, Empfaenger, Absender und Ping-Parameter anpassen.

2. **Geheimnisse hinterlegen:**

   ```powershell
   Copy-Item .env.example .env
   ```

   Werte aus der Azure-App-Registrierung eintragen:

   | Variable | Bedeutung |
   |---|---|
   | `GRAPH_TENANT_ID` | Verzeichnis-(Mandanten-)ID |
   | `GRAPH_CLIENT_ID` | Anwendungs-(Client-)ID |
   | `GRAPH_CLIENT_SECRET` | Client-Secret der App |

   Weder `.env` noch `config.toml` werden eingecheckt (siehe `.gitignore`).

### Voraussetzung Microsoft Graph

In Azure AD eine App registrieren und ihr die **Application Permission**
`Mail.Send` erteilen (mit Admin-Zustimmung). Der `sender` in der Konfiguration muss
ein Postfach sein, in dessen Namen die App senden darf.

## Ausfuehren

```powershell
python -m pingmonitor
# oder mit abweichendem Konfigpfad:
python -m pingmonitor --config C:\pfad\zu\config.toml
```

Exit-Codes: `0` = Durchlauf ok, `2` = Konfigurationsfehler.

## Ping-Methode und Rechte

Standardmaessig wird **icmplib** verwendet. Diese Bibliothek nutzt Raw-Sockets und
benoetigt unter **Windows Administratorrechte** (bzw. root unter Linux/macOS).

Damit das Tool auch **ohne erhoehte Rechte** laeuft, gibt es einen Fallback: Im
Modus `method = "auto"` (Standard) wird zunaechst icmplib versucht; fehlen die
noetigen Rechte, weicht PingMonitor automatisch auf das mitgelieferte
Betriebssystem-Kommando `ping` aus, das ohne Adminrechte funktioniert.

Mit `method = "system"` laesst sich der Fallback erzwingen, mit `method = "icmplib"`
ausschliesslich icmplib verwenden.

> Hinweis: Der System-Ping liefert weniger Detailmetriken (nur Erreichbarkeit ueber
> den Exit-Code), reicht fuer die Alarmierung aber vollkommen aus.

## Logging und Rotation

- Speicherort konfigurierbar ueber `logging.path` (Standard: `logs/pingmonitor.log`).
- Geloggt wird gleichzeitig in die Datei und auf die Konsole.
- **Groessenbasierte Rotation:** Erreicht die Datei `max_bytes` (Standard 5 MB), wird
  sie rotiert; es werden bis zu `backup_count` Altdateien (`.1` … `.5`) aufbewahrt,
  aeltere automatisch geloescht. So bleibt der Plattenverbrauch ohne externen
  Cron-Job begrenzt.
- Format: `Zeitstempel | Level | Modul | Nachricht` – menschenlesbar und parsebar.

## Deployment als Windows-Dienst mit NSSM

PingMonitor enthaelt keine eigene Scheduling-Logik. Fuer den wiederkehrenden Betrieb
empfiehlt sich eine geplante Aufgabe oder ein Dienst via NSSM.

1. **NSSM installieren** (z. B. nach `C:\Tools\nssm`).

2. **Dienst einrichten** (Pfade anpassen):

   ```powershell
   nssm install PingMonitor "C:\PingMonitor\.venv\Scripts\python.exe" "-m pingmonitor"
   nssm set PingMonitor AppDirectory "C:\PingMonitor"
   ```

3. **Da das Skript pro Aufruf nur einmal laeuft**, gibt es zwei gaengige Varianten:

   - **Geplante Aufgabe (empfohlen, einfacher):** Den Aufruf
     `python -m pingmonitor` per Windows-Aufgabenplanung im gewuenschten Intervall
     (z. B. alle 5 Minuten) starten. NSSM ist dann nicht zwingend noetig.

   - **NSSM mit Wrapper-Schleife:** Ein kleines Skript pingt in einer Schleife mit
     `Start-Sleep`. NSSM startet dieses Wrapper-Skript und haelt es am Leben:

     ```powershell
     # loop.ps1
     while ($true) {
         & "C:\PingMonitor\.venv\Scripts\python.exe" -m pingmonitor
         Start-Sleep -Seconds 300
     }
     ```

     ```powershell
     nssm install PingMonitor powershell.exe "-ExecutionPolicy Bypass -File C:\PingMonitor\loop.ps1"
     nssm set PingMonitor AppDirectory "C:\PingMonitor"
     ```

4. **Rechte beachten:** Soll icmplib (Raw-Sockets) statt des Fallbacks genutzt
   werden, muss der Dienst unter einem Konto mit Administratorrechten
   (z. B. `LocalSystem`) laufen. Andernfalls genuegt der `auto`-/`system`-Modus.

5. **Dienst starten:**

   ```powershell
   nssm start PingMonitor
   ```

## Fehlerbehandlung

- **Konfigurationsfehler** (fehlende Datei, ungueltiges TOML, fehlende Secrets)
  werden vor dem Start abgefangen und mit Exit-Code `2` gemeldet.
- **Netzwerk-/Ping-Fehler** eines Hosts brechen den Gesamtdurchlauf nicht ab – die
  uebrigen Hosts werden weiter geprueft.
- **Auth-/Versandfehler** bei Graph werden geloggt; der Zeitstempel wird in diesem
  Fall **nicht** gesetzt, sodass beim naechsten Lauf erneut versucht wird.
