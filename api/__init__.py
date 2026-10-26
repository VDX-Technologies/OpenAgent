"""VDX OpenAgent HTTP API (FastAPI)."""

import re
import subprocess
from pathlib import Path

_FALLBACK = "0.4.2"  # used when not running from a git clone


def _git_version() -> str | None:
    """Nearest ``X.Y.Z`` release tag of the checked-out code, so a release only needs its tag."""
    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0", "--match", "*[0-9].*[0-9].*[0-9]"],
            cwd=Path(__file__).resolve().parent.parent, capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except Exception:
        return None
    return out.lstrip("v") if re.fullmatch(r"v?\d+\.\d+\.\d+", out) else None


def _newest(*versions: str | None) -> str:
    key = lambda v: tuple(int(x) for x in v.split("."))  # noqa: E731
    return max((v for v in versions if v), key=key)


__version__ = _newest(_FALLBACK, _git_version())
