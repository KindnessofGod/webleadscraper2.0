"""Structured JSON-lines logging. Every stage logs through the standard
logging module; this handler serializes records (plus any `extra=` fields)
as one JSON object per line to logs/pipeline.jsonl, so the log is queryable
with jq/sqlite instead of being a flat text dump.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

_RESERVED = set(logging.LogRecord(None, None, "", 0, "", None, None).__dict__.keys())


class JsonLinesFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(log_dir: str = "logs", level: int = logging.INFO) -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("pipeline")
    root.setLevel(level)
    root.handlers.clear()

    file_handler = logging.FileHandler(Path(log_dir) / "pipeline.jsonl")
    file_handler.setFormatter(JsonLinesFormatter())
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root.addHandler(console_handler)

    root.propagate = False
