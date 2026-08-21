"""Logging setup that keeps secrets out of diagnostic output."""
from __future__ import annotations

import logging
import sys
from pathlib import Path


def configure_logging(level: str, secrets: list[str], log_file: str | None = None) -> None:
    class SecretFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            message = record.getMessage()
            for secret in secrets:
                if secret:
                    message = message.replace(secret, "[REDACTED]")
            record.msg = message
            record.args = ()
            return True

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    secret_filter = SecretFilter()
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    stdout_handler.addFilter(secret_filter)
    handlers: list[logging.Handler] = [stdout_handler]
    if log_file:
        try:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            file_handler.setFormatter(formatter)
            file_handler.addFilter(secret_filter)
            handlers.append(file_handler)
        except OSError:
            # Render and container deployments should still start if the
            # optional filesystem log path is unavailable; stdout remains live.
            pass

    root = logging.getLogger()
    root.handlers.clear()
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
