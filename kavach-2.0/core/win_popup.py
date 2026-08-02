"""Windows message box for operator launcher failures."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import sys

_POWERSHELL = (
    Path(os.environ.get("SystemRoot", r"C:\Windows"))
    / "System32"
    / "WindowsPowerShell"
    / "v1.0"
    / "powershell.exe"
)


def _escape_ps_single_quoted(text: str) -> str:
    return text.replace("'", "''")


def show_error_popup(title: str, message: str) -> None:
    """Modal error dialog (OK). No-op if alert mechanism unavailable."""
    print(f"\n*** ERROR: {title} ***\n{message}\n", file=sys.stderr)
    if sys.platform == "win32":
        if not _POWERSHELL.exists():
            return
        t = _escape_ps_single_quoted(title[:200])
        m = _escape_ps_single_quoted(message[:1500])
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            f"[void][System.Windows.Forms.MessageBox]::Show('{m}','{t}',"
            "[System.Windows.Forms.MessageBoxButtons]::OK,"
            "[System.Windows.Forms.MessageBoxIcon]::Error)"
        )
        subprocess.run(
            [str(_POWERSHELL), "-NoProfile", "-Sta", "-Command", script],
            check=False,
        )
    else:
        try:
            subprocess.run(["notify-send", f"ERROR: {title}", message], capture_output=True, check=False)
        except Exception:
            pass


def show_info_popup(title: str, message: str) -> None:
    print(f"\n*** INFO: {title} ***\n{message}\n")
    if sys.platform == "win32":
        if not _POWERSHELL.exists():
            return
        t = _escape_ps_single_quoted(title[:200])
        m = _escape_ps_single_quoted(message[:1500])
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            f"[void][System.Windows.Forms.MessageBox]::Show('{m}','{t}',"
            "[System.Windows.Forms.MessageBoxButtons]::OK,"
            "[System.Windows.Forms.MessageBoxIcon]::Information)"
        )
        subprocess.run(
            [str(_POWERSHELL), "-NoProfile", "-Sta", "-Command", script],
            check=False,
        )
    else:
        try:
            subprocess.run(["notify-send", f"INFO: {title}", message], capture_output=True, check=False)
        except Exception:
            pass

