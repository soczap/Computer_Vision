"""Structured JSON logging to stdout and a rotating file."""
from __future__ import annotations

import json
import logging
import logging.handlers
import time

from vigil.config import get_settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "ctx", None)
        if extra:
            out.update(extra)
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def setup_logging() -> None:
    s = get_settings()
    root = logging.getLogger()
    root.setLevel(s.log_level)
    for h in list(root.handlers):
        root.removeHandler(h)
    stream = logging.StreamHandler()
    stream.setFormatter(JsonFormatter())
    root.addHandler(stream)
    (s.data_dir / "logs").mkdir(exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(s.data_dir / "logs" / "vigil.log", maxBytes=20_000_000, backupCount=5)
    fh.setFormatter(JsonFormatter())
    root.addHandler(fh)
    for noisy in ("httpx", "httpcore", "ultralytics", "urllib3", "PIL", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log(logger: logging.Logger, level: int, msg: str, **ctx) -> None:
    logger.log(level, msg, extra={"ctx": ctx})
