"""Einstiegspunkt: einmaliger Durchlauf ueber alle Hosts.

Das Skript fuehrt pro Aufruf genau einen Durchlauf aus. Die wiederkehrende
Ausfuehrung uebernimmt extern NSSM (siehe README) - hier gibt es bewusst keine
eigene Scheduling-Logik.
"""

from __future__ import annotations

import argparse
import logging

from pingmonitor.config import Config, ConfigError, Host, load_config
from pingmonitor.logging_setup import setup_logging, tail_log
from pingmonitor.notifier import GraphNotifier, NotifierError
from pingmonitor.pinger import PingResult, ping_host
from pingmonitor.state import State

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Pingt Hosts und alarmiert bei Ausfall per E-Mail.")
    parser.add_argument(
        "-c",
        "--config",
        default="config.toml",
        help="Pfad zur TOML-Konfiguration (Standard: config.toml).",
    )
    args = parser.parse_args()

    # Konfigurationsfehler vor dem Logging-Setup abfangen und klar melden.
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Konfigurationsfehler: {exc}")
        return 2

    setup_logging(config.logging)
    logger.info("Starte Durchlauf fuer %d Host(s).", len(config.hosts))

    state = State(config.state_path)
    notifier = GraphNotifier(config.graph)

    for host in config.hosts:
        _process_host(host, config, state, notifier)

    state.save()
    logger.info("Durchlauf abgeschlossen.")
    return 0


def _process_host(host: Host, config: Config, state: State, notifier: GraphNotifier) -> None:
    """Pingt einen Host, loggt das Ergebnis und alarmiert bei Bedarf.

    Fehler eines einzelnen Hosts duerfen den Gesamtdurchlauf nicht abbrechen.
    """
    try:
        result = ping_host(host, config.ping)
    except Exception:  # defensiv: unerwartete Fehler nicht eskalieren lassen
        logger.exception("Unerwarteter Fehler beim Pingen von %s (%s).", host.name, host.ip)
        return

    if result.is_alive:
        logger.info("Host %s (%s) ist erreichbar - %s", host.name, host.ip, result.summary)
        return

    logger.warning("Host %s (%s) ist NICHT erreichbar - %s", host.name, host.ip, result.summary)
    _maybe_alert(host, result, config, state, notifier)


def _maybe_alert(
    host: Host,
    result: PingResult,
    config: Config,
    state: State,
    notifier: GraphNotifier,
) -> None:
    """Sendet eine Alarm-E-Mail, sofern das Rate-Limit es zulaesst."""
    if not state.should_send(host.ip, config.alerts.rate_limit_hours):
        logger.info(
            "Alarm fuer %s unterdrueckt (Rate-Limit von %.0f h noch aktiv).",
            host.name,
            config.alerts.rate_limit_hours,
        )
        return

    subject = f"{host.name} ist nicht erreichbar"
    body = _build_body(host, result, config)

    try:
        notifier.send(config.alerts.recipients, subject, body)
    except NotifierError:
        # Versand-Fehler protokollieren, aber den Zeitstempel NICHT setzen,
        # damit beim naechsten Lauf erneut versucht wird.
        logger.exception("Alarm-E-Mail fuer %s konnte nicht gesendet werden.", host.name)
        return

    state.record_sent(host.ip)


def _build_body(host: Host, result: PingResult, config: Config) -> str:
    """Baut den E-Mail-Text aus aktuellem Ergebnis und Log-Kontext."""
    recent_log = tail_log(config.logging.path, lines=15)
    return (
        f"Der Host '{host.name}' ({host.ip}) ist nicht erreichbar.\n\n"
        f"Aktuelles Ping-Ergebnis ({result.method}):\n"
        f"  Status: {result.status_text}\n"
        f"  Details: {result.summary}\n\n"
        f"Letzte Logeintraege:\n{recent_log}\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
