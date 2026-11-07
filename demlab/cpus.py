"""Core classes of this hybrid CPU, and pinning of single threads to a set of cores (Windows).

The Core Ultra 9 185H has 6 performance cores (12 logical CPUs), 8 efficiency cores and 2 low-power efficiency
cores. Windows reports an EfficiencyClass per logical CPU (higher = faster). The tile server runs foreground tiles
on the performance cores and prefetch on the efficiency cores (E3: mixing them slows the foreground).

    p, e, lp = core_sets()          # lists of logical CPU indices
    pin_current_thread(p)
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys


def cpu_set_info():
    """{logical CPU index: (EfficiencyClass, LastLevelCacheIndex)}; (0, 0) everywhere on non-Windows machines."""
    if sys.platform != "win32":
        return {i: (0, 0) for i in range(os.cpu_count())}
    k32 = ctypes.windll.kernel32
    n = wt.ULONG()
    k32.GetSystemCpuSetInformation(None, 0, ctypes.byref(n), None, 0)
    buf = (ctypes.c_byte * n.value)()
    k32.GetSystemCpuSetInformation(buf, n, ctypes.byref(n), None, 0)
    out, off = {}, 0
    while off < n.value:
        size = ctypes.c_uint32.from_buffer(buf, off).value
        # SYSTEM_CPU_SET_INFORMATION: Size, Type, Id (4 B each), Group (2), LogicalProcessorIndex (1),
        # CoreIndex, LastLevelCacheIndex, NumaNodeIndex, EfficiencyClass (1 each)
        lp = ctypes.c_uint8.from_buffer(buf, off + 14).value
        llc = ctypes.c_uint8.from_buffer(buf, off + 16).value
        out[lp] = (ctypes.c_uint8.from_buffer(buf, off + 18).value, llc)
        off += size
    return out


def efficiency_classes():
    """{logical CPU index: EfficiencyClass} (higher = faster)."""
    return {c: e for c, (e, _) in cpu_set_info().items()}


def core_sets():
    """(performance, efficiency, low_power) logical CPU lists. Windows gives this CPU's efficiency and low-power
    cores the same EfficiencyClass, but they sit behind different last-level caches: within the slower class, the
    smaller cache group is taken as the low-power cores. On a non-hybrid machine all CPUs are 'performance'."""
    info = cpu_set_info()
    classes = sorted({e for e, _ in info.values()}, reverse=True)
    perf = sorted(c for c, (e, _) in info.items() if e == classes[0])
    rest = [c for c, (e, _) in info.items() if e != classes[0]]
    if not rest:
        return perf, [], []
    if len(classes) > 2:
        eff = sorted(c for c in rest if info[c][0] == classes[1])
        return perf, eff, sorted(set(rest) - set(eff))
    groups = {}
    for c in rest:
        groups.setdefault(info[c][1], []).append(c)
    if len(groups) < 2:
        return perf, sorted(rest), []
    by_size = sorted(groups.values(), key=len)
    low = sorted(by_size[0])
    return perf, sorted(set(rest) - set(low)), low


def pin_current_thread(cpus):
    """Restrict the calling thread to the given logical CPUs (no-op if empty or not on Windows)."""
    if not cpus or sys.platform != "win32":
        return False
    mask = 0
    for c in cpus:
        mask |= 1 << c
    k32 = ctypes.windll.kernel32
    k32.GetCurrentThread.restype = wt.HANDLE
    k32.SetThreadAffinityMask.argtypes = (wt.HANDLE, ctypes.c_size_t)
    k32.SetThreadAffinityMask.restype = ctypes.c_size_t
    return k32.SetThreadAffinityMask(k32.GetCurrentThread(), mask) != 0


def current_processor():
    """Logical CPU the calling thread runs on right now (Windows), else -1."""
    if sys.platform != "win32":
        return -1
    return ctypes.windll.kernel32.GetCurrentProcessorNumber()
