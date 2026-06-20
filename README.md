# PingMonitor

Ein schlankes Python-Tool, das eine oder mehrere IP-Adressen pingt, jedes Ergebnis
protokolliert und bei nicht erreichbaren Hosts eine E-Mail-Warnung über die
**Microsoft Graph API (Outlook)** versendet. Gedacht für den unbeaufsichtigten
Betrieb als Windows-Dienst via [NSSM](https://nssm.cc/).

## Funktionsweise

Pro Aufruf wird jeder konfigurierte Host einmal gepingt:

- **Erreichbar:** Ergebnis wird geloggt, sonst passiert nichts.
- **Nicht erreichbar:** Ergebnis wird geloggt und eine Alarm-E-Mail versandt –
  sofern das Rate-Limit (siehe unten) dies zulässt.

Das Skript führt bewusst **genau einen Durchlauf** pro Aufruf aus. Die
wiederkehrende Ausführung übernimmt extern NSSM.

### Rate-Limit (Anti-Spam)

Vor dem Versand wird geprüft, wann zuletzt eine E-Mail für den jeweiligen Host
gesendet wurde. Liegt das weniger als `rate_limit_hours` (Standard: 24 h) zurück,
wird **kein** weiterer Alarm gesendet – der fehlgeschlagene Ping wird aber
trotzdem protokolliert. Die Zeitstempel liegen in einer kleinen Zustandsdatei
(`state.json`), bewusst getrennt vom Log, damit Log-Rotation die Logik nicht stört.

## Projektstruktur

```
pingmonitor/
├── __init__.py
├── __main__.py          # Aufruf via `python -m pingmonitor`
├── main.py              # Einstiegspunkt: Konfig laden → Hosts durchlaufen
├── config.py            # TOML + .env laden und validieren
├── pinger.py            # Ping via icmplib mit System-Ping-Fallback
├── notifier.py          # Microsoft-Graph-Auth und E-Mail-Versand
├── state.py             # JSON-Zustand für Rate-Limit
└── logging_setup.py     # Logging mit größenbasierter Rotation
config.example.toml      # Beispielkonfiguration
.env.example             # Beispiel-Geheimnisse
requirements.txt
```

## Warum TOML als Konfigurationsformat?

TOML wird ab Python 3.11 ohne Zusatzpaket gelesen (`tomllib`), ist streng typisiert
(echte Zahlen/Booleans statt YAML-Mehrdeutigkeiten) und bildet die Hostliste mit
`[[hosts]]`-Tabellen natürlich ab. YAML bräuchte eine zusätzliche Abhängigkeit
ohne echten Mehrwert für diesen Anwendungsfall.

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

   Hosts, Empfänger, Absender und Ping-Parameter anpassen.

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

## Ausführen

```powershell
python -m pingmonitor
# oder mit abweichendem Konfigpfad:
python -m pingmonitor --config C:\pfad\zu\config.toml
```

Exit-Codes: `0` = Durchlauf ok, `2` = Konfigurationsfehler.

## Ping-Methode und Rechte

Standardmäßig wird **icmplib** verwendet. Diese Bibliothek nutzt Raw-Sockets und
benötigt unter **Windows Administratorrechte** (bzw. root unter Linux/macOS).

Damit das Tool auch **ohne erhöhte Rechte** läuft, gibt es einen Fallback: Im
Modus `method = "auto"` (Standard) wird zunächst icmplib versucht; fehlen die
nötigen Rechte, weicht PingMonitor automatisch auf das mitgelieferte
Betriebssystem-Kommando `ping` aus, das ohne Adminrechte funktioniert.

Mit `method = "system"` lässt sich der Fallback erzwingen, mit `method = "icmplib"`
ausschließlich icmplib verwenden.

> Hinweis: Der System-Ping liefert weniger Detailmetriken (nur Erreichbarkeit über
> den Exit-Code), reicht für die Alarmierung aber vollkommen aus.

## Logging und Rotation

- Speicherort konfigurierbar über `logging.path` (Standard: `logs/pingmonitor.log`).
- Geloggt wird gleichzeitig in die Datei und auf die Konsole.
- **Größenbasierte Rotation:** Erreicht die Datei `max_bytes` (Standard 5 MB), wird
  sie rotiert; es werden bis zu `backup_count` Altdateien (`.1` … `.5`) aufbewahrt,
  ältere automatisch gelöscht. So bleibt der Plattenverbrauch ohne externen
  Cron-Job begrenzt.
- Format: `Zeitstempel | Level | Modul | Nachricht` – menschenlesbar und parsebar.

## Deployment als Windows-Dienst mit NSSM

PingMonitor enthält keine eigene Scheduling-Logik. Für den wiederkehrenden Betrieb
empfiehlt sich eine geplante Aufgabe oder ein Dienst via NSSM.

1. **NSSM installieren** (z. B. nach `C:\Tools\nssm`).

2. **Dienst einrichten** (Pfade anpassen):

   ```powershell
   nssm install PingMonitor "C:\PingMonitor\.venv\Scripts\python.exe" "-m pingmonitor"
   nssm set PingMonitor AppDirectory "C:\PingMonitor"
   ```

3. **Da das Skript pro Aufruf nur einmal läuft**, gibt es zwei gängige Varianten:

   - **Geplante Aufgabe (empfohlen, einfacher):** Den Aufruf
     `python -m pingmonitor` per Windows-Aufgabenplanung im gewünschten Intervall
     (z. B. alle 5 Minuten) starten. NSSM ist dann nicht zwingend nötig.

   - **NSSM mit Wrapper-Schleife:** Ein kleines Skript pingt in einer Schleife mit
     `Start-Sleep`. NSSM startet dieses Wrapper-Skript und hält es am Leben:

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
   (z. B. `LocalSystem`) laufen. Andernfalls genügt der `auto`-/`system`-Modus.

5. **Dienst starten:**

   ```powershell
   nssm start PingMonitor
   ```

## Fehlerbehandlung

- **Konfigurationsfehler** (fehlende Datei, ungültiges TOML, fehlende Secrets)
  werden vor dem Start abgefangen und mit Exit-Code `2` gemeldet.
- **Netzwerk-/Ping-Fehler** eines Hosts brechen den Gesamtdurchlauf nicht ab – die
  übrigen Hosts werden weiter geprüft.
- **Auth-/Versandfehler** bei Graph werden geloggt; der Zeitstempel wird in diesem
  Fall **nicht** gesetzt, sodass beim nächsten Lauf erneut versucht wird.
