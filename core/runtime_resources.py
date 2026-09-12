"""Local capacity detection and cross-process admission control for ASTRA."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
import uuid
from typing import Optional


def _positive_int(value, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, parsed)


def _pid_alive(pid: int) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def detect_compute_capacity() -> dict:
    """Return host and process-visible CPU/memory capacity without mutating it."""
    logical_host = _positive_int(os.cpu_count(), 1)
    logical_available = logical_host
    affinity = None
    physical = None
    memory_bytes = None

    try:
        affinity = sorted(os.sched_getaffinity(0))
        logical_available = max(1, len(affinity))
    except (AttributeError, OSError):
        pass

    try:
        import psutil

        physical = psutil.cpu_count(logical=False)
        process_affinity = psutil.Process().cpu_affinity()
        if process_affinity:
            affinity = sorted(process_affinity)
            logical_available = max(1, len(affinity))
        memory_bytes = int(psutil.virtual_memory().total)
    except Exception:
        pass

    if not physical:
        physical = max(1, logical_available // 2)
    physical = min(int(physical), logical_available)

    return {
        "logical_cpus_host": logical_host,
        "logical_cpus_available": logical_available,
        "physical_cores_estimate": physical,
        "cpu_affinity": affinity,
        "memory_bytes": memory_bytes,
    }


def recommended_parallelism(capacity: Optional[dict] = None) -> dict:
    """Plan conservative parallelism and avoid nested BLAS oversubscription."""
    capacity = dict(capacity or detect_compute_capacity())
    logical = _positive_int(capacity.get("logical_cpus_available"), 1)
    physical = _positive_int(capacity.get("physical_cores_estimate"), 1)
    reserve = 1 if logical > 2 else 0
    detected_local = max(1, min(4, physical - reserve))
    override = os.environ.get("ASTRA_LOCAL_WORKERS")
    local_workers = (
        min(logical, _positive_int(override, detected_local))
        if override
        else detected_local
    )
    return {
        "deliberative_cycles": _positive_int(
            os.environ.get("ASTRA_MAX_CONCURRENT_CYCLES"), 1
        ),
        "local_scientific_workers": local_workers,
        "io_workers": max(2, min(16, logical * 2)),
        "recommended_blas_threads_per_worker": max(
            1, logical // max(1, local_workers)
        ),
        "policy": (
            "One full deliberative cycle per model-account set; parallelize "
            "independent local validators and benchmark cases."
        ),
    }


@dataclass
class CycleSlot:
    path: Path
    token: str
    holder: dict

    def release(self) -> None:
        try:
            current = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            current = {}
        if current.get("token") != self.token:
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def _read_holder(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def cycle_lock_root(root: Path) -> Path:
    """Directory holding the deliberative-cycle locks.

    The slot exists to enforce one deliberation per *model-account set*, but
    it used to live under ``<checkout>/workspace/locks``, so two checkouts
    sharing one subscription — this line and the ASTRA 2.0 development line —
    held different locks and could deliberate simultaneously against the same
    account.  Inside a single checkout the lock worked; across checkouts there
    was no mutual exclusion at all, and the resulting quota contention
    surfaces as operational errors that contaminate any measurement.
    Ported from the 2.0 line on 2026-08-13.

    The default is therefore machine-wide.  ``ASTRA_LOCK_ROOT`` overrides it,
    which is also how a line running on a *different* account can be isolated
    on purpose: separate credentials, separate lock root.
    """
    configured = (os.environ.get("ASTRA_LOCK_ROOT") or "").strip().strip("'\"")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "astra" / "locks"
    base = os.environ.get("XDG_CACHE_HOME")
    if base:
        return Path(base) / "astra" / "locks"
    return Path.home() / ".cache" / "astra" / "locks"


def acquire_cycle_slot(root: Path, max_slots: int = 1) -> tuple:
    """Atomically acquire one deliberative-cycle slot across MCP processes.

    ``root`` is kept for callers and for the fallback below; the lock itself
    is machine-wide by default (see :func:`cycle_lock_root`).
    """
    slots = max(1, int(max_slots))
    try:
        lock_root = cycle_lock_root(Path(root))
        lock_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        # An unwritable machine-wide directory must not disable the slot:
        # fall back to the historical per-checkout location.
        lock_root = Path(root).resolve() / "workspace" / "locks"
        lock_root.mkdir(parents=True, exist_ok=True)
    active = []

    for index in range(slots):
        path = lock_root / f"deliberative_cycle_{index}.lock"
        for _attempt in range(2):
            token = uuid.uuid4().hex
            holder = {
                "pid": os.getpid(),
                "token": token,
                "slot": index,
                "created_ts": time.time(),
            }
            try:
                fd = os.open(
                    str(path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
            except FileExistsError:
                existing = _read_holder(path)
                if existing and _pid_alive(existing.get("pid", -1)):
                    active.append(existing)
                    break
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(holder, stream)
            return CycleSlot(path=path, token=token, holder=holder), active

    return None, active
