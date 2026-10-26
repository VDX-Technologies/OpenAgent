"""
Tool · AppleScript helpers
==========================
Shared `osascript` runner and string escaping for the macOS connectors.
"""

from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)


def esc(value: str) -> str:
    """Escape a Python string for safe embedding in an AppleScript string literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def run_applescript(script: str, timeout: int = 30) -> str:
    """Execute an AppleScript snippet and return stdout (or an ``Error: …`` string)."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "Error: AppleScript execution timed out."
    except FileNotFoundError:
        return "Error: osascript not found. This tool requires macOS."
    if result.returncode != 0:
        logger.error("AppleScript error: %s", result.stderr.strip())
        return f"Error: {result.stderr.strip()}"
    return result.stdout.strip()
