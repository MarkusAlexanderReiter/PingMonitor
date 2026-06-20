"""Zentrale Logging-Konfiguration mit groessenbasierter Rotation.

Geloggt wird gleichzeitig in eine rotierende Datei und auf die Konsole. Das
Format ist menschenlesbar und zugleich gut zu parsen (feste, durch | getrennte
Felder). Die Rotation begrenzt den Plattenverbrauch ohne externen Cron-Job.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from pingmonitor.config import LoggingConfig

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(cfg: LoggingConfig) -> None:
    """Konfiguriert das Root-Logging gemaess Konfiguration."""
    log_path = Path(cfg.path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    # Rotierender Datei-Handler: max_bytes pro Datei, danach Rotation in .1, .2 ...
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=cfg.max_bytes,
        backupCount=cfg.backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(cfg.level)
    # Mehrfaches setup_logging (z. B. in Tests) darf keine Handler doppeln.
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console_handler)


def tail_log(path: str, lines: int = 15) -> str:
    """Liest die letzten `lines` Zeilen der Logdatei fuer den E-Mail-Kontext."""
    log_path = Path(path)
    if not log_path.is_file():
        return "(keine Logeintraege vorhanden)"
    try:
        with log_path.open("r", encoding="utf-8") as fh:
            content = fh.readlines()
    except OSError:
        return "(Logdatei nicht lesbar)"
    return "".join(content[-lines:]).strip()
