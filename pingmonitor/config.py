"""Laden und Validieren der Konfiguration aus TOML-Datei und .env.

Geheimnisse (Graph-Credentials) kommen aus der Umgebung bzw. einer .env-Datei,
alle uebrigen Einstellungen aus der TOML-Datei. So landen Secrets nie im Repo.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


class ConfigError(Exception):
    """Wird bei fehlender oder fehlerhafter Konfiguration ausgeloest."""


@dataclass(frozen=True)
class Host:
    ip: str
    name: str  # Anzeigename fuer E-Mails; faellt auf die IP zurueck, falls leer


@dataclass(frozen=True)
class PingConfig:
    count: int = 4
    timeout: float = 2.0
    # "auto" versucht icmplib und faellt bei fehlenden Rechten auf das System-Ping
    # zurueck. Alternativ "icmplib" oder "system" erzwingen.
    method: str = "auto"


@dataclass(frozen=True)
class AlertConfig:
    rate_limit_hours: float = 24.0
    recipients: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GraphConfig:
    tenant_id: str
    client_id: str
    client_secret: str
    sender: str


@dataclass(frozen=True)
class LoggingConfig:
    path: str = "logs/pingmonitor.log"
    level: str = "INFO"
    max_bytes: int = 5 * 1024 * 1024  # 5 MB pro Datei
    backup_count: int = 5  # Anzahl archivierter Altdateien


@dataclass(frozen=True)
class Config:
    hosts: list[Host]
    ping: PingConfig
    alerts: AlertConfig
    graph: GraphConfig
    logging: LoggingConfig
    state_path: str


def _require(value: str | None, env_name: str) -> str:
    """Stellt sicher, dass ein Pflicht-Geheimnis gesetzt ist."""
    if not value:
        raise ConfigError(f"Umgebungsvariable {env_name} ist nicht gesetzt (siehe .env.example).")
    return value


def load_config(config_path: str | os.PathLike[str] = "config.toml") -> Config:
    """Liest die TOML-Konfiguration plus Secrets aus der Umgebung ein.

    Raises:
        ConfigError: bei fehlender Datei, ungueltigem TOML oder fehlenden Pflichtfeldern.
    """
    # .env laden (ueberschreibt vorhandene Umgebungsvariablen bewusst nicht).
    load_dotenv()

    path = Path(config_path)
    if not path.is_file():
        raise ConfigError(f"Konfigurationsdatei nicht gefunden: {path}")

    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Konfigurationsdatei ist kein gueltiges TOML: {exc}") from exc

    hosts = _parse_hosts(raw.get("hosts", []))
    if not hosts:
        raise ConfigError("Es ist mindestens ein [[hosts]]-Eintrag erforderlich.")

    ping_raw = raw.get("ping", {})
    ping = PingConfig(
        count=int(ping_raw.get("count", PingConfig.count)),
        timeout=float(ping_raw.get("timeout", PingConfig.timeout)),
        method=str(ping_raw.get("method", PingConfig.method)).lower(),
    )
    if ping.method not in {"auto", "icmplib", "system"}:
        raise ConfigError("ping.method muss 'auto', 'icmplib' oder 'system' sein.")

    alerts_raw = raw.get("alerts", {})
    recipients = list(alerts_raw.get("recipients", []))
    if not recipients:
        raise ConfigError("alerts.recipients darf nicht leer sein.")
    alerts = AlertConfig(
        rate_limit_hours=float(alerts_raw.get("rate_limit_hours", AlertConfig.rate_limit_hours)),
        recipients=recipients,
    )

    graph_raw = raw.get("graph", {})
    sender = graph_raw.get("sender")
    if not sender:
        raise ConfigError("graph.sender (Absenderadresse) muss gesetzt sein.")
    graph = GraphConfig(
        tenant_id=_require(os.getenv("GRAPH_TENANT_ID"), "GRAPH_TENANT_ID"),
        client_id=_require(os.getenv("GRAPH_CLIENT_ID"), "GRAPH_CLIENT_ID"),
        client_secret=_require(os.getenv("GRAPH_CLIENT_SECRET"), "GRAPH_CLIENT_SECRET"),
        sender=sender,
    )

    log_raw = raw.get("logging", {})
    logging_cfg = LoggingConfig(
        path=str(log_raw.get("path", LoggingConfig.path)),
        level=str(log_raw.get("level", LoggingConfig.level)).upper(),
        max_bytes=int(log_raw.get("max_bytes", LoggingConfig.max_bytes)),
        backup_count=int(log_raw.get("backup_count", LoggingConfig.backup_count)),
    )

    state_path = str(raw.get("state", {}).get("path", "state.json"))

    return Config(
        hosts=hosts,
        ping=ping,
        alerts=alerts,
        graph=graph,
        logging=logging_cfg,
        state_path=state_path,
    )


def _parse_hosts(raw_hosts: list[dict]) -> list[Host]:
    hosts: list[Host] = []
    for entry in raw_hosts:
        ip = entry.get("ip")
        if not ip:
            raise ConfigError("Jeder [[hosts]]-Eintrag benoetigt ein Feld 'ip'.")
        # Ohne Namen wird die IP selbst als Anzeigename verwendet.
        name = entry.get("name") or ip
        hosts.append(Host(ip=str(ip), name=str(name)))
    return hosts
