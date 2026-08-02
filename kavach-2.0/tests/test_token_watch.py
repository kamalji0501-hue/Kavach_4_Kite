"""Tests for token_watch lazy bootstrap."""

from __future__ import annotations

import time
from pathlib import Path

from core.token_store import TokenStore
from core.token_watch import start_token_watch


def test_token_watch_bootstrap_on_existing_token(tmp_path: Path) -> None:
    token_path = tmp_path / "access_token.json"
    store = TokenStore(path=token_path)
    store.save("dummy.jwt.token")

    bootstrapped: list[str] = []

    def on_ready(token: str) -> None:
        bootstrapped.append(token)

    stop = start_token_watch(
        None,
        client_code="1106926362",
        token_path=token_path,
        poll_seconds=0.05,
        on_token_ready=on_ready,
    )
    time.sleep(0.3)
    stop.set()
    assert len(bootstrapped) == 1
    assert bootstrapped[0] == "dummy.jwt.token"
