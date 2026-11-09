"""
Tool · Apple Shortcuts
======================
List and run the user's Shortcuts (``shortcuts`` CLI, macOS 12+), so anything
already automated in the Shortcuts app becomes something VDX can do.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


def _cli(*args: str, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["shortcuts", *args], capture_output=True, text=True, timeout=timeout)


def list_shortcuts() -> str:
    """Names of the user's shortcuts."""
    try:
        r = _cli("list")
    except FileNotFoundError:
        return "Error: the shortcuts command needs macOS 12 or later."
    except subprocess.TimeoutExpired:
        return "Error: Shortcuts did not answer."
    if r.returncode:
        return f"Error: {r.stderr.strip() or 'could not list shortcuts'}"
    return r.stdout.strip() or "No shortcuts found."


def run_shortcut(name: str, input: str = "") -> str:
    """Run a shortcut by name, optionally passing text input; returns its text output."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.txt"
        args = ["run", name, "--output-path", str(out), "--output-type", "public.plain-text"]
        if input:
            src = Path(tmp) / "in.txt"
            src.write_text(input, encoding="utf-8")
            args += ["--input-path", str(src)]
        try:
            r = _cli(*args, timeout=180)
        except FileNotFoundError:
            return "Error: the shortcuts command needs macOS 12 or later."
        except subprocess.TimeoutExpired:
            return f"Error: shortcut '{name}' took longer than 3 minutes."
        if r.returncode:
            return f"Error running '{name}': {r.stderr.strip() or 'failed'}"
        text = out.read_text(encoding="utf-8", errors="replace").strip() if out.exists() else ""
    return f"Shortcut '{name}' ran." + (f" Output:\n{text[:6000]}" if text else "")


TOOL_DESCRIPTORS = [
    {"name": "list_shortcuts", "description": "List the user's Apple Shortcuts.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "run_shortcut", "description": "Run one of the user's Apple Shortcuts by exact name, with optional text input.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "input": {"type": "string"}},
                    "required": ["name"]}},
]

TOOLS = {"list_shortcuts": list_shortcuts, "run_shortcut": run_shortcut}
