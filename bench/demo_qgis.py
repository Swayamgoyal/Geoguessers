"""Demo-video frames for the QGIS plugin (run by bench/demo_video.py with QGIS's own Python):
    python-qgis-ltr.bat bench/demo_qgis.py <server URL> <output folder>

Renders, with QGIS's map renderer (offscreen, no GUI window), the Chamoli DEM as a QGIS hillshade, the box the
user drags with the plugin's tool, and the slope layer the plugin adds for that box (requested from the running
tile server through the plugin's own client code, POST /view). Files are q1.png ... q4.png and captions.json.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "qgis_plugin"))

from qgis.testing import start_app  # noqa: E402

APP = start_app()

from qgis.core import (QgsCoordinateReferenceSystem, QgsHillshadeRenderer, QgsMapRendererParallelJob,  # noqa: E402
                       QgsMapSettings, QgsRasterLayer, QgsRectangle)
from qgis.PyQt.QtCore import QRectF, QSize, Qt  # noqa: E402
from qgis.PyQt.QtGui import QColor, QPainter, QPen  # noqa: E402

from geoguessers_view import client  # noqa: E402

W, H = 1600, 900
DATA = os.environ.get("GEO_DATA", r"D:\geoguessers_data")


def render(layers, extent):
    ms = QgsMapSettings()
    ms.setLayers(layers)
    ms.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:32644"))
    ms.setOutputSize(QSize(W, H))
    ms.setExtent(extent)
    ms.setBackgroundColor(QColor("#16181d"))
    job = QgsMapRendererParallelJob(ms)
    job.start()
    job.waitForFinished()
    return job.renderedImage(), ms


CAPTIONS = {}


def caption(name, title, sub):
    """Captions are drawn later by bench/demo_video.py (Qt's offscreen platform has no fonts)."""
    CAPTIONS[name] = [title, sub]


def rubber_band(img, ms, rect):
    m2p = ms.mapToPixel()
    a = m2p.transform(rect.xMinimum(), rect.yMaximum())
    b = m2p.transform(rect.xMaximum(), rect.yMinimum())
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor("#ffd166"))
    pen.setWidth(3)
    pen.setStyle(Qt.DashLine)
    p.setPen(pen)
    p.setBrush(QColor(255, 209, 102, 40))
    p.drawRect(QRectF(a.x(), a.y(), b.x() - a.x(), b.y() - a.y()))
    p.end()


def main():
    server, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    info = client.get_info(server)
    ds = "chamoli_2m"
    dem = QgsRasterLayer(os.path.join(DATA, "prepared", f"{ds}.tif"), "Chamoli 2 m DEM", "gdal")
    dem.setRenderer(QgsHillshadeRenderer(dem.dataProvider(), 1, 315, 45))
    l, b, r, t = info["datasets"][ds]["bounds"]
    whole = QgsRectangle(l, b, r, t)
    whole.scale(1.08)
    cx, cy = l + 0.47 * (r - l), b + 0.55 * (t - b)
    box = QgsRectangle(cx - 2600, cy - 1460, cx + 2600, cy + 1460)

    img, ms = render([dem], whole)
    caption("q1.png", "The same server inside QGIS",
            "Chamoli 2 m DEM in QGIS; the GeoGuessers panel connects to the tile server on this laptop")
    img.save(os.path.join(out, "q1.png"))

    img, ms = render([dem], whole)
    rubber_band(img, ms, box)
    caption("q2.png", "Drag a box with the GeoGuessers tool",
            "The box is sent to the server (POST /view); the map can be in any CRS, the box is reprojected to UTM 44N")
    img.save(os.path.join(out, "q2.png"))

    body = client.view_body(ds, (box.xMinimum(), box.yMinimum(), box.xMaximum(), box.yMaximum()), W, "slope",
                            "Horn", "auto", full_resolution=True)
    status, data, headers = client.post_view(server, body)
    path = client.save_result(data, "slope", ds, headers, folder=out)
    slope = client.make_layer(path, "slope", ds, headers, "auto", info)
    zoom = QgsRectangle(box)
    zoom.scale(1.35)
    img, ms = render([slope, dem], zoom)
    rubber_band(img, ms, box)
    import json
    sw, sh = json.loads(headers.get("x-size", "[0, 0]"))
    size = f"{sw:,} x {sh:,}"
    caption("q3.png", "Slope at full resolution (2 m cells), added as a GeoTIFF layer",
            f"{size} cells for the box, styled with the server's colours; identical to gdaldem's slope of the DEM")
    img.save(os.path.join(out, "q3.png"))

    body = client.view_body(ds, (whole.xMinimum(), whole.yMinimum(), whole.xMaximum(), whole.yMaximum()), W,
                            "hillshade", "Horn", "auto", azimuth=135)
    status, data, headers = client.post_view(server, body)
    path = client.save_result(data, "hillshade", ds, headers, folder=out)
    hs = client.make_layer(path, "hillshade", ds, headers, "auto", info)
    img, ms = render([slope, hs], whole)
    caption("q4.png", f"A large box comes back from a coarse level: here level {headers.get('x-level', '?')} "
                 f"({float(headers.get('x-level-cell', 0)):.0f} m cells)",
            "Hillshade with the sun from the south-east for the whole area, next to the 2 m slope box")
    img.save(os.path.join(out, "q4.png"))
    import json
    with open(os.path.join(out, "captions.json"), "w", encoding="utf-8") as fh:
        json.dump(CAPTIONS, fh)
    print("frames written to", out)


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)
