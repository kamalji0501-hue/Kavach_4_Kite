"""Watch ``access_token.json`` and hot-reload the KAVACH broker when DRISHTI saves a new JWT."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

from core.token_store import TokenStore

logger = logging.getLogger("batman.token_watch")


def start_token_watch(
    broker,
    *,
    client_code: str,
    token_path: Path,
    poll_seconds: float = 30.0,
    on_token_ready: Callable[[str], None] | None = None,
) -> threading.Event:
    """Background daemon thread — returns stop event for clean shutdown.

    When *broker* is ``None`` and *on_token_ready* is set, invokes the callback once
    a valid token appears (lazy KAVACH bootstrap after DRISHTI saves JWT).
    """
    stop = threading.Event()
    token_path = Path(token_path)

    def _loop() -> None:
        store = TokenStore(path=token_path)
        last_mtime = token_path.stat().st_mtime if token_path.exists() else 0.0
        bootstrap_attempted = False

        if broker is None and on_token_ready is not None and token_path.exists():
            token, saved_at = store.load()
            if token and not store.is_effectively_expired():
                bootstrap_attempted = True
                try:
                    on_token_ready(token)
                except Exception as exc:
                    bootstrap_attempted = False
                    logger.error("Token bootstrap callback failed: %s", exc)

        while not stop.wait(timeout=poll_seconds):
            if not token_path.exists():
                continue
            try:
                mtime = token_path.stat().st_mtime
            except OSError:
                continue
            if mtime <= last_mtime:
                continue
            last_mtime = mtime
            token, saved_at = store.load()
            if not token or store.is_effectively_expired():
                logger.warning(
                    "Token file changed but token missing/expired (saved_at=%s)", saved_at
                )
                continue

            if broker is None and on_token_ready is not None and not bootstrap_attempted:
                bootstrap_attempted = True
                try:
                    on_token_ready(token)
                except Exception as exc:
                    bootstrap_attempted = False
                    logger.error("Token bootstrap callback failed: %s", exc)
                continue

            if broker is None or not client_code:
                continue

            try:
                broker.hot_reload_token(client_code, token)
                logger.info("KAVACH broker hot-reloaded from token file (saved_at=%s)", saved_at)
            except Exception as exc:
                logger.error("Token hot-reload failed: %s", exc)

    threading.Thread(target=_loop, daemon=True, name="token-watch").start()
    return stop
