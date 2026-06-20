#!/usr/bin/env python3
"""gpu-warden — tells the llm-gateway whether the gaming GPU is free for inference.

  GET /status -> {"available": bool, "reason": str, "gpu_util": float|None,
                  "games": [..], "idle_min": float}

`available` is False while you are gaming, where "gaming" means either:
  * one of your configured game processes is running (WARDEN_GAME_PROCESSES), or
  * the GPU 3D-engine utilization is at/above WARDEN_GPU_BUSY_PCT.

Optional reclaim (off by default): if a listed game is running but you have been
idle for WARDEN_RECLAIM_IDLE_MIN minutes, the warden will close it to free the GPU.
This can lose unsaved progress — opt in per game via WARDEN_GAME_PROCESSES only.

Bind to the tailnet; there is no auth. Windows only (uses Win32 idle + tasklist).
"""
from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
from ctypes import wintypes

import psutil
from fastapi import FastAPI

BUSY_PCT = float(os.environ.get("WARDEN_GPU_BUSY_PCT", "25"))
GAMES = [p.strip().lower() for p in os.environ.get("WARDEN_GAME_PROCESSES", "").split(",") if p.strip()]
RECLAIM = os.environ.get("WARDEN_RECLAIM_IDLE", "0") == "1"
RECLAIM_MIN = float(os.environ.get("WARDEN_RECLAIM_IDLE_MIN", "20"))

app = FastAPI(title="gpu-warden")


def idle_minutes() -> float:
    """Minutes since the last keyboard/mouse input (Win32 GetLastInputInfo)."""
    class LastInput(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LastInput()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    millis = ctypes.windll.kernel32.GetTickCount() - info.dwTime
    return max(0.0, millis / 60000.0)


def gpu_util() -> float | None:
    """Best-effort AMD GPU utilization %. None if no tool is available."""
    for tool, args in (("amd-smi", ["metric", "-g", "0", "--usage"]), ("rocm-smi", ["--showuse"])):
        exe = shutil.which(tool)
        if not exe:
            continue
        try:
            out = subprocess.run([exe, *args], capture_output=True, text=True, timeout=5).stdout
        except Exception:
            continue
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", out)
        if m:
            return float(m.group(1))
    return None


def running_games() -> list[str]:
    if not GAMES:
        return []
    found = set()
    for proc in psutil.process_iter(["name"]):
        name = (proc.info.get("name") or "").lower()
        if name in GAMES:
            found.add(name)
    return sorted(found)


def reclaim(games: list[str]) -> bool:
    """Close listed games to free the GPU. Returns True if anything was closed."""
    closed = False
    for proc in psutil.process_iter(["name"]):
        if (proc.info.get("name") or "").lower() in games:
            try:
                proc.terminate()
                closed = True
            except Exception:
                pass
    return closed


@app.get("/status")
def status() -> dict:
    games = running_games()
    util = gpu_util()
    idle = idle_minutes()
    busy_by_gpu = util is not None and util >= BUSY_PCT

    if games and RECLAIM and idle >= RECLAIM_MIN:
        if reclaim(games):
            games = []  # reclaimed; GPU is now ours

    available = not (games or busy_by_gpu)
    if games:
        reason = f"game running: {', '.join(games)}"
    elif busy_by_gpu:
        reason = f"gpu busy {util:.0f}% >= {BUSY_PCT:.0f}%"
    else:
        reason = "free"
    return {
        "available": available,
        "reason": reason,
        "gpu_util": util,
        "games": games,
        "idle_min": round(idle, 1),
    }


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "games_watched": GAMES, "busy_pct": BUSY_PCT, "reclaim": RECLAIM}
