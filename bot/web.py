"""Small HTTP health server for Render Web Service deployments.

Telegram polling remains owned by python-telegram-bot's asyncio loop. Flask is
only used for Render/UptimeRobot health checks and runs in a daemon thread so
it cannot block polling or the scheduler.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from flask import Flask, jsonify

logger = logging.getLogger(__name__)
app = Flask(__name__)
_started_at = time.time()
_state_lock = threading.Lock()
_ready = False
_stopping = False
_server_thread: threading.Thread | None = None


def _status_payload() -> dict[str, Any]:
    with _state_lock:
        ready = _ready
        stopping = _stopping
    return {
        "service": "gsi-study-mcq-bot",
        "status": "stopping" if stopping else ("ok" if ready else "starting"),
        "telegram_polling": "running" if not stopping else "stopping",
        "uptime_seconds": round(max(0.0, time.time() - _started_at), 1),
    }


@app.get("/")
def index():
    return jsonify(_status_payload())


@app.get("/health")
def health():
    # Always return 200 while the process is alive. Render health checks should
    # not restart a healthy process merely because Telegram/database startup is
    # still completing during a deploy.
    return jsonify(_status_payload()), 200


def mark_ready() -> None:
    global _ready, _stopping
    with _state_lock:
        _ready = True
        _stopping = False
    logger.info("Flask health server status: bot ready")


def mark_stopping() -> None:
    global _stopping
    with _state_lock:
        _stopping = True
    logger.info("Flask health server status: bot stopping")


def start_health_server() -> threading.Thread:
    """Start Flask once and return its daemon thread."""
    global _server_thread
    if _server_thread is not None and _server_thread.is_alive():
        return _server_thread
    port = int(os.getenv("PORT", "10000"))
    _server_thread = threading.Thread(
        target=lambda: app.run(
            host="0.0.0.0",
            port=port,
            debug=False,
            use_reloader=False,
            threaded=True,
        ),
        name="flask-health-server",
        daemon=True,
    )
    _server_thread.start()
    logger.info("Flask health server started on 0.0.0.0:%s", port)
    return _server_thread
