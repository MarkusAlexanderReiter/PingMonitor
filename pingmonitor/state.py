"""Persistenter Zustand fuer die Rate-Limit-Logik.

Der Zeitpunkt der letzten Alarm-E-Mail je Host wird in einer kleinen JSON-Datei
gehalten - bewusst getrennt vom Log, damit Log-Rotation die Rate-Limit-Pruefung
nie beeinflusst.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class State:
    """Verwaltet die "zuletzt gesendet"-Zeitstempel je Host."""

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._data: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        if not self._path.is_file():
            return {}
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data.get("last_alert", {})
        except (json.JSONDecodeError, OSError) as exc:
            # Beschaedigter Zustand darf den Lauf nicht stoppen - lieber neu beginnen.
            logger.warning("Zustandsdatei %s nicht lesbar (%s), starte mit leerem Zustand.", self._path, exc)
            return {}

    def should_send(self, host_ip: str, window_hours: float, now: datetime | None = None) -> bool:
        """True, wenn fuer diesen Host wieder eine E-Mail erlaubt ist."""
        now = now or datetime.now(timezone.utc)
        last_raw = self._data.get(host_ip)
        if last_raw is None:
            return True
        try:
            last = datetime.fromisoformat(last_raw)
        except ValueError:
            return True
        return now - last >= timedelta(hours=window_hours)

    def record_sent(self, host_ip: str, now: datetime | None = None) -> None:
        """Vermerkt, dass soeben eine Alarm-E-Mail fuer diesen Host versandt wurde."""
        now = now or datetime.now(timezone.utc)
        self._data[host_ip] = now.isoformat()

    def save(self) -> None:
        """Schreibt den Zustand atomar zurueck auf die Platte."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump({"last_alert": self._data}, fh, indent=2)
        tmp.replace(self._path)
