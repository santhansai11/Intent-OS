"""System resource monitoring.

Uses psutil when installed; otherwise degrades gracefully with
platform-provided information so the kernel runs dependency-free.
"""
from __future__ import annotations

import os
import platform
from typing import Any, Dict

try:  # pragma: no cover - exercised only when psutil is present
    import psutil
except Exception:  # pragma: no cover
    psutil = None


def system_snapshot() -> Dict[str, Any]:
    """Best-effort snapshot of real machine resources."""
    data: Dict[str, Any] = {
        "platform": platform.system(),
        "cpu_count": os.cpu_count() or 1,
        "source": "fallback",
    }
    if psutil is not None:
        try:
            vm = psutil.virtual_memory()
            data.update(
                {
                    "source": "psutil",
                    "cpu_percent": psutil.cpu_percent(interval=None),
                    "memory_total_mb": round(vm.total / (1024 * 1024), 1),
                    "memory_used_mb": round(vm.used / (1024 * 1024), 1),
                    "memory_percent": vm.percent,
                }
            )
            return data
        except Exception:  # pragma: no cover
            pass
    # Fallback without psutil
    data.update({"cpu_percent": None, "memory_total_mb": None, "memory_used_mb": None})
    return data
