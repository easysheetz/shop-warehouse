"""Logi na standardowe wyjście.

LOG_FORMAT=json – jedna linia JSON na wpis z polem "severity", które czyta Google Cloud Logging.
LOG_FORMAT=text – czytelny format do pracy lokalnej.
Nigdy nie logujemy tokenów ani PIN-ów.
"""
import json
import logging
import sys

from .config import settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    if settings.LOG_FORMAT == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.LOG_LEVEL.upper())
    # httpx loguje pełne adresy zapytań – nie chcemy ich w logach
    logging.getLogger("httpx").setLevel(logging.WARNING)
