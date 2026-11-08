#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ComputerRAMCleaner (CRAMC) v1.1.0 - Masaüstü uygulaması

Linux (Lubuntu/LXQt) : sync + /proc/sys/vm/drop_caches (PageCache, Dentries & Inodes)
                       isteğe bağlı güvenli swap sıfırlama
Windows 10/11        : Working Set + Sistem Önbelleği temizliği (ctypes + psutil)
Depolama             : Kullanıcı geçici klasörlerinde 24 saatten eski normal dosyaların
                       önizlemeli ve onaylı temizliği

Çalıştırma:
    Linux  : sudo python3 cramc.py
    Windows: python cramc.py   (Yönetici olarak çalıştırmak daha etkilidir)
    Test   : python3 cramc.py --selftest     (arayüzsüz motor testi)

Gereksinimler (kaynak koddan çalıştırırken):
    Linux  : python3-tk ve psutil (Windows ölçümü için)
    Windows: psutil

PyInstaller ile üretilen tek dosyalık dağıtımlarda Python/pip kurulumu gerekmez.
"""

import base64
import json
import os
import platform
import queue
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zlib
from dataclasses import asdict, dataclass, field
from datetime import datetime

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
    TK_OK = True
except ImportError:
    tk = None
    ttk = None
    messagebox = None
    TK_OK = False

try:
    import psutil
except ImportError:
    psutil = None

APP_NAME = "ComputerRAMCleaner"
APP_SHORT = "CRAMC"
APP_VERSION = "1.1.0"

MB = 1024 * 1024
GB = 1024 * MB
DROP_CACHES_PATH = "/proc/sys/vm/drop_caches"
OS_NAME = platform.system()
IS_LINUX = OS_NAME == "Linux"
IS_WINDOWS = OS_NAME == "Windows"



# =========================================================================== #
#  YARDIMCILAR
# =========================================================================== #
def fmt_size(n: float) -> str:
    sign = "-" if n < 0 else ""
    n = abs(n)
    if n >= GB:
        return f"{sign}{n / GB:.2f} GB"
    return f"{sign}{n / MB:.0f} MB"


def fmt_ago(ts: float) -> str:
    d = max(int(time.time() - ts), 0)
    if d < 60:
        return f"{d} sn önce"
    if d < 3600:
        return f"{d // 60} dk önce"
    if d < 86400:
        return f"{d // 3600} sa önce"
    return f"{d // 86400} gün önce"


def os_pretty() -> str:
    if IS_LINUX:
        try:
            return platform.freedesktop_os_release().get("PRETTY_NAME", "Linux")
        except Exception:
            pass
        try:
            with open("/etc/os-release", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("PRETTY_NAME="):
                        return line.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
        return "Linux"
    if IS_WINDOWS:
        return f"Windows {platform.release()}"
    return OS_NAME


def is_root_linux() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def is_admin_windows() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def has_privileges() -> bool:
    if IS_LINUX:
        return is_root_linux()
    if IS_WINDOWS:
        return is_admin_windows()
    return False


# =========================================================================== #
#  AYARLARIN KALICI SAKLANMASI
# =========================================================================== #
def config_dir() -> str:
    if IS_WINDOWS:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        home = os.path.expanduser("~")
        if is_root_linux() and os.environ.get("SUDO_USER"):
            try:
                import pwd
                home = pwd.getpwnam(os.environ["SUDO_USER"]).pw_dir
            except Exception:
                pass
        base = os.path.join(home, ".config")
    return os.path.join(base, "cramc")


def settings_path() -> str:
    return os.path.join(config_dir(), "settings.json")


def _chown_sudo_user(path: str):
    """sudo ile çalışırken oluşturulan dosyanın sahibini gerçek kullanıcı yap."""
    if IS_LINUX and is_root_linux() and os.environ.get("SUDO_UID"):
        try:
            uid = int(os.environ["SUDO_UID"])
            gid = int(os.environ.get("SUDO_GID", uid))
            os.chown(path, uid, gid)
        except (OSError, ValueError):
            pass


def load_settings() -> dict:
    try:
        with open(settings_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data: dict) -> bool:
    try:
        d = config_dir()
        os.makedirs(d, exist_ok=True)
        _chown_sudo_user(d)
        path = settings_path()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        _chown_sudo_user(path)
        return True
    except OSError:
        return False


# =========================================================================== #
#  BELLEK ÖLÇÜMÜ
# =========================================================================== #
@dataclass
class MemSnapshot:
    total: int
    used: int
    free: int          # Her iki platformda da kullanılabilir bellek (Linux MemAvailable)
    available: int
    cached: int        # Linux: buffers+cache | Windows: sistem önbelleği
    swap_total: int = 0
    swap_used: int = 0
    raw: dict = field(default_factory=dict)


def read_meminfo() -> dict:
    """/proc/meminfo içeriğini bayt cinsinden sözlük olarak döndürür."""
    info = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as fh:
        for line in fh:
            key, _, rest = line.partition(":")
            parts = rest.split()
            if parts:
                try:
                    info[key.strip()] = int(parts[0]) * 1024
                except ValueError:
                    pass
    return info


def _snapshot_linux() -> MemSnapshot:
    """Linux belleğini MemAvailable temelinde ölçer.

    MemFree yalnızca tamamen boş sayfaları gösterir. MemAvailable ise kernel'in
    reclaim edilebilir cache/slab havuzlarını da hesaba katar ve günlük kullanım
    görünümü için daha gerçekçi bir used metriği sağlar.
    """
    m = read_meminfo()
    total = m["MemTotal"]
    free = m.get("MemFree", 0)
    buffers = m.get("Buffers", 0)
    shmem = m.get("Shmem", 0)
    cached_raw = m.get("Cached", 0)
    sreclaimable = m.get("SReclaimable", 0)
    fallback_available = free + buffers + max(cached_raw - shmem, 0) + sreclaimable
    available = min(total, max(0, m.get("MemAvailable", fallback_available)))
    used = max(total - available, 0)
    # Ekrandaki önbellek metriği tmpfs/shmem'i cache gibi göstermemek için çıkarır.
    cached = max(0, buffers + cached_raw - shmem + sreclaimable)
    swap_total = m.get("SwapTotal", 0)
    swap_used = max(swap_total - m.get("SwapFree", 0), 0)
    return MemSnapshot(total, used, available, available, cached,
                       swap_total, swap_used, m)


def _snapshot_windows() -> MemSnapshot:
    if psutil is None:
        raise RuntimeError("psutil bulunamadı (Windows derlemesinde psutil gömülü olmalıdır)")
    vm = psutil.virtual_memory()
    try:
        sw = psutil.swap_memory()
        swap_total, swap_used = sw.total, sw.used
    except Exception:
        swap_total = swap_used = 0
    perf = _win_perf_info()
    return MemSnapshot(vm.total, vm.used, vm.available, vm.available,
                       perf.get("system_cache", 0), swap_total, swap_used, perf)


def take_snapshot() -> MemSnapshot:
    if IS_LINUX:
        return _snapshot_linux()
    if IS_WINDOWS:
        return _snapshot_windows()
    raise RuntimeError(f"Desteklenmeyen işletim sistemi: {OS_NAME}")


def count_processes() -> int:
    try:
        if IS_LINUX:
            return sum(1 for n in os.listdir("/proc") if n.isdigit())
        if psutil is not None:
            return len(psutil.pids())
        return int(_win_perf_info().get("process_count", 0))
    except Exception:
        return 0


# =========================================================================== #
#  WINDOWS API (ctypes) - yalnızca Windows'ta ve ilk kullanımda yüklenir
# =========================================================================== #
_WINAPI = None


def _winapi():
    global _WINAPI
    if _WINAPI is not None:
        return _WINAPI

    import ctypes
    from ctypes import wintypes
    from types import SimpleNamespace

    class PERFORMANCE_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("CommitTotal", ctypes.c_size_t),
            ("CommitLimit", ctypes.c_size_t),
            ("CommitPeak", ctypes.c_size_t),
            ("PhysicalTotal", ctypes.c_size_t),
            ("PhysicalAvailable", ctypes.c_size_t),
            ("SystemCache", ctypes.c_size_t),
            ("KernelTotal", ctypes.c_size_t),
            ("KernelPaged", ctypes.c_size_t),
            ("KernelNonpaged", ctypes.c_size_t),
            ("PageSize", ctypes.c_size_t),
            ("HandleCount", wintypes.DWORD),
            ("ProcessCount", wintypes.DWORD),
            ("ThreadCount", wintypes.DWORD),
        ]

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class LUID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]

    class TOKEN_PRIVILEGES(ctypes.Structure):
        _fields_ = [("PrivilegeCount", wintypes.DWORD),
                    ("Privileges", LUID_AND_ATTRIBUTES * 1)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetSystemFileCacheSize.argtypes = [ctypes.c_size_t, ctypes.c_size_t,
                                                wintypes.DWORD]
    kernel32.SetSystemFileCacheSize.restype = wintypes.BOOL

    psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
    psapi.EmptyWorkingSet.restype = wintypes.BOOL
    psapi.GetPerformanceInfo.argtypes = [ctypes.POINTER(PERFORMANCE_INFORMATION),
                                         wintypes.DWORD]
    psapi.GetPerformanceInfo.restype = wintypes.BOOL

    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                          ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR,
                                               ctypes.POINTER(LUID)]
    advapi32.LookupPrivilegeValueW.restype = wintypes.BOOL
    advapi32.AdjustTokenPrivileges.argtypes = [wintypes.HANDLE, wintypes.BOOL,
                                               ctypes.POINTER(TOKEN_PRIVILEGES),
                                               wintypes.DWORD, ctypes.c_void_p,
                                               ctypes.c_void_p]
    advapi32.AdjustTokenPrivileges.restype = wintypes.BOOL

    _WINAPI = SimpleNamespace(
        ctypes=ctypes, wintypes=wintypes, kernel32=kernel32, psapi=psapi,
        advapi32=advapi32, PERFORMANCE_INFORMATION=PERFORMANCE_INFORMATION,
        LUID=LUID, TOKEN_PRIVILEGES=TOKEN_PRIVILEGES,
    )
    return _WINAPI


def _win_perf_info() -> dict:
    try:
        api = _winapi()
        pi = api.PERFORMANCE_INFORMATION()
        pi.cb = api.ctypes.sizeof(pi)
        if not api.psapi.GetPerformanceInfo(api.ctypes.byref(pi), pi.cb):
            return {}
        return {
            "system_cache": int(pi.SystemCache) * int(pi.PageSize),
            "process_count": int(pi.ProcessCount),
        }
    except Exception:
        return {}


def _win_enable_privilege(name: str) -> bool:
    """Geçerli işlem belirtecinde bir ayrıcalığı etkinleştirir."""
    try:
        api = _winapi()
        ct = api.ctypes
        token = api.wintypes.HANDLE()
        TOKEN_ADJUST_PRIVILEGES, TOKEN_QUERY = 0x0020, 0x0008
        if not api.advapi32.OpenProcessToken(
                api.kernel32.GetCurrentProcess(),
                TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ct.byref(token)):
            return False
        try:
            luid = api.LUID()
            if not api.advapi32.LookupPrivilegeValueW(None, name, ct.byref(luid)):
                return False
            tp = api.TOKEN_PRIVILEGES()
            tp.PrivilegeCount = 1
            tp.Privileges[0].Luid = luid
            tp.Privileges[0].Attributes = 0x00000002  # SE_PRIVILEGE_ENABLED
            ct.set_last_error(0)
            if not api.advapi32.AdjustTokenPrivileges(
                    token, False, ct.byref(tp), 0, None, None):
                return False
            return ct.get_last_error() == 0  # 1300 = ERROR_NOT_ALL_ASSIGNED
        finally:
            api.kernel32.CloseHandle(token)
    except Exception:
        return False


# =========================================================================== #
#  TEMİZLİK SEÇENEKLERİ VE TAHMİN
# =========================================================================== #
@dataclass
class CleanOptions:
    # Linux
    pagecache: bool = True
    dentries: bool = True
    swap_reset: bool = False
    sync_first: bool = True
    # Windows
    working_set: bool = True
    system_cache: bool = True

    def any_selected(self) -> bool:
        if IS_LINUX:
            return self.pagecache or self.dentries or self.swap_reset
        return self.working_set or self.system_cache


@dataclass
class SwapDev:
    name: str
    kind: str
    size: int
    used: int
    prio: int


def read_swaps() -> list:
    devs = []
    try:
        with open("/proc/swaps", "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()[1:]
    except OSError:
        return devs
    for line in lines:
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            devs.append(SwapDev(parts[0].replace("\\040", " "), parts[1],
                                int(parts[2]) * 1024, int(parts[3]) * 1024,
                                int(parts[4])))
        except ValueError:
            continue
    return devs


def swap_reset_is_safe(snap: MemSnapshot, swap_used: int) -> bool:
    """Swap içeriği RAM'e sığacak mı? (sistemi kilitlememek için güvenlik payı bırakılır)"""
    margin = max(256 * MB, int(snap.total * 0.10))
    return swap_used <= snap.available - margin


def estimate_gain(opts: CleanOptions, snap: MemSnapshot, ws_bytes: int = 0):
    """Kernel/işlem ölçümlerinden muhafazakâr aday havuzu tahmini döndürür.

    Sonuç garanti edilen boş RAM değildir. Linux'ta temiz page-cache adayları ve
    reclaimable slab üst sınırı; Windows'ta süreçlerin USS belleği ile kernel
    SystemCache metriği kullanılır. Çakışan Windows havuzları toplam RAM'i aşamaz.
    """
    items = []
    if IS_LINUX:
        m = snap.raw
        if opts.pagecache:
            cached = max(0, m.get("Cached", 0) + m.get("Buffers", 0)
                         - m.get("Shmem", 0))
            file_lru = m.get("Active(file)", 0) + m.get("Inactive(file)", 0)
            if file_lru > 0:
                cached = min(cached, file_lru)
            not_immediately_clean = (m.get("Mapped", 0) + m.get("Dirty", 0)
                                     + m.get("Writeback", 0))
            pagecache_candidate = max(0, cached - not_immediately_clean)
            items.append(("Temiz PageCache adayı (kernel meminfo)", pagecache_candidate))
        if opts.dentries:
            # SReclaimable tüm reclaimable slab havuzudur; tamamı dentry/inode
            # olarak boşaltılamayabileceğinden UI bunu açıkça üst sınır diye sunar.
            slab_candidate = max(0, m.get("SReclaimable", 0))
            items.append(("Reclaimable slab üst sınırı (SReclaimable)", slab_candidate))
        if opts.swap_reset:
            if snap.swap_total == 0:
                items.append(("Swap sıfırlama (swap etkin değil)", 0))
            elif snap.swap_used == 0:
                items.append(("Swap sıfırlama (swap boş)", 0))
            elif swap_reset_is_safe(snap, snap.swap_used):
                items.append(("Swap sıfırlama (RAM tüketimi)", -snap.swap_used))
            else:
                items.append(("Swap sıfırlama (RAM yetersiz, atlanır)", 0))
        positive = sum(max(value, 0) for _, value in items)
        # MemAvailable, kernel'in yakın vadede geri kazanabileceği alanı da
        # içerir; aday havuzunu kullanılan bellek sınırında tutar.
        ceiling = max(0, snap.total - snap.available)
        if positive > ceiling and positive:
            ratio = ceiling / positive
            items = [(label, int(value * ratio) if value > 0 else value)
                     for label, value in items]
    elif IS_WINDOWS:
        used_ceiling = max(0, snap.total - snap.available)
        if opts.working_set:
            private_ws = min(max(int(ws_bytes), 0), used_ceiling)
            items.append(("Süreç USS toplamı (özel bellek üst sınırı)", private_ws))
        else:
            private_ws = 0
        if opts.system_cache:
            # SystemCache, GetPerformanceInfo/psutil.snapshot üzerinden alınan
            # Windows kernel metriğidir. Working Set tahminiyle çakışmaya karşı cap.
            cache_candidate = min(max(int(snap.cached), 0),
                                  max(0, used_ceiling - private_ws))
            items.append(("Sistem dosya önbelleği (Windows SystemCache)", cache_candidate))
    return sum(value for _, value in items), items


# =========================================================================== #
#  DEPOLAMA / GEÇİCİ DOSYA TEMİZLİĞİ
# =========================================================================== #
TEMP_FILE_MIN_AGE_SECONDS = 24 * 60 * 60
TEMP_SCAN_LIMIT = 20000


@dataclass(frozen=True)
class TempFileCandidate:
    path: str
    size: int
    mtime: float


def _temp_target_uid():
    """sudo ile başlatıldıysa gerçek kullanıcıya ait geçici dosyaları hedefle."""
    if not IS_LINUX:
        return None
    try:
        return int(os.environ.get("SUDO_UID", os.getuid()))
    except (TypeError, ValueError, OSError):
        return os.getuid()


def _temp_roots() -> list:
    if IS_WINDOWS:
        roots = [tempfile.gettempdir()]
    elif IS_LINUX:
        roots = [tempfile.gettempdir(), "/tmp", "/var/tmp"]
    else:
        roots = []
    unique = []
    seen = set()
    for root in roots:
        path = os.path.abspath(os.path.expanduser(root))
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def _is_reparse_or_symlink(path: str, st) -> bool:
    if stat.S_ISLNK(st.st_mode):
        return True
    # Windows reparse points (junctions/mount points) are not followed.
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(IS_WINDOWS and (attrs & 0x400))  # FILE_ATTRIBUTE_REPARSE_POINT


def _path_is_inside(path: str, root: str) -> bool:
    try:
        path_abs = os.path.abspath(path)
        root_abs = os.path.abspath(root)
        return os.path.commonpath((path_abs, root_abs)) == root_abs and path_abs != root_abs
    except (ValueError, OSError):
        return False


def scan_temp_files(min_age_seconds: int = TEMP_FILE_MIN_AGE_SECONDS):
    """Yalnızca kullanıcı temp dizinlerinde 24 saatten eski normal dosyaları listeler.

    Sembolik bağlantılar/junction'lar izlenmez. Linux'ta SUDO_UID kullanılarak
    yalnızca gerçek kullanıcıya ait dosya ve dizinlere girilir. Hiçbir dosya silinmez.
    Dönüş: (adaylar, erişim_hatası_sayısı, limit_doldu_mu).
    """
    cutoff = time.time() - max(0, int(min_age_seconds))
    target_uid = _temp_target_uid()
    candidates = []
    errors = 0
    limited = False

    for root in _temp_roots():
        try:
            root_stat = os.lstat(root)
            if _is_reparse_or_symlink(root, root_stat) or not stat.S_ISDIR(root_stat.st_mode):
                continue
        except OSError:
            continue

        def on_walk_error(_exc):
            nonlocal errors
            errors += 1

        for current, dirnames, filenames in os.walk(
                root, topdown=True, followlinks=False, onerror=on_walk_error):
            try:
                current_stat = os.lstat(current)
            except OSError:
                dirnames[:] = []
                errors += 1
                continue
            if _is_reparse_or_symlink(current, current_stat):
                dirnames[:] = []
                continue
            if IS_LINUX and current != root and current_stat.st_uid != target_uid:
                # /tmp ve /var/tmp kökleri normalde root sahibidir; kök dizini
                # geçilebilir, ancak alt klasörler gerçek kullanıcıya ait olmalıdır.
                dirnames[:] = []
                continue

            safe_dirs = []
            for dirname in dirnames:
                child = os.path.join(current, dirname)
                try:
                    child_stat = os.lstat(child)
                except OSError:
                    errors += 1
                    continue
                if _is_reparse_or_symlink(child, child_stat) or not stat.S_ISDIR(child_stat.st_mode):
                    continue
                if IS_LINUX and child_stat.st_uid != target_uid:
                    continue
                safe_dirs.append(dirname)
            dirnames[:] = safe_dirs

            for filename in filenames:
                path = os.path.join(current, filename)
                try:
                    st = os.lstat(path)
                    if _is_reparse_or_symlink(path, st) or not stat.S_ISREG(st.st_mode):
                        continue
                    if IS_LINUX and st.st_uid != target_uid:
                        continue
                    if st.st_mtime > cutoff:
                        continue
                    candidates.append(TempFileCandidate(path, int(st.st_size), float(st.st_mtime)))
                    if len(candidates) >= TEMP_SCAN_LIMIT:
                        limited = True
                        break
                except OSError:
                    errors += 1
            if limited:
                break
        if limited:
            break

    candidates.sort(key=lambda item: item.size, reverse=True)
    return candidates, errors, limited


def delete_temp_files(candidates, min_age_seconds: int = TEMP_FILE_MIN_AGE_SECONDS):
    """Önizlemede listelenen dosyaları yeniden doğrulayıp tek tek siler.

    Yalnızca izin verilen temp köklerinin altında kalan, hâlâ normal dosya olan,
    eşik yaştan eski ve Linux'ta gerçek kullanıcıya ait dosyalar silinir.
    Dizinler, bağlantılar, cache klasörleri ve sistem genelindeki dosyalar silinmez.
    """
    cutoff = time.time() - max(0, int(min_age_seconds))
    target_uid = _temp_target_uid()
    roots = _temp_roots()
    removed = 0
    bytes_removed = 0
    skipped = 0

    for candidate in candidates:
        path = getattr(candidate, "path", "")
        root = next((r for r in roots if _path_is_inside(path, r)), None)
        if root is None:
            skipped += 1
            continue
        try:
            relative = os.path.relpath(path, root)
            parts = relative.split(os.sep)
            if not parts or any(part in ("", ".", "..") for part in parts):
                skipped += 1
                continue

            # POSIX'te dir_fd + O_NOFOLLOW parent symlink yarışlarını önler:
            # her klasör bileşeni gerçek dizin olarak açılır ve unlink aynı fd'de yapılır.
            if os.name == "posix" and hasattr(os, "O_NOFOLLOW") and os.open in os.supports_dir_fd:
                flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW
                dir_fd = os.open(root, flags)
                try:
                    for component in parts[:-1]:
                        next_fd = os.open(component, flags, dir_fd=dir_fd)
                        os.close(dir_fd)
                        dir_fd = next_fd
                    st = os.stat(parts[-1], dir_fd=dir_fd, follow_symlinks=False)
                    if not stat.S_ISREG(st.st_mode) or st.st_mtime > cutoff:
                        skipped += 1
                        continue
                    if IS_LINUX and st.st_uid != target_uid:
                        skipped += 1
                        continue
                    size = int(st.st_size)
                    os.unlink(parts[-1], dir_fd=dir_fd)
                finally:
                    os.close(dir_fd)
            else:
                # Windows: her üst dizin ve son dosya yeniden lstat edilir;
                # reparse point/junction veya symlink görüldüğünde işlem durur.
                parent = root
                safe = True
                for component in parts[:-1]:
                    parent = os.path.join(parent, component)
                    parent_stat = os.lstat(parent)
                    if (_is_reparse_or_symlink(parent, parent_stat)
                            or not stat.S_ISDIR(parent_stat.st_mode)):
                        safe = False
                        break
                if not safe:
                    skipped += 1
                    continue
                st = os.lstat(path)
                if (_is_reparse_or_symlink(path, st) or not stat.S_ISREG(st.st_mode)
                        or st.st_mtime > cutoff):
                    skipped += 1
                    continue
                size = int(st.st_size)
                os.remove(path)

            removed += 1
            bytes_removed += size
        except OSError:
            skipped += 1

    return removed, bytes_removed, skipped


# =========================================================================== #
#  TEMİZLİK MOTORU
# =========================================================================== #
def _find_cmd(name: str):
    path = shutil.which(name)
    if path:
        return path
    for d in ("/sbin", "/usr/sbin", "/bin", "/usr/bin"):
        cand = os.path.join(d, name)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def _linux_swap_reset(log):
    """True: başarılı, False: hata, None: güvenlik nedeniyle atlandı."""
    devs = read_swaps()
    if not devs:
        log("warn", "Aktif swap bulunamadı, swap sıfırlama atlandı")
        return None
    used = sum(d.used for d in devs)
    snap = take_snapshot()
    if not swap_reset_is_safe(snap, used):
        log("warn", f"Swap sıfırlama atlandı: {fmt_size(used)} swap, mevcut boş RAM'e "
                    f"({fmt_size(snap.available)}) göre güvenli değil")
        return None
    swapoff, swapon = _find_cmd("swapoff"), _find_cmd("swapon")
    if not swapoff or not swapon:
        log("err", "swapoff/swapon komutları bulunamadı")
        return False

    log("info", f"Swap sıfırlanıyor: {len(devs)} aygıt, {fmt_size(used)} kullanımda "
                "(bu işlem biraz sürebilir)...")
    all_ok = True
    for d in devs:
        off_ok = False
        try:
            subprocess.run([swapoff, d.name], check=True, timeout=900,
                           capture_output=True, text=True)
            off_ok = True
        except subprocess.CalledProcessError as exc:
            log("err", f"swapoff {d.name} başarısız: {(exc.stderr or '').strip()}")
        except subprocess.TimeoutExpired:
            log("err", f"swapoff {d.name} zaman aşımına uğradı")
        except OSError as exc:
            log("err", f"swapoff çalıştırılamadı: {exc}")
        if not off_ok:
            all_ok = False
            continue
        cmd = [swapon] + (["-p", str(d.prio)] if d.prio >= 0 else []) + [d.name]
        try:
            subprocess.run(cmd, check=True, timeout=120, capture_output=True, text=True)
            log("ok", f"{d.name} yeniden etkinleştirildi")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            all_ok = False
            log("err", f"KRİTİK: {d.name} yeniden açılamadı ({exc}). "
                       f"Elle çalıştırın: sudo swapon {d.name}")
    return all_ok


def clean_linux(opts: CleanOptions, log):
    """(başarılı_mı, hata_mesajı) döndürür."""
    if not is_root_linux():
        log("err", "Root yetkisi yok: Tam temizlik için sudo ile çalıştırın")
        return False, "Tam temizlik için sudo ile çalıştırın"

    actions = 0
    last_err = ""

    if opts.sync_first:
        log("info", "Disk tamponları senkronize ediliyor (sync)...")
        try:
            subprocess.run(["sync"], check=True, timeout=180)
            log("ok", "sync tamamlandı")
        except FileNotFoundError:
            last_err = "'sync' komutu bulunamadı"
            log("err", last_err)
        except subprocess.TimeoutExpired:
            last_err = "'sync' zaman aşımına uğradı"
            log("err", last_err)
        except subprocess.CalledProcessError as exc:
            last_err = f"'sync' başarısız (kod {exc.returncode})"
            log("err", last_err)

    value = (1 if opts.pagecache else 0) | (2 if opts.dentries else 0)
    if value:
        names = " + ".join(n for n, on in (("PageCache", opts.pagecache),
                                           ("Dentries/Inodes", opts.dentries)) if on)
        try:
            with open(DROP_CACHES_PATH, "w", encoding="ascii") as fh:
                fh.write(f"{value}\n")
            actions += 1
            log("ok", f"drop_caches = {value} yazıldı ({names})")
        except PermissionError:
            last_err = "drop_caches yazma izni reddedildi"
            log("err", last_err)
        except OSError as exc:
            last_err = f"drop_caches yazılamadı: {exc}"
            log("err", last_err)

    if opts.swap_reset:
        result = _linux_swap_reset(log)
        if result:
            actions += 1
        elif result is False:
            last_err = "Swap sıfırlama başarısız (günlüğe bakın)"
        elif actions == 0:
            last_err = "Swap sıfırlama güvenlik nedeniyle atlandı"

    return actions > 0, last_err


def clean_windows(opts: CleanOptions, log):
    """(başarılı_mı, hata_mesajı) döndürür."""
    if psutil is None:
        log("err", "psutil bulunamadı:  pip install psutil")
        return False, "psutil gerekli (pip install psutil)"

    api = _winapi()
    ct = api.ctypes
    if not is_admin_windows():
        log("warn", "Yönetici yetkisi yok: yalnızca erişilebilen süreçler temizlenir")

    actions = 0
    last_err = ""

    if opts.working_set:
        PROCESS_QUERY_INFORMATION, PROCESS_SET_QUOTA = 0x0400, 0x0100
        ok = failed = 0
        own_pid = os.getpid()
        for proc in psutil.process_iter(["pid"]):
            pid = proc.info["pid"]
            if pid in (0, 4, own_pid):
                continue
            handle = api.kernel32.OpenProcess(
                PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA, False, pid)
            if not handle:
                failed += 1
                continue
            try:
                if api.psapi.EmptyWorkingSet(handle):
                    ok += 1
                else:
                    failed += 1
            finally:
                api.kernel32.CloseHandle(handle)
        if ok:
            actions += 1
            log("ok", f"Working Set boşaltıldı: {ok} süreç ({failed} atlandı/erişilemedi)")
        else:
            last_err = "Hiçbir sürecin Working Set'i boşaltılamadı"
            log("err", last_err)

    if opts.system_cache:
        if not _win_enable_privilege("SeIncreaseQuotaPrivilege"):
            log("warn", "Sistem önbelleği atlandı: SeIncreaseQuotaPrivilege alınamadı "
                        "(Yönetici olarak çalıştırın)")
            if actions == 0:
                last_err = "Sistem önbelleği için Yönetici yetkisi gerekli"
        else:
            minus_one = ct.c_size_t(-1).value
            ct.set_last_error(0)
            if api.kernel32.SetSystemFileCacheSize(minus_one, minus_one, 0):
                actions += 1
                log("ok", "Sistem dosya önbelleği temizlendi")
            else:
                err = ct.get_last_error()
                last_err = f"SetSystemFileCacheSize başarısız (hata {err})"
                log("err", last_err)

    return actions > 0, last_err


# =========================================================================== #
#  VEKTÖREL LOGO (dışarıdan dosya gerekmez)
# =========================================================================== #
_C_BLUE = (47, 140, 255)
_C_GREEN = (46, 204, 113)
_C_DIE = (234, 255, 243)
_C_CHIP = (14, 19, 24)


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _shield_halfwidth(v):
    top, shoulder, mid, tip = 0.03, 0.17, 0.46, 0.97
    if v < top or v > tip:
        return None
    if v < shoulder:
        return 0.40 * (v - top) / (shoulder - top)
    if v <= mid:
        return 0.40
    t = (v - mid) / (tip - mid)
    return 0.40 * (1.0 - t * t) ** 0.7


def _rrect(ax, ay, hx, hy, r):
    qx, qy = ax - (hx - r), ay - (hy - r)
    return max(qx, 0.0) ** 2 + max(qy, 0.0) ** 2 <= r * r


def _logo_sample(u, v):
    """Birim karede (u, v) noktasının rengi; saydamsa None."""
    dx, dy = u - 0.5, v - 0.47
    ax, ay = abs(dx), abs(dy)
    if ax <= 0.095 and ay <= 0.095:                      # çip kalıbı (die)
        return _C_DIE
    if ax <= 0.19 and ay <= 0.19 and _rrect(ax, ay, 0.19, 0.19, 0.045):  # çip gövdesi
        return _C_CHIP
    if 0.19 < ax <= 0.27 and abs(ay - 0.075) <= 0.028:   # yan bacaklar
        return _C_CHIP
    if 0.19 < ay <= 0.27 and abs(ax - 0.075) <= 0.028:   # üst/alt bacaklar
        return _C_CHIP
    hw = _shield_halfwidth(v)                            # kalkan
    if hw is None or abs(u - 0.5) > hw:
        return None
    t = min(max((u + v - 0.2) / 1.2, 0.0), 1.0)
    return _lerp(_C_BLUE, _C_GREEN, t)


def generate_logo_png(size: int, ss: int = 3) -> bytes:
    """Saf Python ile (kenar yumuşatmalı) logo PNG baytları üretir."""
    n = ss * ss
    rows = []
    for py in range(size):
        row = bytearray([0])  # PNG filtre baytı
        for px in range(size):
            r = g = b = a = 0
            for sy in range(ss):
                v = (py + (sy + 0.5) / ss) / size
                for sx in range(ss):
                    u = (px + (sx + 0.5) / ss) / size
                    c = _logo_sample(u, v)
                    if c:
                        r += c[0]
                        g += c[1]
                        b += c[2]
                        a += 1
            if a:
                row += bytes((r // a, g // a, b // a, a * 255 // n))
            else:
                row += b"\x00\x00\x00\x00"
        rows.append(bytes(row))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


# =========================================================================== #
#  ARAYÜZ SABİTLERİ
# =========================================================================== #
BG = "#121212"
CARD = "#1c1c1f"
CARD2 = "#232328"
CARD_BORDER = "#2a2a2f"
FG = "#e8e8ea"
FG_DIM = "#8b8b93"
BLUE = "#3b9cff"
GREEN = "#2ecc71"
GREEN_DARK = "#25a85c"
AMBER = "#f5a524"
RED = "#ef4444"
CYAN = "#22d3ee"

FONT = "DejaVu Sans" if IS_LINUX else "Segoe UI"
MONO = "DejaVu Sans Mono" if IS_LINUX else "Consolas"


def make_card(parent, title):
    """(dış_çerçeve, başlık_çubuğu, gövde) döndürür."""
    outer = tk.Frame(parent, bg=CARD, highlightbackground=CARD_BORDER,
                     highlightcolor=CARD_BORDER, highlightthickness=1)
    head = tk.Frame(outer, bg=CARD)
    head.pack(fill="x", padx=16, pady=(10, 4))
    tk.Label(head, text=title, bg=CARD, fg=FG_DIM,
             font=(FONT, 8, "bold")).pack(side="left")
    body = tk.Frame(outer, bg=CARD)
    body.pack(fill="both", expand=True, padx=16, pady=(0, 12))
    return outer, head, body


def _round_rect(c, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


if TK_OK:
    class CheckRow(tk.Frame):
        """Koyu tema uyumlu, özel çizimli onay kutusu satırı."""

        def __init__(self, parent, text, desc, var, bg=CARD):
            super().__init__(parent, bg=bg, cursor="hand2")
            self.var = var
            self.box = tk.Canvas(self, width=20, height=20, bg=bg,
                                 highlightthickness=0, bd=0, cursor="hand2")
            self.box.grid(row=0, column=0, rowspan=2, padx=(0, 10), pady=2, sticky="n")
            self.title = tk.Label(self, text=text, bg=bg, fg=FG, anchor="w",
                                  justify="left", font=(FONT, 10, "bold"),
                                  cursor="hand2")
            self.title.grid(row=0, column=1, sticky="w")
            self.desc = tk.Label(self, text=desc, bg=bg, fg=FG_DIM, anchor="w",
                                 justify="left", wraplength=340, font=(FONT, 8),
                                 cursor="hand2")
            self.desc.grid(row=1, column=1, sticky="w")
            self.columnconfigure(1, weight=1)
            for w in (self, self.box, self.title, self.desc):
                w.bind("<Button-1>", self._toggle)
            var.trace_add("write", lambda *a: self._draw())
            self._draw()

        def _toggle(self, _event=None):
            self.var.set(not self.var.get())

        def _draw(self):
            c = self.box
            c.delete("all")
            on = bool(self.var.get())
            _round_rect(c, 1, 1, 19, 19, 5,
                        fill=BLUE if on else "#0d0d0f",
                        outline=BLUE if on else "#4a4a55")
            if on:
                c.create_line(5, 10, 9, 14, 15, 6, fill="#ffffff", width=2,
                              capstyle="round", joinstyle="round")

    class FlatSlider(tk.Canvas):
        """Koyu tema uyumlu yatay kaydırıcı (tamsayı değişkenine bağlı)."""

        def __init__(self, parent, var, lo, hi, step=1, bg=CARD):
            super().__init__(parent, height=22, bg=bg, highlightthickness=0,
                             bd=0, cursor="hand2")
            self.var, self.lo, self.hi, self.step = var, lo, hi, step
            self.bind("<Configure>", lambda e: self._draw())
            self.bind("<Button-1>", self._on_mouse)
            self.bind("<B1-Motion>", self._on_mouse)
            var.trace_add("write", lambda *a: self._draw())

        def _x_range(self):
            w = self.winfo_width()
            return 10, max(w - 10, 11)

        def _on_mouse(self, e):
            x0, x1 = self._x_range()
            f = (min(max(e.x, x0), x1) - x0) / (x1 - x0)
            val = self.lo + f * (self.hi - self.lo)
            val = round(val / self.step) * self.step
            self.var.set(int(min(max(val, self.lo), self.hi)))

        def _draw(self):
            self.delete("all")
            x0, x1 = self._x_range()
            cy = 11
            try:
                f = (self.var.get() - self.lo) / (self.hi - self.lo)
            except Exception:
                f = 0
            f = min(max(f, 0.0), 1.0)
            xk = x0 + f * (x1 - x0)
            self.create_line(x0, cy, x1, cy, fill="#2f2f36", width=4, capstyle="round")
            self.create_line(x0, cy, xk, cy, fill=BLUE, width=4, capstyle="round")
            self.create_oval(xk - 8, cy - 8, xk + 8, cy + 8, fill="#ffffff",
                             outline=BLUE, width=2)

    class GhostButton(tk.Label):
        def __init__(self, parent, text, command, bg=CARD):
            super().__init__(parent, text=text, bg=bg, fg=FG_DIM, cursor="hand2",
                             font=(FONT, 8, "bold"), padx=6, pady=2)
            self._cmd = command
            self.bind("<Button-1>", lambda e: self._cmd())
            self.bind("<Enter>", lambda e: self.configure(fg=FG))
            self.bind("<Leave>", lambda e: self.configure(fg=FG_DIM))


# =========================================================================== #
#  ANA UYGULAMA
# =========================================================================== #
class CramcApp:
    def __init__(self, root):
        self.root = root
        self.busy = False
        self.q = queue.Queue()
        self.ws_bytes = 0  # Windows: toplam süreç USS (özel, benzersiz bellek)
        self.storage_candidates = []
        self.storage_busy = False
        self._stop = False
        self._swap_running = False
        self._notice_job = None
        self._save_job = None
        self._last_snap = None
        self._last_tick_err = None
        self._warned_auto = False
        self.last_auto_ts = 0.0
        self.session_freed = 0
        self.session_cleans = 0
        self._icons = []
        self.logo_img = None

        s = load_settings()
        o = s.get("opts", {}) if isinstance(s.get("opts"), dict) else {}
        defaults = CleanOptions()

        def bv(name):
            return tk.BooleanVar(value=bool(o.get(name, getattr(defaults, name))))

        def iv(key, default, lo, hi):
            try:
                return tk.IntVar(value=min(max(int(s.get(key, default)), lo), hi))
            except (TypeError, ValueError):
                return tk.IntVar(value=default)

        self.v_pagecache = bv("pagecache")
        self.v_dentries = bv("dentries")
        self.v_swap = bv("swap_reset")
        self.v_sync = bv("sync_first")
        self.v_ws = bv("working_set")
        self.v_syscache = bv("system_cache")
        self.v_auto = tk.BooleanVar(value=bool(s.get("auto_enabled", False)))
        self.v_thr = iv("auto_threshold", 85, 50, 95)
        self.v_cd = iv("auto_cooldown", 10, 1, 60)
        self.settings_open = bool(s.get("settings_open", True))
        ts = s.get("last_clean_ts")
        self.last_clean_ts = float(ts) if isinstance(ts, (int, float)) else None

        root.title(f"{APP_NAME} ({APP_SHORT})")
        root.configure(bg=BG)
        self._load_icons()
        self._build_style()
        self._build_ui()
        self._wire_traces()
        self._fit_window()
        self._log_startup()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        if IS_WINDOWS and psutil is not None:
            threading.Thread(target=self._ws_loop, daemon=True).start()
        self._tick()
        self._poll_queue()

    # ------------------------------------------------------------- ikonlar
    def _load_icons(self):
        try:
            imgs = []
            for size in (64, 32):
                data = base64.b64encode(generate_logo_png(size)).decode("ascii")
                imgs.append(tk.PhotoImage(data=data))
            self.logo_img = tk.PhotoImage(
                data=base64.b64encode(generate_logo_png(52)).decode("ascii"))
            self._icons = imgs + [self.logo_img]
            self.root.iconphoto(True, *imgs)
        except Exception:
            self.logo_img = None  # logo olmadan da çalışır

    # --------------------------------------------------------------- stil
    def _build_style(self):
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("Ram.Horizontal.TProgressbar", troughcolor="#2a2a2f",
                     background=BLUE, bordercolor=CARD, lightcolor=BLUE,
                     darkcolor=BLUE, thickness=16)
        st.configure("Swap.Horizontal.TProgressbar", troughcolor="#33333a",
                     background=CYAN, bordercolor=CARD2, lightcolor=CYAN,
                     darkcolor=CYAN, thickness=6)
        st.configure("Busy.Horizontal.TProgressbar", troughcolor=BG,
                     background=GREEN, bordercolor=BG, lightcolor=GREEN,
                     darkcolor=GREEN, thickness=4)
        st.configure("Dark.Vertical.TScrollbar", background="#2f2f36",
                     troughcolor="#0d0d0f", bordercolor="#0d0d0f",
                     arrowcolor=FG_DIM, lightcolor="#2f2f36", darkcolor="#2f2f36",
                     relief="flat")
        st.map("Dark.Vertical.TScrollbar", background=[("active", "#3d3d46")])
        st.configure("CRAMC.TNotebook", background=BG, borderwidth=0)
        st.configure("CRAMC.TNotebook.Tab", background=CARD2, foreground=FG_DIM,
                     padding=(18, 10), borderwidth=0)
        st.map("CRAMC.TNotebook.Tab",
               background=[("selected", CARD)],
               foreground=[("selected", FG), ("active", FG)])
        st.configure("Storage.Treeview", background="#0d0d0f", foreground=FG,
                     fieldbackground="#0d0d0f", rowheight=26, borderwidth=0)
        st.configure("Storage.Treeview.Heading", background=CARD2,
                     foreground=FG_DIM, relief="flat")
        st.map("Storage.Treeview", background=[("selected", "#21436a")],
               foreground=[("selected", "#ffffff")])
        self.style = st

    # ----------------------------------------------------------------- UI
    def _build_ui(self):
        self.notebook = ttk.Notebook(self.root, style="CRAMC.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=12, pady=12)

        self.welcome_tab = tk.Frame(self.notebook, bg=BG)
        self.ram_tab = tk.Frame(self.notebook, bg=BG)
        self.storage_tab = tk.Frame(self.notebook, bg=BG)

        self.notebook.add(self.welcome_tab, text="✦  Hoş Geldin")
        self.notebook.add(self.ram_tab, text="◈  RAM Yönetimi")
        self.notebook.add(self.storage_tab, text="▣  Depolama")

        self._build_welcome_tab(self.welcome_tab)
        self._build_dashboard_tab(self.ram_tab)
        self._build_storage_tab(self.storage_tab)

    def _build_welcome_tab(self, parent):
        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill="both", expand=True, padx=24, pady=22)

        hero = tk.Frame(outer, bg=CARD, highlightbackground=CARD_BORDER,
                        highlightthickness=1)
        hero.pack(fill="x", pady=(0, 14))

        head = tk.Frame(hero, bg=CARD)
        head.pack(fill="x", padx=24, pady=(22, 6))
        if self.logo_img is not None:
            tk.Label(head, image=self.logo_img, bg=CARD).pack(side="left", padx=(0, 14))
        title_box = tk.Frame(head, bg=CARD)
        title_box.pack(side="left", fill="x", expand=True)
        tk.Label(title_box, text="CRAMC'ye hoş geldin!", bg=CARD, fg=FG,
                 font=(FONT, 22, "bold")).pack(anchor="w")
        tk.Label(title_box, text=f"{os_pretty()}  •  Sürüm {APP_VERSION}",
                 bg=CARD, fg=BLUE, font=(FONT, 9, "bold")).pack(anchor="w", pady=(3, 0))

        tk.Label(hero,
                 text="ComputerRAMCleaner; RAM ve sistem önbelleği durumunu izlemenize, "
                      "işletim sisteminize uygun temizlik işlemlerini seçmenize ve "
                      "kullanıcı geçici dosyalarını kontrollü biçimde yönetmenize yardımcı olur.",
                 bg=CARD, fg=FG_DIM, justify="left", anchor="w", wraplength=900,
                 font=(FONT, 10), padx=24).pack(fill="x", pady=(8, 12))

        action_row = tk.Frame(hero, bg=CARD)
        action_row.pack(fill="x", padx=24, pady=(0, 22))
        tk.Button(action_row, text="RAM Yönetimine Git  →",
                  command=lambda: self.notebook.select(self.ram_tab),
                  bg=GREEN, fg="#06220f", activebackground=GREEN_DARK,
                  relief="flat", bd=0, cursor="hand2",
                  font=(FONT, 10, "bold"), padx=18, pady=9).pack(side="left")
        privilege_text = ("● Yetkili çalışıyor" if has_privileges()
                          else ("● Linux: tam temizlik için sudo gerekli" if IS_LINUX
                                else "● Yönetici izni yok; bazı işlemler atlanabilir"))
        privilege_color = GREEN if has_privileges() else AMBER
        tk.Label(action_row, text=privilege_text, bg=CARD, fg=privilege_color,
                 font=(FONT, 9, "bold")).pack(side="right", padx=(10, 0))

        tk.Label(outer, text="HIZLI BAŞLANGIÇ REHBERİ", bg=BG, fg=FG_DIM,
                 font=(FONT, 9, "bold")).pack(anchor="w", pady=(8, 10))

        guide = tk.Frame(outer, bg=BG)
        guide.pack(fill="x")
        for col in range(3):
            guide.columnconfigure(col, weight=1, uniform="guide")

        guide_items = [
            ("01", "Sistemi gözlemle",
             "RAM, kullanılabilir bellek, önbellek, swap ve işlem sayısını RAM Yönetimi sekmesinde incele."),
            ("02", "İşlemleri seç",
             "Linux veya Windows için gösterilen seçenekleri ihtiyacına göre işaretle. Swap sıfırlama isteğe bağlıdır."),
            ("03", "Önizle ve uygula",
             "Tahmini kazanımı üst sınır olarak değerlendir; ardından RAM TEMİZLE düğmesiyle işlemi başlat."),
        ]
        for col, (num, title_text, desc) in enumerate(guide_items):
            card = tk.Frame(guide, bg=CARD, highlightbackground=CARD_BORDER,
                            highlightthickness=1)
            card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 7, 0),
                      pady=0)
            tk.Label(card, text=num, bg=CARD, fg=BLUE,
                     font=(FONT, 10, "bold")).pack(anchor="w", padx=16, pady=(15, 4))
            tk.Label(card, text=title_text, bg=CARD, fg=FG,
                     font=(FONT, 11, "bold")).pack(anchor="w", padx=16)
            tk.Label(card, text=desc, bg=CARD, fg=FG_DIM, justify="left",
                     anchor="nw", wraplength=260, font=(FONT, 8)).pack(
                         fill="both", expand=True, padx=16, pady=(7, 16))

        note = tk.Frame(outer, bg="#2b2418", highlightbackground="#5a4528",
                        highlightthickness=1)
        note.pack(fill="x", pady=(16, 0))
        tk.Label(note,
                 text="GÜVENLİK NOTU  •  Bellek önbelleklerini temizlemek her zaman performans artışı sağlamaz. "
                      "Sistemler bu belleği ihtiyaç olduğunda otomatik geri kazanabilir. Depolama sekmesi "
                      "yalnızca kullanıcının geçici klasörlerinde 24 saatten eski dosyaları listeler; "
                      "silmeden önce önizleme ve onay ister.",
                 bg="#2b2418", fg=AMBER, justify="left", anchor="w",
                 wraplength=920, font=(FONT, 8), padx=15, pady=11).pack(fill="x")

    def _build_dashboard_tab(self, tab):
        main = tk.Frame(tab, bg=BG)
        main.pack(fill="both", expand=True, padx=20, pady=(16, 8))
        main.columnconfigure(0, weight=1, uniform="cols")
        main.columnconfigure(1, weight=1, uniform="cols")
        main.rowconfigure(2, weight=1)

        self._build_header(main)
        self._build_banner(main)

        left = tk.Frame(main, bg=BG)
        left.grid(row=2, column=0, sticky="nsew", padx=(0, 8))
        right = tk.Frame(main, bg=BG)
        right.grid(row=2, column=1, sticky="nsew", padx=(8, 0))
        self._build_left(left)
        self._build_right(right)

        tk.Label(main, text=f"{APP_SHORT} v{APP_VERSION}", bg=BG, fg="#4a4a52",
                 font=(FONT, 8)).grid(row=3, column=0, columnspan=2, pady=(6, 0))

    def _build_storage_tab(self, parent):
        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill="both", expand=True, padx=22, pady=20)

        tk.Label(outer, text="DEPOLAMA YÖNETİMİ", bg=BG, fg=BLUE,
                 font=(FONT, 9, "bold")).pack(anchor="w")
        tk.Label(outer, text="Geçici dosyaları güvenle gözden geçir",
                 bg=BG, fg=FG, font=(FONT, 20, "bold")).pack(anchor="w", pady=(4, 5))
        tk.Label(outer,
                 text="CRAMC yalnızca kullanıcı geçici klasörlerini tarar. Varsayılan olarak "
                      "24 saatten eski normal dosyalar listelenir; sistem klasörleri, tarayıcı "
                      "önbellekleri, İndirilenler klasörü ve sembolik bağlantı hedefleri taranmaz.",
                 bg=BG, fg=FG_DIM, justify="left", anchor="w", wraplength=950,
                 font=(FONT, 9)).pack(fill="x", pady=(0, 14))

        summary = tk.Frame(outer, bg=CARD, highlightbackground=CARD_BORDER,
                           highlightthickness=1)
        summary.pack(fill="x", pady=(0, 12))
        self.storage_status = tk.Label(summary,
            text="Tarama yapılmadı. Önce geçici dosyaları tara.", bg=CARD,
            fg=FG_DIM, anchor="w", justify="left", wraplength=900,
            font=(FONT, 10), padx=16, pady=13)
        self.storage_status.pack(fill="x")

        table_frame = tk.Frame(outer, bg=CARD, highlightbackground=CARD_BORDER,
                               highlightthickness=1)
        table_frame.pack(fill="both", expand=True)
        columns = ("path", "size", "date")
        self.storage_tree = ttk.Treeview(table_frame, columns=columns,
            show="headings", style="Storage.Treeview", height=12)
        self.storage_tree.heading("path", text="GEÇİCİ DOSYA")
        self.storage_tree.heading("size", text="BOYUT")
        self.storage_tree.heading("date", text="SON DEĞİŞİKLİK")
        self.storage_tree.column("path", width=650, minwidth=240, anchor="w")
        self.storage_tree.column("size", width=110, minwidth=90, anchor="e")
        self.storage_tree.column("date", width=170, minwidth=140, anchor="center")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical",
                                  command=self.storage_tree.yview,
                                  style="Dark.Vertical.TScrollbar")
        self.storage_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.storage_tree.pack(side="left", fill="both", expand=True, padx=8, pady=8)

        buttons = tk.Frame(outer, bg=BG)
        buttons.pack(fill="x", pady=(12, 0))
        self.storage_scan_button = tk.Button(
            buttons, text="GEÇİCİ DOSYALARI TARA", command=self._scan_storage,
            bg=BLUE, fg="#061321", activebackground="#287ed2",
            relief="flat", bd=0, cursor="hand2", font=(FONT, 10, "bold"),
            padx=18, pady=10)
        self.storage_scan_button.pack(side="left")
        self.storage_clean_button = tk.Button(
            buttons, text="ÖNİZLEMEDEKİ DOSYALARI SİL", command=self._clean_storage,
            bg=GREEN, fg="#06220f", activebackground=GREEN_DARK,
            disabledforeground="#557767", relief="flat", bd=0, cursor="hand2",
            font=(FONT, 10, "bold"), padx=18, pady=10, state="disabled")
        self.storage_clean_button.pack(side="left", padx=(10, 0))
        tk.Label(buttons, text="Yalnızca listelenen dosyalar silinir; onay gerekir.",
                 bg=BG, fg=FG_DIM, font=(FONT, 8)).pack(side="right")

    def _scan_storage(self):
        if self.storage_busy:
            return
        self.storage_busy = True
        # Yeni tarama başlarken önceki önizlemenin yanlışlıkla silinmesini önle.
        self.storage_candidates = []
        for item in self.storage_tree.get_children():
            self.storage_tree.delete(item)
        self.storage_scan_button.configure(state="disabled")
        self.storage_clean_button.configure(state="disabled")
        self.storage_status.configure(text="Geçici klasörler taranıyor…", fg=BLUE)
        threading.Thread(target=self._storage_scan_worker, daemon=True).start()

    def _storage_scan_worker(self):
        try:
            candidates, errors, limited = scan_temp_files()
            self.q.put(("storage_scan_done", candidates, errors, limited))
        except Exception as exc:
            self.q.put(("storage_scan_error", str(exc)))

    def _clean_storage(self):
        if self.storage_busy or not self.storage_candidates:
            return
        count = len(self.storage_candidates)
        total_bytes = sum(item.size for item in self.storage_candidates)
        answer = messagebox.askyesno(
            "Geçici dosyaları sil",
            f"{count} adet, toplam {fmt_size(total_bytes)} boyutunda geçici dosya silinecek.\n\n"
            "Yalnızca kullanıcı geçici klasörlerinde bulunan ve en az 24 saat önce değiştirilmiş "
            "normal dosyalar hedeflenir. Açık/kilitli veya artık uygun olmayan dosyalar atlanır.\n\n"
            "Devam etmek istiyor musunuz?",
            parent=self.root)
        if not answer:
            return
        self.storage_busy = True
        self.storage_scan_button.configure(state="disabled")
        self.storage_clean_button.configure(state="disabled")
        self.storage_status.configure(text="Önizlemede listelenen dosyalar tekrar doğrulanıyor ve temizleniyor…",
                                      fg=AMBER)
        candidates = list(self.storage_candidates)
        threading.Thread(target=self._storage_clean_worker,
                         args=(candidates,), daemon=True).start()

    def _storage_clean_worker(self, candidates):
        try:
            removed, freed, skipped = delete_temp_files(candidates)
            self.q.put(("storage_clean_done", removed, freed, skipped))
        except Exception as exc:
            self.q.put(("storage_clean_error", str(exc)))

    def _finish_storage_scan(self, candidates, errors, limited):
        self.storage_busy = False
        # Silme işlemi yalnızca tabloda görünür olan önizleme satırlarını kapsar.
        # Tarama 1000'den fazla dosya bulursa diğerleri kullanıcıya gösterilmeden silinmez.
        self.storage_candidates = list(candidates[:1000])
        for item in self.storage_tree.get_children():
            self.storage_tree.delete(item)
        total_bytes = sum(item.size for item in candidates)
        for item in candidates[:1000]:
            self.storage_tree.insert("", "end", values=(
                item.path, fmt_size(item.size),
                datetime.fromtimestamp(item.mtime).strftime("%d.%m.%Y %H:%M")))
        shown = min(len(candidates), 1000)
        text = (f"Bulunan dosya: {len(candidates)}  •  Toplam boyut: {fmt_size(total_bytes)}  •  "
                f"Yaş eşiği: 24 saat")
        if shown < len(candidates):
            text += f"  •  İlk {shown} dosya gösteriliyor ve yalnızca bunlar silme önizlemesine dahil"
        if limited:
            text += "  •  Güvenlik sınırı nedeniyle tarama 20.000 dosyada durdu"
        if errors:
            text += f"  •  Erişim/okuma hatası: {errors}"
        if not candidates:
            text = "Uygun geçici dosya bulunamadı. Sistem ve kullanıcı klasörleri korunmuştur."
        self.storage_status.configure(text=text, fg=GREEN if candidates else FG_DIM)
        self.storage_scan_button.configure(state="normal")
        self.storage_clean_button.configure(
            state="normal" if self.storage_candidates else "disabled")

    def _finish_storage_clean(self, removed, freed, skipped):
        self.storage_busy = False
        self.log("ok", f"Depolama temizliği: {removed} dosya, {fmt_size(freed)} silindi; {skipped} dosya atlandı")
        self.storage_status.configure(
            text=f"Temizlik tamamlandı: {removed} dosya silindi ({fmt_size(freed)}). "
                 f"Atlanan dosya: {skipped}. Son durumu görmek için yeniden tarayın.",
            fg=GREEN)
        self.storage_candidates = []
        for item in self.storage_tree.get_children():
            self.storage_tree.delete(item)
        self.storage_scan_button.configure(state="normal")
        self.storage_clean_button.configure(state="disabled")

    def _finish_storage_error(self, message):
        self.storage_busy = False
        self.storage_status.configure(text=f"Depolama işlemi başarısız: {message}", fg=RED)
        self.storage_scan_button.configure(state="normal")
        self.storage_clean_button.configure(
            state="normal" if self.storage_candidates else "disabled")

    def _build_header(self, main):
        hdr = tk.Frame(main, bg=BG)
        hdr.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        if self.logo_img is not None:
            tk.Label(hdr, image=self.logo_img, bg=BG).pack(side="left", padx=(0, 12))
        tb = tk.Frame(hdr, bg=BG)
        tb.pack(side="left")
        tk.Label(tb, text=f"{APP_NAME} ({APP_SHORT})", bg=BG, fg=FG,
                 font=(FONT, 17, "bold")).pack(anchor="w")
        tk.Label(tb, text=f"{os_pretty()}  •  RAM Temizleme ve Optimizasyon Aracı",
                 bg=BG, fg=FG_DIM, font=(FONT, 9)).pack(anchor="w")

        if has_privileges():
            text = "●  ROOT YETKİSİ" if IS_LINUX else "●  YÖNETİCİ"
            bg, fg = "#10331f", GREEN
        else:
            text = "●  SUDO YOK" if IS_LINUX else "●  STANDART KULLANICI"
            bg, fg = "#3a2a0a", AMBER
        tk.Label(hdr, text=text, bg=bg, fg=fg, font=(FONT, 9, "bold"),
                 padx=12, pady=5).pack(side="right")

    def _build_banner(self, main):
        self.banner = tk.Label(main, text="", bg="#3a2a0a", fg=AMBER, anchor="w",
                               justify="left", font=(FONT, 10, "bold"),
                               padx=12, pady=7, wraplength=800)
        self.banner.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        self._refresh_banner()

    def _refresh_banner(self):
        msgs = []
        if IS_LINUX and not is_root_linux():
            msgs.append("Tam temizlik için sudo ile çalıştırın:  sudo python3 cramc.py")
        elif IS_WINDOWS and not is_admin_windows():
            msgs.append("Tam temizlik için programı Yönetici olarak çalıştırın")
        if IS_WINDOWS and psutil is None:
            msgs.append("psutil modülü bulunamadı; kaynak kodla çalıştırıyorsanız psutil kurun")
        if msgs:
            self.banner.configure(text="⚠  " + "\n⚠  ".join(msgs))
            self.banner.grid()
        else:
            self.banner.grid_remove()

    # ---- sol sütun
    def _build_left(self, parent):
        # Canlı RAM kartı
        card, head, body = make_card(parent, "ANLIK RAM KULLANIMI")
        card.pack(fill="x", pady=(0, 8))
        tk.Label(head, text="●  CANLI", bg=CARD, fg=GREEN,
                 font=(FONT, 8, "bold")).pack(side="right")
        top = tk.Frame(body, bg=CARD)
        top.pack(fill="x")
        self.pct_label = tk.Label(top, text="0%", bg=CARD, fg=FG,
                                  font=(FONT, 30, "bold"))
        self.pct_label.pack(side="left")
        tk.Label(top, text="kullanılan", bg=CARD, fg=FG_DIM,
                 font=(FONT, 9)).pack(side="left", padx=(8, 0), pady=(14, 0))
        self.bar = ttk.Progressbar(body, style="Ram.Horizontal.TProgressbar",
                                   orient="horizontal", mode="determinate",
                                   maximum=100)
        self.bar.pack(fill="x", pady=(2, 10))
        stats = tk.Frame(body, bg=CARD)
        stats.pack(fill="x")
        stats.columnconfigure((0, 1, 2, 3), weight=1, uniform="s")
        self.st_total = self._stat_box(stats, 0, "TOPLAM", FG)
        self.st_used = self._stat_box(stats, 1, "KULLANILAN", BLUE)
        self.st_free = self._stat_box(stats, 2, "KULLANILABİLİR", GREEN)
        self.st_cache = self._stat_box(stats, 3, "ÖNBELLEK", CYAN)

        # Sistem özeti
        card, head, body = make_card(parent, "SİSTEM ÖZETİ")
        card.pack(fill="x", pady=(0, 8))
        grid = tk.Frame(body, bg=CARD)
        grid.pack(fill="x")
        grid.columnconfigure((0, 1, 2, 3), weight=1, uniform="t")
        self.t_swap = self._tile(grid, 0, "SWAP", with_bar=True)
        self.t_proc = self._tile(grid, 1, "İŞLEM")
        self.t_last = self._tile(grid, 2, "SON TEMİZLİK")
        self.t_sess = self._tile(grid, 3, "OTURUM")

        # Tahmini kazanç
        card, head, body = make_card(parent, "TAHMİNİ KAZANÇ")
        card.pack(fill="x", pady=(0, 8))
        tk.Label(head, text="●  CANLI HESAP", bg=CARD, fg=BLUE,
                 font=(FONT, 8, "bold")).pack(side="right")
        row = tk.Frame(body, bg=CARD)
        row.pack(fill="x")
        self.est_value = tk.Label(row, text="—", bg=CARD, fg=GREEN,
                                  font=(FONT, 20, "bold"))
        self.est_value.pack(side="left")
        self.est_sub = tk.Label(row, text="", bg=CARD, fg=FG_DIM, justify="right",
                                font=(FONT, 8))
        self.est_sub.pack(side="right")
        self.est_detail = tk.Label(body, text="", bg=CARD, fg="#b7b7c0", anchor="w",
                                   justify="left", wraplength=390, font=(FONT, 8))
        self.est_detail.pack(fill="x", pady=(4, 0))
        tk.Label(body, text="Kernel/process verilerinden hesaplanan aday havuzu üst sınırıdır; gerçek serbest kalan RAM daha düşük olabilir.",
                 bg=CARD, fg="#777783", anchor="w", wraplength=420,
                 justify="left", font=(FONT, 7)).pack(fill="x")

        # Ana buton
        self.button = tk.Button(
            parent, text="RAM TEMİZLE", command=self.on_clean, bg=GREEN,
            fg="#06220f", activebackground=GREEN_DARK, activeforeground="#06220f",
            disabledforeground="#0b3a1c", relief="flat", bd=0, cursor="hand2",
            font=(FONT, 14, "bold"), pady=11)
        self.button.pack(fill="x")
        self.button.bind("<Enter>", lambda e: self._btn_hover(True))
        self.button.bind("<Leave>", lambda e: self._btn_hover(False))
        self.busy_bar = ttk.Progressbar(parent, style="Busy.Horizontal.TProgressbar",
                                        orient="horizontal", mode="indeterminate")
        self.busy_bar.pack(fill="x", pady=(2, 0))
        self.notice = tk.Label(parent, text="", bg=BG, fg=GREEN, height=2,
                               wraplength=410, anchor="n",
                               font=(FONT, 11, "bold"))
        self.notice.pack(fill="x", pady=(6, 0))

    def _stat_box(self, parent, col, title, color):
        box = tk.Frame(parent, bg=CARD)
        box.grid(row=0, column=col, sticky="nsew", padx=2)
        tk.Label(box, text=title, bg=CARD, fg=FG_DIM,
                 font=(FONT, 8, "bold")).pack()
        gb = tk.Label(box, text="-- GB", bg=CARD, fg=color, font=(FONT, 12, "bold"))
        gb.pack(pady=(2, 0))
        pc = tk.Label(box, text="--%", bg=CARD, fg=FG_DIM, font=(FONT, 9))
        pc.pack()
        return gb, pc

    def _tile(self, parent, col, title, with_bar=False):
        f = tk.Frame(parent, bg=CARD2, highlightbackground=CARD_BORDER,
                     highlightthickness=1)
        f.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 4, 0))
        tk.Label(f, text=title, bg=CARD2, fg=FG_DIM,
                 font=(FONT, 7, "bold")).pack(anchor="w", padx=8, pady=(7, 0))
        val = tk.Label(f, text="--", bg=CARD2, fg=FG, font=(FONT, 10, "bold"))
        val.pack(anchor="w", padx=8)
        bar = None
        if with_bar:
            bar = ttk.Progressbar(f, style="Swap.Horizontal.TProgressbar",
                                  orient="horizontal", mode="determinate", maximum=100)
            bar.pack(fill="x", padx=8, pady=(2, 1))
        else:
            tk.Frame(f, bg=CARD2, height=9).pack()
        sub = tk.Label(f, text="", bg=CARD2, fg=FG_DIM, font=(FONT, 8))
        sub.pack(anchor="w", padx=8, pady=(0, 7))
        return val, sub, bar

    # ---- sağ sütun
    def _build_right(self, parent):
        # Açılır/kapanır ayarlar kartı
        self.settings_card = tk.Frame(parent, bg=CARD, highlightbackground=CARD_BORDER,
                                      highlightcolor=CARD_BORDER, highlightthickness=1)
        self.settings_card.pack(fill="x", pady=(0, 8))
        head = tk.Frame(self.settings_card, bg=CARD, cursor="hand2")
        head.pack(fill="x", padx=16, pady=(10, 8))
        title = tk.Label(head, text="⚙  TEMİZLİK SEÇENEKLERİ", bg=CARD, fg=FG_DIM,
                         font=(FONT, 8, "bold"), cursor="hand2")
        title.pack(side="left")
        self.arrow = tk.Label(head, text="▾", bg=CARD, fg=BLUE,
                              font=(FONT, 11, "bold"), cursor="hand2")
        self.arrow.pack(side="right")
        for w in (head, title, self.arrow):
            w.bind("<Button-1>", lambda e: self._toggle_settings())
        self.settings_body = tk.Frame(self.settings_card, bg=CARD)
        self._build_settings_body(self.settings_body)
        self._set_settings_open(self.settings_open, save=False)

        # İşlem günlüğü
        card, head, body = make_card(parent, "İŞLEM GÜNLÜĞÜ")
        card.pack(fill="both", expand=True)
        GhostButton(head, "TEMİZLE", self._clear_log).pack(side="right")
        self.log_text = tk.Text(body, height=6, width=40, wrap="word", bg="#0d0d0f",
                                fg="#b7b7c0", insertbackground="#0d0d0f", bd=0,
                                highlightthickness=0, padx=8, pady=6,
                                font=(MONO, 8), state="disabled", cursor="arrow")
        sb = ttk.Scrollbar(body, orient="vertical", style="Dark.Vertical.TScrollbar",
                           command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)
        for tag, color in (("ts", "#5b5b66"), ("info", "#b7b7c0"), ("ok", GREEN),
                           ("warn", AMBER), ("err", RED)):
            self.log_text.tag_configure(tag, foreground=color)

    def _build_settings_body(self, parent):
        def row(text, desc, var):
            CheckRow(parent, text, desc, var).pack(fill="x", pady=3)

        if IS_LINUX:
            row("PageCache (Sayfa Önbelleği)",
                "Dosya içeriği önbelleği  •  drop_caches=1", self.v_pagecache)
            row("Dentries & Inodes",
                "Dizin/dosya yapısı önbelleği  •  drop_caches=2", self.v_dentries)
            row("Swap Sıfırlama",
                "Swap'i RAM'e geri alıp yeniden açar  •  yavaş olabilir", self.v_swap)
            row("Önce sync çalıştır",
                "Yazılmamış verileri diske yazar (önerilir)", self.v_sync)
        else:
            row("Arka Plan Working Set",
                "Süreçlerin kullanılmayan çalışma belleğini boşaltır", self.v_ws)
            row("Sistem Önbelleği",
                "Dosya sistemi önbelleğini küçültür  •  Yönetici gerekir",
                self.v_syscache)

        tk.Frame(parent, bg=CARD_BORDER, height=1).pack(fill="x", pady=(8, 8))
        tk.Label(parent, text="OTOMATİK ZAMANLAYICI", bg=CARD, fg=FG_DIM,
                 font=(FONT, 8, "bold")).pack(anchor="w", pady=(0, 4))
        row("Otomatik temizleme",
            "RAM kullanımı eşiği aşınca kendiliğinden temizler", self.v_auto)
        self._slider_row(parent, "Kullanım eşiği", self.v_thr, 50, 95, 5,
                         lambda v: f"%{v}")
        self._slider_row(parent, "Bekleme süresi", self.v_cd, 1, 60, 1,
                         lambda v: f"{v} dk")

    def _slider_row(self, parent, title, var, lo, hi, step, fmt):
        f = tk.Frame(parent, bg=CARD)
        f.pack(fill="x", pady=(4, 0))
        top = tk.Frame(f, bg=CARD)
        top.pack(fill="x")
        tk.Label(top, text=title, bg=CARD, fg=FG, font=(FONT, 9)).pack(side="left")
        val = tk.Label(top, text=fmt(var.get()), bg=CARD, fg=BLUE,
                       font=(FONT, 9, "bold"))
        val.pack(side="right")
        FlatSlider(f, var, lo, hi, step).pack(fill="x")
        var.trace_add("write", lambda *a: val.configure(text=fmt(var.get())))

    def _toggle_settings(self):
        self._set_settings_open(not self.settings_open)

    def _set_settings_open(self, is_open, save=True):
        self.settings_open = is_open
        if is_open:
            self.settings_body.pack(fill="x", padx=16, pady=(0, 12))
            self.arrow.configure(text="▾")
        else:
            self.settings_body.pack_forget()
            self.arrow.configure(text="▸")
        if save:
            self._schedule_save()

    def _fit_window(self):
        """Sekmeli arayüzü ekrana sığdır; pencere yeniden boyutlandırılabilir."""
        root = self.root
        root.update_idletasks()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        req_w, req_h = root.winfo_reqwidth(), root.winfo_reqheight()
        w = min(max(req_w, 980), max(640, sw - 40))
        h = min(max(req_h, 720), max(520, sh - 80))
        x = max((sw - w) // 2, 10)
        y = max((sh - h) // 3, 10)
        root.geometry(f"{w}x{h}+{x}+{y}")
        root.minsize(min(900, max(640, sw - 40)), min(620, max(520, sh - 80)))
        root.resizable(True, True)

    # ---------------------------------------------------------- günlük/bildirim
    def log(self, level, msg):
        icon = {"ok": "✓", "warn": "!", "err": "✗"}.get(level, "•")
        t = self.log_text
        t.configure(state="normal")
        t.insert("end", datetime.now().strftime("%H:%M:%S") + "  ", "ts")
        t.insert("end", f"{icon} {msg}\n", level)
        lines = int(t.index("end-1c").split(".")[0])
        if lines > 400:
            t.delete("1.0", f"{lines - 400}.0")
        t.configure(state="disabled")
        t.see("end")

    def _clear_log(self):
        t = self.log_text
        t.configure(state="normal")
        t.delete("1.0", "end")
        t.configure(state="disabled")

    def _log_startup(self):
        self.log("info", f"{APP_SHORT} v{APP_VERSION} başlatıldı")
        try:
            s = take_snapshot()
            self.log("info", f"{os_pretty()}  •  toplam RAM {fmt_size(s.total)}")
        except Exception as exc:
            self.log("err", f"Bellek bilgisi okunamadı: {exc}")
        if has_privileges():
            self.log("ok", "Yetki durumu: tam temizlik mümkün")
        elif IS_LINUX:
            self.log("warn", "Root yetkisi yok: Tam temizlik için sudo ile çalıştırın")
        else:
            self.log("warn", "Yönetici yetkisi yok: temizlik sınırlı olabilir")

    def _show_notice(self, text, color, seconds=10):
        if self._notice_job is not None:
            self.root.after_cancel(self._notice_job)
        self.notice.configure(text=text, fg=color)
        self._notice_job = self.root.after(
            seconds * 1000, lambda: self.notice.configure(text=""))

    def _btn_hover(self, inside):
        if not self.busy:
            self.button.configure(bg=GREEN_DARK if inside else GREEN)

    # ------------------------------------------------------------ ayar takibi
    def get_options(self) -> CleanOptions:
        return CleanOptions(
            pagecache=bool(self.v_pagecache.get()),
            dentries=bool(self.v_dentries.get()),
            swap_reset=bool(self.v_swap.get()),
            sync_first=bool(self.v_sync.get()),
            working_set=bool(self.v_ws.get()),
            system_cache=bool(self.v_syscache.get()),
        )

    def _wire_traces(self):
        for var in (self.v_pagecache, self.v_dentries, self.v_swap, self.v_sync,
                    self.v_ws, self.v_syscache, self.v_auto, self.v_thr, self.v_cd):
            var.trace_add("write", self._on_setting_changed)

    def _on_setting_changed(self, *_):
        self._update_estimate()
        self._schedule_save()

    def _schedule_save(self):
        if self._save_job is not None:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(600, self._save_now)

    def _save_now(self):
        self._save_job = None
        save_settings({
            "version": 1,
            "opts": asdict(self.get_options()),
            "auto_enabled": bool(self.v_auto.get()),
            "auto_threshold": int(self.v_thr.get()),
            "auto_cooldown": int(self.v_cd.get()),
            "settings_open": self.settings_open,
            "last_clean_ts": self.last_clean_ts,
        })

    # ------------------------------------------------------- canlı güncelleme
    def _tick(self):
        try:
            snap = take_snapshot()
            self._last_snap = snap
            self._last_tick_err = None
            self._render_stats(snap)
            self._update_estimate()
            self._check_auto(snap)
        except Exception as exc:
            msg = str(exc)
            if msg != self._last_tick_err:
                self._last_tick_err = msg
                self.log("err", f"Bellek okunamadı: {msg}")
        finally:
            self.root.after(1000, self._tick)

    def _render_stats(self, s: MemSnapshot):
        total = s.total or 1
        used_pct = s.used / total * 100
        self.pct_label.configure(text=f"{used_pct:.0f}%")
        self.bar["value"] = used_pct
        color = BLUE if used_pct < 65 else (AMBER if used_pct < 85 else RED)
        self.style.configure("Ram.Horizontal.TProgressbar", background=color,
                             lightcolor=color, darkcolor=color)

        def put(box, value):
            box[0].configure(text=f"{value / GB:.2f} GB")
            box[1].configure(text=f"%{value / total * 100:.1f}")

        put(self.st_total, s.total)
        self.st_total[1].configure(text="100%")
        put(self.st_used, s.used)
        put(self.st_free, s.free)
        put(self.st_cache, s.cached)

        # Sistem özeti
        val, sub, bar = self.t_swap
        if s.swap_total > 0:
            sp = s.swap_used / s.swap_total * 100
            val.configure(text=f"{s.swap_used / GB:.1f}/{s.swap_total / GB:.1f} GB")
            sub.configure(text=f"%{sp:.0f} dolu")
            bar["value"] = sp
        else:
            val.configure(text="Yok")
            sub.configure(text="swap etkin değil")
            bar["value"] = 0

        val, sub, _ = self.t_proc
        val.configure(text=str(count_processes()))
        sub.configure(text="çalışan süreç")

        val, sub, _ = self.t_last
        if self.last_clean_ts:
            dt = datetime.fromtimestamp(self.last_clean_ts)
            same_day = dt.date() == datetime.now().date()
            val.configure(text=dt.strftime("%H:%M:%S" if same_day else "%d.%m %H:%M"))
            sub.configure(text=fmt_ago(self.last_clean_ts))
        else:
            val.configure(text="Henüz yok")
            sub.configure(text="-")

        val, sub, _ = self.t_sess
        val.configure(text=fmt_size(self.session_freed))
        sub.configure(text=f"{self.session_cleans} temizlik")

    def _update_estimate(self):
        snap = self._last_snap
        if snap is None:
            return
        opts = self.get_options()
        if not opts.any_selected():
            self.est_value.configure(text="—", fg=FG_DIM)
            self.est_sub.configure(text="seçenek seçilmedi")
            self.est_detail.configure(
                text="Sağdaki panelden en az bir temizlik seçeneği işaretleyin.")
            return
        total, items = estimate_gain(opts, snap, self.ws_bytes)
        pct = total / (snap.total or 1) * 100
        self.est_value.configure(text=f"≈ {fmt_size(total)}",
                                 fg=GREEN if total >= 0 else AMBER)
        self.est_sub.configure(
            text=f"{total / MB:.0f} MB  •  {total / GB:.2f} GB\n"
                 f"toplam RAM'in %{pct:.1f}'i · üst sınır")
        lines = []
        for label, v in items:
            lines.append(f"•  {label}: " + (f"−{fmt_size(-v)}" if v < 0
                                            else f"≈ {fmt_size(v)}"))
        self.est_detail.configure(text="\n".join(lines))

    def _ws_loop(self):
        """Windows: süreçlerin özel (USS) resident belleğini periyodik ölçer."""
        while not self._stop:
            total_uss = 0
            try:
                for proc in psutil.process_iter():
                    try:
                        # psutil 8.x, memory_full_info() yerine memory_footprint()
                        # API'sini önerir. Eski sürümler için geriye dönük uyumluluk.
                        footprint = getattr(proc, "memory_footprint", None)
                        mem = footprint() if callable(footprint) else proc.memory_full_info()
                        total_uss += int(getattr(mem, "uss", 0) or 0)
                    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                        continue
                    except Exception:
                        continue
                self.ws_bytes = total_uss
            except Exception:
                self.ws_bytes = 0
            for _ in range(6):
                if self._stop:
                    return
                time.sleep(1)

    # ------------------------------------------------------- otomatik temizlik
    def _check_auto(self, snap: MemSnapshot):
        if not self.v_auto.get() or self.busy:
            return
        used_pct = snap.used / (snap.total or 1) * 100
        thr = int(self.v_thr.get())
        if used_pct < thr:
            return
        if time.time() - self.last_auto_ts < int(self.v_cd.get()) * 60:
            return
        self.last_auto_ts = time.time()
        self.log("info", f"Otomatik zamanlayıcı: kullanım %{used_pct:.0f} ≥ eşik %{thr}")
        self.on_clean(auto=True)

    # ------------------------------------------------------------- temizleme
    def on_clean(self, auto=False):
        if self.busy:
            return
        opts = self.get_options()
        if not opts.any_selected():
            if not auto:
                self._show_notice("En az bir temizlik seçeneği seçin.", AMBER)
                self.log("warn", "Temizlik için seçenek seçilmedi")
            return
        if IS_LINUX and not is_root_linux():
            if not auto:
                self._show_notice("Tam temizlik için sudo ile çalıştırın", AMBER)
                self.log("warn", "Root yetkisi yok: Tam temizlik için sudo ile çalıştırın")
            elif not self._warned_auto:
                self._warned_auto = True
                self.log("warn", "Otomatik temizleme için root yetkisi gerekli")
            return

        self.busy = True
        self._swap_running = bool(IS_LINUX and opts.swap_reset)
        self.button.configure(text="TEMİZLENİYOR...", state="disabled", bg=GREEN_DARK)
        self.busy_bar.start(12)
        self.notice.configure(text="Temizlik sürüyor, lütfen bekleyin...", fg=FG_DIM)
        threading.Thread(target=self._worker, args=(opts, auto), daemon=True).start()

    def _worker(self, opts, auto):
        """Arka plan iş parçacığı: arayüze dokunmaz, her şeyi kuyruğa yazar."""
        def log(level, msg):
            self.q.put(("log", level, msg))
        try:
            before = take_snapshot()
            log("info", f"Temizlik başlatıldı ({'otomatik' if auto else 'manuel'})  •  "
                        f"önce: kullanılan {fmt_size(before.used)}, "
                        f"kullanılabilir {fmt_size(before.free)}")
            if IS_LINUX:
                ok, err = clean_linux(opts, log)
            else:
                ok, err = clean_windows(opts, log)
            time.sleep(1.5)  # sayaçların güncellenmesi için kısa bekleme
            after = take_snapshot()
            gained = after.free - before.free
            log("info", f"Sonra: kullanılan {fmt_size(after.used)}, "
                        f"kullanılabilir {fmt_size(after.free)}  (fark {fmt_size(gained)})")
            self.q.put(("done", ok, err, gained, auto))
        except Exception as exc:
            log("err", f"Beklenmeyen hata: {exc}")
            self.q.put(("done", False, str(exc), 0, auto))

    def _poll_queue(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item[0] == "log":
                    self.log(item[1], item[2])
                elif item[0] == "done":
                    self._finish(*item[1:])
                elif item[0] == "storage_scan_done":
                    self._finish_storage_scan(*item[1:])
                elif item[0] == "storage_clean_done":
                    self._finish_storage_clean(*item[1:])
                elif item[0] in ("storage_scan_error", "storage_clean_error"):
                    self._finish_storage_error(item[1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _finish(self, ok, err, gained, auto):
        self.busy = False
        self._swap_running = False
        self.busy_bar.stop()
        self.button.configure(text="RAM TEMİZLE", state="normal", bg=GREEN)
        if not ok:
            self._show_notice(f"Hata: {err}" if err else "Temizlik tamamlanamadı", RED)
            return
        gained_mb = max(gained, 0) / MB
        self.last_clean_ts = time.time()
        self.session_cleans += 1
        self.session_freed += max(gained, 0)
        if gained_mb >= 1:
            self._show_notice(f"Kullanılabilir RAM ölçümünde +{gained_mb:.0f} MB fark", GREEN)
            self.log("ok", f"Kullanılabilir RAM ölçüm farkı: +{gained_mb:.0f} MB")
        else:
            self._show_notice("Temizlik tamamlandı (belirgin kullanılabilir RAM artışı ölçülmedi).",
                              GREEN)
            self.log("ok", "Temizlik tamamlandı; belirgin kullanılabilir RAM artışı ölçülmedi")
        self._schedule_save()
        try:
            snap = take_snapshot()
            self._last_snap = snap
            self._render_stats(snap)
            self._update_estimate()
        except Exception:
            pass

    def _on_close(self):
        if self.busy and self._swap_running:
            self._show_notice("Swap sıfırlama sürüyor, bitmesini bekleyin.", AMBER)
            return
        if self.storage_busy:
            self._show_notice("Depolama taraması/temizliği sürüyor; işlem bitince kapatın.", AMBER)
            return
        self._stop = True
        self._save_now()
        self.root.destroy()


# =========================================================================== #
#  GİRİŞ NOKTASI
# =========================================================================== #
def selftest() -> int:
    """Arayüzsüz motor testi (--selftest)."""
    print(f"{APP_NAME} v{APP_VERSION} selftest  |  {os_pretty()}  |  python {platform.python_version()}")
    s = take_snapshot()
    print(f"RAM toplam {fmt_size(s.total)}, kullanılan {fmt_size(s.used)}, "
          f"kullanılabilir {fmt_size(s.free)}, önbellek {fmt_size(s.cached)}, "
          f"swap {fmt_size(s.swap_used)}/{fmt_size(s.swap_total)}")
    print(f"İşlem sayısı: {count_processes()}")
    total, items = estimate_gain(CleanOptions(swap_reset=True), s, 0)
    print(f"Tahmini kazanç: {fmt_size(total)}")
    for label, v in items:
        print(f"   {label}: {fmt_size(v)}")
    png = generate_logo_png(32)
    sig_ok = png[:8] == b"\x89PNG\r\n\x1a\n"
    print(f"Logo PNG: {len(png)} bayt, imza {'OK' if sig_ok else 'HATA'}")
    print(f"Yetki: {'var' if has_privileges() else 'yok'}  |  ayar dosyası: {settings_path()}")
    print(f"tkinter: {'var' if TK_OK else 'YOK (sudo apt install -y python3-tk)'}  |  "
          f"psutil: {'var' if psutil else 'yok'}")
    try:
        temp_items, temp_errors, temp_limited = scan_temp_files()
        temp_bytes = sum(item.size for item in temp_items)
        print(f"Geçici dosya önizlemesi: {len(temp_items)} dosya, {fmt_size(temp_bytes)} "
              f"(hata={temp_errors}, limit={temp_limited}; silme yapılmadı)")
    except Exception as exc:
        print(f"Geçici dosya taraması kullanılamıyor: {exc}")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if not TK_OK:
        print("tkinter bulunamadı. Lubuntu/Ubuntu için kurulum:")
        print("    sudo apt install -y python3-tk")
        return 1
    if not (IS_LINUX or IS_WINDOWS):
        print(f"Desteklenmeyen işletim sistemi: {OS_NAME}")
        return 2
    if IS_WINDOWS:
        try:  # Windows'ta bulanık yazıyı önle
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"Pencere açılamadı (ekran bulunamadı?): {exc}")
        print("sudo ile açıyorsanız deneyin:  sudo -E python3 cramc.py")
        return 2
    CramcApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
