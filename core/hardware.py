"""
Core · Hardware Profile & Model Recommendations
===============================================
Detects the host machine (chip, RAM, cores, free disk) using the
stdlib + ``sysctl`` and suggests Ollama models that fit comfortably.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from typing import Any

# Curated catalogue. ``min_ram`` is total system RAM (GB) needed to run the
# default Q4 quant with headroom for macOS + browser; ``size_gb`` is download size.
CATALOG: list[dict[str, Any]] = [
    {"name": "llama3.2:3b", "size_gb": 2.0, "min_ram": 8, "tags": ["fast", "tools"],
     "desc": "Tiny and quick. Good for simple commands on 8 GB Macs."},
    {"name": "qwen2.5:3b", "size_gb": 1.9, "min_ram": 8, "tags": ["fast", "tools"],
     "desc": "Small Qwen with solid tool-calling for its size."},
    {"name": "qwen2.5:7b", "size_gb": 4.7, "min_ram": 16, "tags": ["tools", "default"],
     "desc": "VDX default. Best balance of speed and reliable tool use."},
    {"name": "llama3.1:8b", "size_gb": 4.9, "min_ram": 16, "tags": ["tools"],
     "desc": "Meta's 8B all-rounder with native function calling."},
    {"name": "qwen2.5-coder:7b", "size_gb": 4.7, "min_ram": 16, "tags": ["code", "tools"],
     "desc": "Tuned for code. Pair with the Code connector."},
    {"name": "qwen3:8b", "size_gb": 5.2, "min_ram": 16, "tags": ["tools", "reasoning"],
     "desc": "Newer Qwen with thinking mode and tool support."},
    {"name": "qwen2.5:14b", "size_gb": 9.0, "min_ram": 24, "tags": ["tools", "smart"],
     "desc": "Noticeably smarter multi-step planning."},
    {"name": "qwen2.5-coder:14b", "size_gb": 9.0, "min_ram": 24, "tags": ["code", "tools"],
     "desc": "Stronger coding agent for real repos."},
    {"name": "mistral-small:24b", "size_gb": 14.0, "min_ram": 32, "tags": ["tools", "smart"],
     "desc": "Fast 24B with excellent function calling."},
    {"name": "qwen2.5:32b", "size_gb": 20.0, "min_ram": 48, "tags": ["tools", "smart"],
     "desc": "Near-frontier quality for a local model."},
    {"name": "qwen2.5-coder:32b", "size_gb": 20.0, "min_ram": 48, "tags": ["code", "tools"],
     "desc": "Best open coder in this list."},
    {"name": "llama3.3:70b", "size_gb": 43.0, "min_ram": 64, "tags": ["tools", "smart"],
     "desc": "Big and capable. Needs a 64 GB+ machine."},
]


def _sysctl(key: str) -> str:
    """Read a ``sysctl`` value (macOS/BSD); empty string on failure."""
    try:
        out = subprocess.run(["sysctl", "-n", key], capture_output=True, text=True, timeout=3)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _ram_bytes() -> int:
    """Total physical memory in bytes."""
    if platform.system() == "Darwin":
        v = _sysctl("hw.memsize")
        if v.isdigit():
            return int(v)
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return 0


def system_profile() -> dict[str, Any]:
    """Return a snapshot of the host hardware relevant for running LLMs."""
    system = platform.system()
    machine = platform.machine()
    chip = _sysctl("machdep.cpu.brand_string") if system == "Darwin" else platform.processor()
    apple_silicon = system == "Darwin" and machine == "arm64"
    perf = _sysctl("hw.perflevel0.physicalcpu") if apple_silicon else ""
    eff = _sysctl("hw.perflevel1.physicalcpu") if apple_silicon else ""
    disk = shutil.disk_usage(os.path.expanduser("~"))
    return {
        "os": f"macOS {platform.mac_ver()[0]}" if system == "Darwin" else f"{system} {platform.release()}",
        "machine": machine,
        "model": _sysctl("hw.model") if system == "Darwin" else "",
        "chip": chip or machine,
        "apple_silicon": apple_silicon,
        "cpu_cores": os.cpu_count() or 0,
        "perf_cores": int(perf) if perf.isdigit() else None,
        "efficiency_cores": int(eff) if eff.isdigit() else None,
        "ram_gb": round(_ram_bytes() / 1024**3),
        "disk_free_gb": round(disk.free / 1024**3),
        "disk_total_gb": round(disk.total / 1024**3),
    }


def recommend(profile: dict[str, Any], installed: list[str]) -> list[dict[str, Any]]:
    """Rate every catalogue model for this machine.

    Each item gets ``fit`` ∈ {``great``, ``ok``, ``too_big``}, ``installed``
    and ``recommended`` (the best general + best code model that fit well).
    """
    ram = profile.get("ram_gb") or 0
    # Unified memory on Apple Silicon is shared with the GPU; Intel/PC is
    # usually CPU-only so be more conservative.
    budget = ram if profile.get("apple_silicon") else ram * 0.75
    have = {n.split(":latest")[0] for n in installed} | set(installed)

    items = []
    for m in CATALOG:
        if budget >= m["min_ram"]:
            fit = "great"
        elif budget >= m["min_ram"] * 0.7 and m["size_gb"] < ram * 0.6:
            fit = "ok"
        else:
            fit = "too_big"
        items.append({**m, "fit": fit, "installed": m["name"] in have, "recommended": False})

    great = [i for i in items if i["fit"] == "great"]
    for tag in ("code",):
        best = max((i for i in great if tag in i["tags"]), key=lambda i: i["min_ram"], default=None)
        if best:
            best["recommended"] = True
    general = max((i for i in great if "code" not in i["tags"]), key=lambda i: i["min_ram"], default=None)
    if general:
        general["recommended"] = True
    return items
