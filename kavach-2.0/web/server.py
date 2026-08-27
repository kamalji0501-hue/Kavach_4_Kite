"""Bind uvicorn for the Kavach web desk. Default 0.0.0.0:8789."""

from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger("batman.kavach.web.server")


def _bind() -> tuple[str, int]:
    host = (os.environ.get("KAVACH_WEB_HOST") or "0.0.0.0").strip() or "0.0.0.0"
    port = int((os.environ.get("KAVACH_WEB_PORT") or "8789").strip() or "8789")
    return host, port


def start_web_thread() -> threading.Thread:
    import uvicorn

    from web.app import create_app

    host, port = _bind()
    app = create_app()
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
        loop="asyncio",
    )
    server = uvicorn.Server(config)

    def _run() -> None:
        logger.info("Kavach web desk listening on http://%s:%s", host, port)
        server.run()

    t = threading.Thread(target=_run, daemon=True, name="kavach-web")
    t.start()
    return t
