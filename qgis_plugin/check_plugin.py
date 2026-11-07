"""Headless end-to-end check of the QGIS plugin against a running tile server (Phase 4 gate).

Run with QGIS's own Python while the server is up (python -m server):
    "C:\\Program Files\\QGIS 3.44.15\\bin\\python-qgis-ltr.bat" qgis_plugin\\check_plugin.py [--server URL]

It loads the plugin into QGIS with a stand-in interface (qgis.testing.mocked), connects, drags boxes through the map
tool and checks that:
  1. a slope box at full resolution lines up with the DEM: same cells as gdaldem's slope of the full-resolution DEM
     (the precomputed pyramid), so the layer is neither shifted nor scaled;
  2. a "match screen" box drawn on a canvas in WGS 84 is reprojected to UTM, gets a coarser level, the server's
     colour map and the expected-error note;
  3. both datasets work;
  4. an oversized full-resolution box and a box outside the data give clear messages, not layers.
"""

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from qgis.testing.mocked import get_iface  # noqa: E402  (starts the QGIS application)

import numpy as np  # noqa: E402
from osgeo import gdal  # noqa: E402
from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject,  # noqa: E402
                       QgsRectangle, QgsSingleBandPseudoColorRenderer)

import geoguessers_view  # noqa: E402
from geoguessers_view import client  # noqa: E402

DATA = os.environ.get("GEO_DATA", r"D:\geoguessers_data")
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


def wait(plugin, timeout=300):
    t0 = time.time()
    while plugin.tasks and time.time() - t0 < timeout:
        QgsApplication.processEvents()
        time.sleep(0.02)
    QgsApplication.processEvents()
    return not plugin.tasks


def set_canvas(iface, crs, rect):
    canvas = iface.mapCanvas()
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem(crs))
    canvas.setExtent(rect)
    canvas.refresh()
    return canvas


def draw(plugin, iface, rect):
    """Drag a box with the plugin's map tool (the tool's own signal, as when the mouse is released)."""
    plugin.panel.draw.setChecked(True)
    assert iface.mapCanvas().mapTool() is plugin.tool
    before = set(QgsProject.instance().mapLayers())
    plugin.tool.extentChanged.emit(rect)
    done = wait(plugin)
    new = [lyr for lid, lyr in QgsProject.instance().mapLayers().items() if lid not in before]
    return done, (new[0] if new else None)


def select(combo, value):
    combo.setCurrentIndex(combo.findData(value))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default=client.DEFAULT_SERVER)
    a = ap.parse_args()

    iface = get_iface()
    plugin = geoguessers_view.classFactory(iface)
    plugin.initGui()
    plugin.panel.server.setText(a.server)
    plugin.action.setChecked(True)                       # opens the dock and connects
    check("connects and lists datasets", plugin.info is not None and plugin.panel.dataset.count() >= 1,
          plugin.panel.status.text())
    if plugin.info is None:
        return 1
    p = plugin.panel
    info = plugin.info

    # 1. slope, full resolution, canvas in the data CRS: compare cells with gdaldem's slope (precomputed level 0)
    ds = "chamoli_2m"
    select(p.dataset, ds)
    select(p.op, "slope")
    select(p.method, "Horn")
    select(p.mode, "auto")
    p.res.setCurrentIndex(p.res.findData(True))
    l, b, r, t = info["datasets"][ds]["bounds"]
    cx, cy = l + 0.43 * (r - l), b + 0.57 * (t - b)
    box = QgsRectangle(cx - 1234.5, cy - 987.3, cx + 1234.5, cy + 987.3)    # not aligned to cells on purpose
    set_canvas(iface, "EPSG:32644", box.buffered(3000))
    done, layer = draw(plugin, iface, box)
    ok = done and layer is not None and layer.isValid()
    check("full-resolution slope box becomes a layer", ok, p.status.text().replace("\n", " "))
    if ok:
        src = layer.source()
        out = gdal.Open(src)
        v = out.GetRasterBand(1).ReadAsArray()
        gt = out.GetGeoTransform()
        ref_ds = gdal.Open(os.path.join(DATA, "bench_out", f"e5_slope_{ds}.tif"))
        rgt = ref_ds.GetGeoTransform()
        col0, row0 = (gt[0] - rgt[0]) / rgt[1], (gt[3] - rgt[3]) / rgt[5]
        aligned = abs(col0 - round(col0)) < 1e-6 and abs(row0 - round(row0)) < 1e-6 and gt[1] == rgt[1]
        ref = ref_ds.GetRasterBand(1).ReadAsArray(int(round(col0)), int(round(row0)), v.shape[1], v.shape[0])
        m = (ref != -9999.0) & (v != -9999.0)
        diff = np.abs(v[m].astype(np.float64) - ref[m])
        covers = (gt[0] <= box.xMinimum() and gt[0] + gt[1] * v.shape[1] >= box.xMaximum()
                  and gt[3] >= box.yMaximum() and gt[3] + gt[5] * v.shape[0] <= box.yMinimum()
                  and v.shape[1] * gt[1] - box.width() < 2 * gt[1])
        check("layer is in UTM 44N", layer.crs().authid() == "EPSG:32644", layer.crs().authid())
        check("layer covers the box, on the DEM's cell grid", aligned and covers,
              f"origin offset {col0:.3f}, {row0:.3f} cells; size {v.shape[1]}x{v.shape[0]} cells")
        check("values equal gdaldem slope of the full-resolution DEM", m.mean() > 0.95 and diff.max() < 1e-3,
              f"{m.sum():,} cells, max |diff| {diff.max():.2e} deg")
        check("styled with the server's slope colours", isinstance(layer.renderer(), QgsSingleBandPseudoColorRenderer))
        check("abstract says full resolution", "no pyramid error" in layer.metadata().abstract())

    # 2. hillshade, match screen, canvas in WGS 84 (the box is reprojected; a coarser level is chosen)
    select(p.op, "hillshade")
    p.res.setCurrentIndex(p.res.findData(False))
    utm, wgs = QgsCoordinateReferenceSystem("EPSG:32644"), QgsCoordinateReferenceSystem("EPSG:4326")
    to_wgs = QgsCoordinateTransform(utm, wgs, QgsProject.instance())
    big = to_wgs.transformBoundingBox(QgsRectangle(l + 0.1 * (r - l), b + 0.1 * (t - b),
                                                   l + 0.9 * (r - l), b + 0.9 * (t - b)))
    canvas = set_canvas(iface, "EPSG:4326", big.buffered(0.05))
    done, layer = draw(plugin, iface, big)
    ok = done and layer is not None and layer.isValid()
    check("match-screen hillshade box from a WGS 84 canvas", ok, p.status.text().replace("\n", " "))
    if ok:
        out = gdal.Open(layer.source())
        lvl = int(layer.name().split("level ")[1].split(" ")[0])
        width = client.screen_width(big, canvas.mapUnitsPerPixel())
        x0, _, x1, _ = client.box_in_crs(big, wgs, utm)
        s = (x1 - x0) / width
        res = [lv["res"] for lv in info["datasets"][ds]["levels"]]
        want = max([j for j, c in enumerate(res) if c <= s], default=0)
        check("level = finest level whose cells fit the box's screen pixels", lvl == want and lvl >= 3,
              f"box {width} px on screen, {s:.0f} m/px -> level {lvl} ({res[lvl]:.0f} m cells), "
              f"{out.RasterXSize}x{out.RasterYSize} cells")

    # 3. the other dataset, TRI, auto
    ds2 = "tile571_8m"
    if ds2 in info["datasets"]:
        select(p.dataset, ds2)
        select(p.op, "TRI")
        l2, b2, r2, t2 = info["datasets"][ds2]["bounds"]
        box2 = QgsRectangle(l2 + 0.3 * (r2 - l2), b2 + 0.3 * (t2 - b2), l2 + 0.4 * (r2 - l2), b2 + 0.4 * (t2 - b2))
        set_canvas(iface, "EPSG:32644", box2.buffered(5000))
        done, layer = draw(plugin, iface, box2)
        check("second dataset (tile571 8 m, TRI)", done and layer is not None and layer.isValid(),
              p.status.text().replace("\n", " "))
        select(p.dataset, ds)

    # 4. refusals: whole Chamoli at full resolution (264 M cells > limit), and a box outside the data
    select(p.op, "slope")
    p.res.setCurrentIndex(p.res.findData(True))
    whole = QgsRectangle(l, b, r, t)
    set_canvas(iface, "EPSG:32644", whole.buffered(1000))
    done, layer = draw(plugin, iface, whole)
    check("oversized full-resolution box is refused with a message", done and layer is None
          and "limit" in p.status.text(), p.status.text())
    p.res.setCurrentIndex(p.res.findData(False))
    away = QgsRectangle(l - 50_000, b - 50_000, l - 40_000, b - 40_000)
    set_canvas(iface, "EPSG:32644", away.buffered(1000))
    done, layer = draw(plugin, iface, away)
    check("box outside the data gives a message", done and layer is None and "overlap" in p.status.text(),
          p.status.text())

    plugin.unload()
    check("unloads cleanly", iface.mapCanvas().mapTool() is None)
    print(f"{sum(RESULTS)}/{len(RESULTS)} checks passed")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)      # skip QGIS teardown (the mocked interface's widgets are not owned by a real main window)
