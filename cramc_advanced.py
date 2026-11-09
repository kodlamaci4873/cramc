#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Advanced telemetry, process inspection, health hints and report export for CRAMC.

This module is intentionally independent from the cleanup engine. Monitoring
never initiates cleanup. Process exit is graceful, user-confirmed and limited
to processes owned by the current desktop account.
"""
from __future__ import annotations

import csv
import getpass
import json
import math
import os
import platform
import socket
import tempfile
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Deque, Iterable, Optional

try:
    import psutil
except Exception:
    psutil = None

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except Exception:
    tk = filedialog = messagebox = ttk = None

MODULE_VERSION = "1.0.0"
MAX_HISTORY_POINTS = 360
MAX_PROCESSES = 2500
MAX_EXPORT_PROCESSES = 5000
DEFAULT_SAMPLE_INTERVAL = 2.5


@dataclass
class SystemSample:
    timestamp: float
    cpu_percent: float = 0.0
    cpu_count: int = 0
    memory_total: int = 0
    memory_used: int = 0
    memory_available: int = 0
    memory_percent: float = 0.0
    swap_total: int = 0
    swap_used: int = 0
    swap_percent: float = 0.0
    disk_total: int = 0
    disk_used: int = 0
    disk_percent: float = 0.0
    disk_read_bytes: int = 0
    disk_write_bytes: int = 0
    net_sent_bytes: int = 0
    net_recv_bytes: int = 0
    load_1m: Optional[float] = None
    load_5m: Optional[float] = None
    load_15m: Optional[float] = None
    boot_time: Optional[float] = None
    hostname: str = ""
    platform: str = ""
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key, value in tuple(result.items()):
            if isinstance(value, float) and not math.isfinite(value):
                result[key] = None
        return result


@dataclass
class ProcessRecord:
    pid: int
    name: str
    username: str
    status: str
    cpu_percent: float
    memory_rss: int
    memory_percent: float
    threads: int
    created: Optional[float]
    executable: str = ""
    accessible: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ActionResult:
    ok: bool
    message: str
    pid: Optional[int] = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthFinding:
    severity: str
    code: str
    title: str
    detail: str
    recommendation: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _safe_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def format_bytes(value: int) -> str:
    number = float(max(0, int(value)))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if number < 1024 or unit == "TB":
            return f"{int(number)} B" if unit == "B" else f"{number:.1f} {unit}"
        number /= 1024
    return f"{number:.1f} TB"


def format_rate(value: float) -> str:
    return f"{format_bytes(max(0, int(value)))}/s"


def _current_owner() -> str:
    if psutil is not None:
        try:
            return psutil.Process(os.getpid()).username()
        except Exception:
            pass
    try:
        return getpass.getuser()
    except Exception:
        return ""


def _same_owner(first: str, second: str) -> bool:
    return first.casefold() == second.casefold() if os.name == "nt" else first == second


def _protected_name(name: str) -> bool:
    value = (name or "").strip().casefold()
    protected = {
        "system", "system idle process", "registry", "smss.exe", "csrss.exe",
        "wininit.exe", "services.exe", "lsass.exe", "winlogon.exe", "explorer.exe",
        "init", "systemd", "kthreadd", "ksoftirqd", "launchd",
    }
    return value in protected or value.startswith("kworker/")


class SystemProbe:
    """Best-effort cross-platform sensor and process reader."""

    def __init__(self, disk_path: Optional[str] = None):
        self.disk_path = disk_path or (
            os.environ.get("SystemDrive", "C:") + "\\" if os.name == "nt" else "/"
        )
        self._lock = threading.RLock()

    @property
    def available(self) -> bool:
        return psutil is not None

    def sample(self) -> SystemSample:
        now = time.time()
        result = SystemSample(timestamp=now, hostname=socket.gethostname(),
                              platform=platform.platform(), cpu_count=os.cpu_count() or 0)
        if psutil is None:
            result.errors.append("psutil is not installed; detailed telemetry is unavailable")
            if hasattr(os, "getloadavg"):
                try:
                    result.load_1m, result.load_5m, result.load_15m = os.getloadavg()
                except OSError:
                    pass
            return result
        with self._lock:
            self._read_cpu(result)
            self._read_memory(result)
            self._read_swap(result)
            self._read_disk(result)
            self._read_network(result)
            self._read_load(result)
            try:
                result.boot_time = float(psutil.boot_time())
            except Exception as exc:
                result.errors.append(f"boot time: {type(exc).__name__}")
        return result

    def _read_cpu(self, sample: SystemSample) -> None:
        try:
            sample.cpu_percent = float(psutil.cpu_percent(interval=None))
            sample.cpu_count = int(psutil.cpu_count(logical=True) or 0)
        except Exception as exc:
            sample.errors.append(f"cpu: {type(exc).__name__}")

    def _read_memory(self, sample: SystemSample) -> None:
        try:
            memory = psutil.virtual_memory()
            sample.memory_total = int(memory.total)
            sample.memory_used = int(memory.used)
            sample.memory_available = int(memory.available)
            sample.memory_percent = float(memory.percent)
        except Exception as exc:
            sample.errors.append(f"memory: {type(exc).__name__}")

    def _read_swap(self, sample: SystemSample) -> None:
        try:
            swap = psutil.swap_memory()
            sample.swap_total = int(swap.total)
            sample.swap_used = int(swap.used)
            sample.swap_percent = float(swap.percent)
        except Exception as exc:
            sample.errors.append(f"swap: {type(exc).__name__}")

    def _read_disk(self, sample: SystemSample) -> None:
        try:
            usage = psutil.disk_usage(self.disk_path)
            sample.disk_total = int(usage.total)
            sample.disk_used = int(usage.used)
            sample.disk_percent = float(usage.percent)
        except Exception as exc:
            sample.errors.append(f"disk usage: {type(exc).__name__}")
        try:
            counters = psutil.disk_io_counters()
            if counters:
                sample.disk_read_bytes = int(counters.read_bytes)
                sample.disk_write_bytes = int(counters.write_bytes)
        except Exception as exc:
            sample.errors.append(f"disk io: {type(exc).__name__}")

    def _read_network(self, sample: SystemSample) -> None:
        try:
            counters = psutil.net_io_counters()
            if counters:
                sample.net_sent_bytes = int(counters.bytes_sent)
                sample.net_recv_bytes = int(counters.bytes_recv)
        except Exception as exc:
            sample.errors.append(f"network: {type(exc).__name__}")

    def _read_load(self, sample: SystemSample) -> None:
        try:
            if hasattr(os, "getloadavg"):
                sample.load_1m, sample.load_5m, sample.load_15m = (
                    float(value) for value in os.getloadavg()
                )
        except (OSError, ValueError):
            pass

    def processes(self, limit: int = MAX_PROCESSES) -> list[ProcessRecord]:
        if psutil is None:
            return []
        limit = max(1, min(int(limit), MAX_PROCESSES))
        rows: list[ProcessRecord] = []
        attrs = ["pid", "name", "username", "status", "cpu_percent", "memory_info",
                 "memory_percent", "num_threads", "create_time", "exe"]
        try:
            for proc in psutil.process_iter(attrs=attrs, ad_value=None):
                try:
                    info = proc.info
                    pid = int(info.get("pid") or 0)
                    if pid <= 0:
                        continue
                    memory = info.get("memory_info")
                    rows.append(ProcessRecord(
                        pid=pid, name=str(info.get("name") or "(unknown)"),
                        username=str(info.get("username") or ""),
                        status=str(info.get("status") or "unknown"),
                        cpu_percent=max(0.0, float(info.get("cpu_percent") or 0.0)),
                        memory_rss=max(0, int(getattr(memory, "rss", 0) or 0)),
                        memory_percent=max(0.0, float(info.get("memory_percent") or 0.0)),
                        threads=max(0, int(info.get("num_threads") or 0)),
                        created=_safe_float(info.get("create_time")),
                        executable=str(info.get("exe") or ""),
                        accessible=bool(info.get("name")),
                    ))
                except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied):
                    continue
                except (TypeError, ValueError, OSError):
                    continue
                if len(rows) >= limit:
                    break
        except Exception:
            return rows
        rows.sort(key=lambda item: item.memory_rss, reverse=True)
        return rows

    def terminate_user_process(self, pid: int, timeout: float = 2.0) -> ActionResult:
        """Request graceful exit; never escalates to a forced kill."""
        if psutil is None:
            return ActionResult(False, "psutil is unavailable")
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            return ActionResult(False, "invalid process id")
        if pid <= 1:
            return ActionResult(False, "system process is protected", pid)
        if pid == os.getpid():
            return ActionResult(False, "the CRAMC process is protected", pid)
        try:
            process = psutil.Process(pid)
            owner = process.username()
            allowed = _current_owner()
            if not owner or not allowed or not _same_owner(owner, allowed):
                return ActionResult(False, "process is not owned by the current desktop user",
                                    pid, {"owner": owner or "unknown"})
            name = process.name()
            if _protected_name(name):
                return ActionResult(False, "protected system process", pid, {"name": name})
            process.terminate()
            try:
                process.wait(timeout=max(0.1, min(float(timeout), 10.0)))
                return ActionResult(True, f"{name} exited gracefully", pid, {"owner": owner})
            except psutil.TimeoutExpired:
                return ActionResult(False, "process did not exit; no forced kill was attempted",
                                    pid, {"owner": owner, "name": name})
        except psutil.NoSuchProcess:
            return ActionResult(False, "process no longer exists", pid)
        except psutil.AccessDenied:
            return ActionResult(False, "permission denied", pid)
        except Exception as exc:
            return ActionResult(False, f"{type(exc).__name__}: {exc}", pid)


class HistoryBuffer:
    """Thread-safe bounded history for live charts and diagnostic summaries."""

    def __init__(self, max_points: int = MAX_HISTORY_POINTS):
        self.max_points = max(2, min(int(max_points), 5000))
        self._items: Deque[SystemSample] = deque(maxlen=self.max_points)
        self._lock = threading.RLock()

    def add(self, sample: SystemSample) -> None:
        if not isinstance(sample, SystemSample):
            raise TypeError("HistoryBuffer accepts SystemSample instances")
        with self._lock:
            if self._items and sample.timestamp < self._items[-1].timestamp:
                sample = SystemSample(**{**sample.to_dict(),
                                         "timestamp": self._items[-1].timestamp})
            self._items.append(sample)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def samples(self) -> list[SystemSample]:
        with self._lock:
            return list(self._items)

    def series(self, field_name: str, limit: int = 120) -> list[tuple[float, float]]:
        allowed = {"cpu_percent", "memory_percent", "disk_percent", "swap_percent"}
        if field_name not in allowed:
            raise ValueError("unsupported history field")
        limit = max(2, int(limit))
        with self._lock:
            items = list(self._items)
        if len(items) > limit:
            stride = (len(items) - 1) / (limit - 1)
            items = [items[round(index * stride)] for index in range(limit)]
        result = []
        for item in items:
            value = _safe_float(getattr(item, field_name, None))
            if value is not None:
                result.append((item.timestamp, max(0.0, min(100.0, value))))
        return result

    def summary(self, field_name: str) -> dict[str, Optional[float]]:
        values = [value for _, value in self.series(field_name, self.max_points)]
        if not values:
            return {"min": None, "max": None, "average": None, "latest": None}
        return {"min": min(values), "max": max(values),
                "average": sum(values) / len(values), "latest": values[-1]}

    def to_list(self) -> list[dict[str, Any]]:
        return [sample.to_dict() for sample in self.samples()]


def analyze_health(sample: SystemSample) -> list[HealthFinding]:
    """Return advisory findings only; this function never changes system state."""
    findings: list[HealthFinding] = []
    if sample.memory_total > 0:
        if sample.memory_percent >= 95:
            findings.append(HealthFinding("critical", "memory_critical", "Very high memory use",
                f"Memory usage is {sample.memory_percent:.1f}%.",
                "Review the process list and close only applications you recognize."))
        elif sample.memory_percent >= 85:
            findings.append(HealthFinding("warning", "memory_high", "High memory use",
                f"Memory usage is {sample.memory_percent:.1f}%.",
                "Check memory-heavy applications; cache alone is not necessarily waste."))
    if sample.swap_total > 0 and sample.swap_percent >= 80:
        findings.append(HealthFinding("warning", "swap_high", "High swap use",
            f"Swap usage is {sample.swap_percent:.1f}%.",
            "Look for sustained memory pressure before changing swap settings."))
    if sample.disk_total > 0:
        if sample.disk_percent >= 97:
            findings.append(HealthFinding("critical", "disk_critical", "Disk nearly full",
                f"Monitored volume is {sample.disk_percent:.1f}% full.",
                "Review personal files and backups; avoid deleting system folders."))
        elif sample.disk_percent >= 90:
            findings.append(HealthFinding("warning", "disk_high", "Low disk space",
                f"Monitored volume is {sample.disk_percent:.1f}% full.",
                "Inspect storage usage and remove only files you no longer need."))
    if sample.cpu_percent >= 95:
        findings.append(HealthFinding("warning", "cpu_saturated", "CPU is heavily loaded",
            f"CPU usage is {sample.cpu_percent:.1f}%.",
            "Sort processes by CPU and check whether the load is expected."))
    if not findings:
        findings.append(HealthFinding("ok", "system_ok", "No urgent resource warning",
            "The latest sample did not cross CRAMC's advisory thresholds.",
            "Continue monitoring; this is not a full hardware diagnostic."))
    return findings


def build_report(sample: SystemSample, processes: Iterable[ProcessRecord],
                 history: Optional[HistoryBuffer] = None) -> dict[str, Any]:
    rows = list(processes)[:MAX_EXPORT_PROCESSES]
    return {
        "schema": "cramc-system-report",
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "application": {"name": "ComputerRAMCleaner", "module_version": MODULE_VERSION},
        "system": sample.to_dict(),
        "health": [finding.to_dict() for finding in analyze_health(sample)],
        "processes": [row.to_dict() for row in rows],
        "history": history.to_list() if history is not None else [],
        "privacy": {"command_line_arguments_included": False,
                    "environment_variables_included": False,
                    "file_contents_included": False},
    }


def export_report(path: str | os.PathLike[str], sample: SystemSample,
                  processes: Iterable[ProcessRecord],
                  history: Optional[HistoryBuffer] = None) -> ActionResult:
    """Atomically write a JSON system report or CSV process list."""
    destination = Path(path).expanduser()
    suffix = destination.suffix.casefold()
    if suffix not in {".json", ".csv"}:
        return ActionResult(False, "Choose a .json or .csv report file")
    rows = list(processes)[:MAX_EXPORT_PROCESSES]
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.",
            suffix=".tmp", dir=str(destination.parent), text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                if suffix == ".json":
                    json.dump(build_report(sample, rows, history), stream,
                              ensure_ascii=False, indent=2, allow_nan=False)
                    stream.write("\n")
                else:
                    fields = ["pid", "name", "username", "status", "cpu_percent",
                              "memory_rss", "memory_percent", "threads", "created",
                              "executable", "accessible"]
                    writer = csv.DictWriter(stream, fieldnames=fields)
                    writer.writeheader()
                    for row in rows:
                        writer.writerow(row.to_dict())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        return ActionResult(True, f"Report saved: {destination}",
                            details={"path": str(destination)})
    except Exception as exc:
        return ActionResult(False, f"Could not export report: {type(exc).__name__}: {exc}")


def _clamp_percent(value: float) -> float:
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


class ProcessMonitorFrame(ttk.Frame if ttk is not None else object):
    """Live Tk dashboard. All widget updates run on Tk's main thread."""

    def __init__(self, parent: Any, translator: Callable[[str], str] = lambda value: value,
                 on_log: Optional[Callable[[str, str], None]] = None,
                 sample_interval: float = DEFAULT_SAMPLE_INTERVAL):
        if ttk is None or tk is None:
            raise RuntimeError("Tkinter is unavailable")
        super().__init__(parent)
        self._ = translator
        self._on_log = on_log or (lambda level, message: None)
        self.probe = SystemProbe()
        self.history = HistoryBuffer()
        self.sample_interval = max(1.0, min(float(sample_interval), 30.0))
        self._after_id = None
        self._destroyed = False
        self._refreshing = False
        self._sample: Optional[SystemSample] = None
        self._processes: list[ProcessRecord] = []
        self._sort_key = "memory"
        self._sort_reverse = True
        self._last_alert_codes: set[str] = set()
        self._filter = tk.StringVar(value="")
        self._status = tk.StringVar(value=self._("Preparing system monitor…"))
        self._build()
        self.refresh()
        self.bind("<Destroy>", self._on_destroy, add="+")

    def _build(self) -> None:
        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text=self._("LIVE SYSTEM MONITOR"),
                  font=("TkDefaultFont", 15, "bold")).pack(side="left")
        ttk.Label(header, textvariable=self._status).pack(side="right")

        metrics = ttk.Frame(outer)
        metrics.pack(fill="x", pady=(0, 10))
        self.metric_vars: dict[str, tk.StringVar] = {}
        specs = [("cpu", "CPU"), ("memory", "RAM"), ("disk", "DISK"),
                 ("swap", "SWAP"), ("network", "NETWORK")]
        for column, (key, title) in enumerate(specs):
            metrics.columnconfigure(column, weight=1, uniform="metrics")
            card = ttk.LabelFrame(metrics, text=self._(title), padding=(9, 7))
            card.grid(row=0, column=column, sticky="nsew",
                      padx=(0 if column == 0 else 5, 0))
            variable = tk.StringVar(value="—")
            self.metric_vars[key] = variable
            ttk.Label(card, textvariable=variable,
                      font=("TkDefaultFont", 11, "bold")).pack(anchor="w")

        chart_box = ttk.LabelFrame(outer, text=self._("RESOURCE HISTORY · LAST 15 MINUTES"),
                                  padding=8)
        chart_box.pack(fill="x", pady=(0, 10))
        self.chart = tk.Canvas(chart_box, height=118, highlightthickness=0,
                               background="#17171c")
        self.chart.pack(fill="x", expand=True)
        self.chart.bind("<Configure>", lambda _event: self._draw_chart())

        process_box = ttk.LabelFrame(outer, text=self._("RUNNING PROCESSES"), padding=8)
        process_box.pack(fill="both", expand=True)
        controls = ttk.Frame(process_box)
        controls.pack(fill="x", pady=(0, 7))
        ttk.Label(controls, text=self._("Search:")).pack(side="left")
        search = ttk.Entry(controls, textvariable=self._filter, width=28)
        search.pack(side="left", padx=(6, 10))
        search.bind("<KeyRelease>", lambda _event: self._render_processes())
        ttk.Button(controls, text=self._("Refresh"), command=self.refresh).pack(side="left")
        ttk.Button(controls, text=self._("Export report"),
                   command=self.export_dialog).pack(side="left", padx=6)
        ttk.Button(controls, text=self._("End selected process"),
                   command=self.terminate_selected).pack(side="right")

        columns = ("pid", "name", "user", "cpu", "memory", "percent", "status", "threads")
        self.tree = ttk.Treeview(process_box, columns=columns, show="headings",
                                 height=11, selectmode="browse")
        headings = {"pid": "PID", "name": "PROCESS", "user": "USER", "cpu": "CPU %",
                    "memory": "RAM", "percent": "RAM %", "status": "STATUS",
                    "threads": "THREADS"}
        widths = {"pid": 65, "name": 230, "user": 145, "cpu": 75,
                  "memory": 105, "percent": 85, "status": 105, "threads": 75}
        for key in columns:
            self.tree.heading(key, text=self._(headings[key]),
                              command=lambda column=key: self._sort(column))
            self.tree.column(key, width=widths[key], minwidth=45,
                             anchor="w" if key in ("name", "user", "status") else "e")
        scroll = ttk.Scrollbar(process_box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._show_selection)

        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(8, 0))
        self.detail_var = tk.StringVar(value=self._("Select a process to inspect details."))
        ttk.Label(footer, textvariable=self.detail_var, wraplength=850).pack(
            side="left", fill="x", expand=True)
        ttk.Button(footer, text=self._("Clear history"),
                   command=self.clear_history).pack(side="right")

    def refresh(self) -> None:
        if self._destroyed or self._refreshing:
            return
        self._refreshing = True
        try:
            sample = self.probe.sample()
            self._sample = sample
            self.history.add(sample)
            self._render_metrics(sample)
            self._draw_chart()
            self._processes = self.probe.processes()
            self._render_processes()
            alerts = [item for item in analyze_health(sample)
                      if item.severity in ("warning", "critical")]
            current_codes = {item.code for item in alerts}
            for finding in alerts:
                if finding.code not in self._last_alert_codes:
                    self._on_log("warn", f"{finding.title}: {finding.detail}")
            self._last_alert_codes = current_codes
            self._status.set(self._("Warnings: ") + str(len(alerts)) if alerts
                             else self._("All monitored resources look stable"))
        except Exception as exc:
            self._status.set(self._("Monitor error: ") + str(exc))
            self._on_log("err", f"System monitor: {type(exc).__name__}: {exc}")
        finally:
            self._refreshing = False
            if not self._destroyed:
                self._after_id = self.after(int(self.sample_interval * 1000), self.refresh)

    def _render_metrics(self, sample: SystemSample) -> None:
        self.metric_vars["cpu"].set(f"{sample.cpu_percent:.0f}% · {sample.cpu_count} cores")
        self.metric_vars["memory"].set(
            f"{sample.memory_percent:.0f}% · {format_bytes(sample.memory_available)} free")
        self.metric_vars["disk"].set(
            f"{sample.disk_percent:.0f}% · {format_bytes(sample.disk_used)} / "
            f"{format_bytes(sample.disk_total)}")
        self.metric_vars["swap"].set(
            f"{sample.swap_percent:.0f}% · {format_bytes(sample.swap_used)}")
        self.metric_vars["network"].set(
            f"↑ {format_bytes(sample.net_sent_bytes)}  ↓ {format_bytes(sample.net_recv_bytes)}")

    def _draw_chart(self) -> None:
        if not hasattr(self, "chart") or not self.chart.winfo_exists():
            return
        canvas = self.chart
        canvas.delete("all")
        width, height = max(240, canvas.winfo_width()), max(80, canvas.winfo_height())
        left, right, top, bottom = 34, width - 12, 8, height - 20
        if right <= left:
            return
        for percent in (0, 25, 50, 75, 100):
            y = bottom - (bottom - top) * percent / 100
            canvas.create_line(left, y, right, y, fill="#34343d", dash=(2, 3))
            canvas.create_text(left - 5, y, text=str(percent), fill="#a7a7b2",
                               anchor="e", font=("TkDefaultFont", 7))
        for field_name, color in (("cpu_percent", "#62a8ff"),
                                  ("memory_percent", "#49d39b"),
                                  ("disk_percent", "#e9b45a")):
            values = self.history.series(field_name, 120)
            if len(values) < 2:
                continue
            points = []
            for index, (_stamp, value) in enumerate(values):
                x = left + (right - left) * index / max(1, len(values) - 1)
                y = bottom - (bottom - top) * _clamp_percent(value) / 100
                points.extend((x, y))
            canvas.create_line(*points, fill=color, width=2, smooth=True)
        canvas.create_text(right, height - 5, text="CPU · RAM · Disk",
                           fill="#b7b7c0", anchor="se", font=("TkDefaultFont", 7))

    def _render_processes(self) -> None:
        if not hasattr(self, "tree") or not self.tree.winfo_exists():
            return
        query = self._filter.get().strip().casefold()
        rows = [row for row in self._processes if not query
                or query in row.name.casefold() or query in str(row.pid)
                or query in row.username.casefold()]
        keys = {"pid": "pid", "name": "name", "user": "username",
                "cpu": "cpu_percent", "memory": "memory_rss",
                "percent": "memory_percent", "status": "status", "threads": "threads"}
        key = keys.get(self._sort_key, "memory_rss")
        rows.sort(key=lambda row: getattr(row, key, 0), reverse=self._sort_reverse)
        selected = self.tree.selection()
        selected_pid = selected[0] if selected else None
        self.tree.delete(*self.tree.get_children())
        for row in rows:
            self.tree.insert("", "end", iid=str(row.pid), values=(
                row.pid, row.name[:90], row.username[:35], f"{row.cpu_percent:.1f}",
                format_bytes(row.memory_rss), f"{row.memory_percent:.1f}",
                row.status, row.threads))
        if selected_pid and self.tree.exists(selected_pid):
            self.tree.selection_set(selected_pid)

    def _sort(self, column: str) -> None:
        if self._sort_key == column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_key = column
            self._sort_reverse = column not in ("pid", "name", "user", "status")
        self._render_processes()

    def _show_selection(self, _event: Any = None) -> None:
        selection = self.tree.selection()
        if not selection:
            self.detail_var.set(self._("Select a process to inspect details."))
            return
        pid = int(selection[0])
        row = next((item for item in self._processes if item.pid == pid), None)
        if row is None:
            return
        created = (datetime.fromtimestamp(row.created).strftime("%Y-%m-%d %H:%M:%S")
                   if row.created else self._("unknown"))
        self.detail_var.set(
            f"PID {row.pid} · {row.name} · {self._('User')}: "
            f"{row.username or self._('unknown')} · {self._('Started')}: {created} · "
            f"{self._('Threads')}: {row.threads} · {self._('Executable')}: "
            f"{row.executable or self._('not available')}")

    def terminate_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo(self._("Process manager"), self._("Select a process first."),
                                parent=self)
            return
        pid = int(selection[0])
        row = next((item for item in self._processes if item.pid == pid), None)
        if row is None:
            messagebox.showwarning(self._("Process manager"),
                self._("Process is no longer available."), parent=self)
            return
        prompt = self._("Ask this process to exit? Unsaved work may be lost. "
                        "CRAMC will not force-kill it.\n\n")
        if not messagebox.askyesno(self._("Confirm process exit"),
                                   prompt + f"{row.name} (PID {pid})", parent=self):
            return
        result = self.probe.terminate_user_process(pid)
        self._on_log("ok" if result.ok else "warn", result.message)
        if result.ok:
            self._status.set(self._("Process exited; refreshing list…"))
            self.after(350, self.refresh)
        else:
            messagebox.showwarning(self._("Process manager"), result.message, parent=self)

    def export_dialog(self) -> None:
        if self._sample is None:
            messagebox.showwarning(self._("Export report"),
                self._("No system sample is available yet."), parent=self)
            return
        path = filedialog.asksaveasfilename(parent=self,
            title=self._("Export system report"), defaultextension=".json",
            filetypes=[("JSON report", "*.json"), ("CSV process list", "*.csv")])
        if not path:
            return
        result = export_report(path, self._sample, self._processes, self.history)
        if result.ok:
            self._on_log("ok", result.message)
            messagebox.showinfo(self._("Export report"), result.message, parent=self)
        else:
            self._on_log("err", result.message)
            messagebox.showerror(self._("Export report"), result.message, parent=self)

    def clear_history(self) -> None:
        self.history.clear()
        if self._sample is not None:
            self.history.add(self._sample)
        self._draw_chart()
        self._on_log("info", "System monitor history cleared")

    def _on_destroy(self, event: Any) -> None:
        if event.widget is not self:
            return
        self._destroyed = True
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None


__all__ = ["ActionResult", "HealthFinding", "HistoryBuffer", "ProcessMonitorFrame",
           "ProcessRecord", "SystemProbe", "SystemSample", "analyze_health",
           "build_report", "export_report", "format_bytes", "format_rate"]
