"""Ping-Logik mit icmplib und systemweitem Fallback ohne Admin-Rechte.

icmplib nutzt Raw-Sockets und benoetigt unter Windows Administratorrechte. Schlaegt
das mangels Rechten fehl, wird im Modus "auto" automatisch auf das mitgelieferte
Betriebssystem-Kommando `ping` ausgewichen, das ohne erhoehte Rechte auskommt.
"""

from __future__ import annotations

import logging
import platform
import subprocess
from dataclasses import dataclass

from icmplib import ICMPLibError, SocketPermissionError, ping as icmp_ping

from pingmonitor.config import Host, PingConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PingResult:
    """Ergebnis eines Ping-Vorgangs fuer genau einen Host."""

    host: Host
    is_alive: bool
    method: str  # "icmplib" oder "system"
    summary: str  # menschenlesbare Zusammenfassung fuer Log und E-Mail

    @property
    def status_text(self) -> str:
        return "erreichbar" if self.is_alive else "NICHT erreichbar"


def ping_host(host: Host, cfg: PingConfig) -> PingResult:
    """Pingt einen Host gemaess der konfigurierten Methode.

    Im Modus "auto" wird zuerst icmplib versucht; fehlen die noetigen Rechte,
    erfolgt ein transparenter Fallback auf das System-Ping.
    """
    if cfg.method == "system":
        return _system_ping(host, cfg)

    try:
        return _icmplib_ping(host, cfg)
    except SocketPermissionError:
        if cfg.method == "auto":
            logger.warning(
                "icmplib ohne ausreichende Rechte - Fallback auf System-Ping fuer %s.",
                host.ip,
            )
            return _system_ping(host, cfg)
        # Bei explizit erzwungenem icmplib den Fehler als nicht erreichbar werten.
        logger.error("icmplib-Berechtigungsfehler fuer %s.", host.ip)
        return PingResult(host, False, "icmplib", "Berechtigungsfehler: Raw-Socket nicht erlaubt.")


def _icmplib_ping(host: Host, cfg: PingConfig) -> PingResult:
    try:
        # privileged=False nutzt - wo moeglich - unprivilegierte Sockets.
        host_result = icmp_ping(
            host.ip,
            count=cfg.count,
            timeout=cfg.timeout,
            privileged=False,
        )
    except ICMPLibError as exc:
        logger.error("icmplib-Fehler fuer %s: %s", host.ip, exc)
        return PingResult(host, False, "icmplib", f"icmplib-Fehler: {exc}")

    summary = (
        f"{host_result.packets_received}/{host_result.packets_sent} Pakete, "
        f"Verlust {host_result.packet_loss:.0%}, "
        f"avg {host_result.avg_rtt:.1f} ms"
    )
    return PingResult(host, host_result.is_alive, "icmplib", summary)


def _system_ping(host: Host, cfg: PingConfig) -> PingResult:
    """Faellt auf das Betriebssystem-Kommando `ping` zurueck (keine Admin-Rechte noetig)."""
    is_windows = platform.system().lower() == "windows"
    if is_windows:
        # -n Anzahl, -w Timeout in Millisekunden.
        cmd = ["ping", "-n", str(cfg.count), "-w", str(int(cfg.timeout * 1000)), host.ip]
    else:
        # -c Anzahl, -W Timeout in Sekunden (ganzzahlig).
        cmd = ["ping", "-c", str(cfg.count), "-W", str(max(1, int(cfg.timeout))), host.ip]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=cfg.timeout * cfg.count + 5,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.error("System-Ping fuer %s fehlgeschlagen: %s", host.ip, exc)
        return PingResult(host, False, "system", f"System-Ping-Fehler: {exc}")

    is_alive = proc.returncode == 0
    summary = f"System-Ping Exit-Code {proc.returncode}"
    return PingResult(host, is_alive, "system", summary)
