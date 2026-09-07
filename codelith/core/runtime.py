"""
Where the application is running, when that changes the advice it gives.

Only one question so far, and it earns its place because the answer changes what a
person should type: a model endpoint on the host is `localhost:1234` from a terminal
and `host.docker.internal:1234` from inside a container, and getting it wrong produces
a connection error that names neither.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def in_container() -> bool:
    """
    Whether this process is inside a container.

    Three signals, because none of them is universal. `/.dockerenv` is written by
    Docker itself; the cgroup path names the runtime under most of them; and the
    explicit variable is the escape hatch for whatever the first two miss, including
    Podman and anything the runtimes change next year.
    """
    if os.environ.get("CODELITH_IN_CONTAINER", "").strip().lower() in {"1", "true", "yes"}:
        return True
    if Path("/.dockerenv").exists():
        return True
    try:
        cgroup = Path("/proc/self/cgroup").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return any(marker in cgroup for marker in ("docker", "containerd", "kubepods", "podman"))


__all__ = ["in_container"]
