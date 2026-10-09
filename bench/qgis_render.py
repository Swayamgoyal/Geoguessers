"""Open a DEM in QGIS (headless) and render one 1920x1080 map view, timing each step.

Runs inside QGIS's own Python (python-qgis-ltr.bat), launched by bench/experiments/e1_qgis.py:
    qgis_render.py <raster> <overviews: use|none> <view: full|zoom> <out.png>
Prints a JSON line: t_internal (= render time), t_init, t_open, peak_mb, filled (fraction of
non-transparent pixels in the rendered image, a sanity check that something was drawn).
'none' hides the file's pyramid (GDAL open option OVERVIEW_LEVEL=NONE), as for a DEM without one.
'zoom' is a 1920 m x 1080 m window at the centre of the layer (1 m per pixel at 1 m resolution).
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import time

t0 = time.perf_counter()
k32 = ctypes.windll.kernel32
k32.GetCurrentProcess.restype = wt.HANDLE  # pseudo-handle -1: must not be truncated to 32 bits
k32.SetProcessAffinityMask.argtypes = [wt.HANDLE, ctypes.c_size_t]
k32.K32GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD]
SELF = k32.GetCurrentProcess()
mask = int(os.environ.get("BENCH_AFFINITY_MASK", "0"))
if mask and not k32.SetProcessAffinityMask(SELF, mask):
    print(json.dumps({"error": "SetProcessAffinityMask failed"}))
    sys.exit(1)

from qgis.core import (QgsApplication, QgsMapRendererParallelJob, QgsMapSettings,  # noqa: E402
                       QgsRasterLayer, QgsRectangle)
from qgis.PyQt.QtCore import QSize  # noqa: E402
from qgis.PyQt.QtGui import QColor  # noqa: E402

path, overviews, view, out_png = sys.argv[1:5]
app = QgsApplication([], False)
app.initQgis()
t_init = time.perf_counter() - t0

t = time.perf_counter()
uri = path if overviews == "use" else f"{path}|option:OVERVIEW_LEVEL=NONE"
layer = QgsRasterLayer(uri, "dem", "gdal")  # includes QGIS's default min/max stretch estimate
if not layer.isValid():
    print(json.dumps({"error": "layer not valid"}))
    sys.exit(1)
t_open = time.perf_counter() - t

ext = layer.extent()
if view == "zoom":
    c = ext.center()
    ext = QgsRectangle(c.x() - 960, c.y() - 540, c.x() + 960, c.y() + 540)
settings = QgsMapSettings()
settings.setLayers([layer])
settings.setDestinationCrs(layer.crs())
settings.setOutputSize(QSize(1920, 1080))
settings.setExtent(ext)
settings.setBackgroundColor(QColor(0, 0, 0, 0))  # transparent, so 'filled' counts only drawn DEM pixels

t = time.perf_counter()
job = QgsMapRendererParallelJob(settings)
job.start()
job.waitForFinished()
img = job.renderedImage()
t_render = time.perf_counter() - t

img.save(out_png)
step = 8  # sample every 8th pixel for the fill check
pts = [(x, y) for x in range(0, img.width(), step) for y in range(0, img.height(), step)]
filled = sum(1 for x, y in pts if (img.pixel(x, y) >> 24) & 0xFF) / len(pts)


class _Mem(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t)] + \
               [(f"f{i}", ctypes.c_size_t) for i in range(7)]


m = _Mem(cb=ctypes.sizeof(_Mem))
k32.K32GetProcessMemoryInfo(SELF, ctypes.byref(m), m.cb)
print(json.dumps({"t_internal": round(t_render, 4), "t_init": round(t_init, 3), "t_open": round(t_open, 4),
                  "peak_mb": round(m.PeakWorkingSetSize / 2**20, 1), "filled": round(filled, 3)}), flush=True)
os._exit(0)  # skip exitQgis(): headless QGIS returns a non-zero code from its shutdown
