"""Talking to the GeoGuessers tile server and turning its answer into a styled QGIS layer.

Only the standard library and qgis.core are used here (no GUI), so this part can be tested headless:
    get_info(server)                          -> datasets, ops, modes, colour maps (GET /info)
    view_body(...), post_view(server, body)   -> GeoTIFF bytes + headers (POST /view, format "tif")
    make_layer(path, ...)                     -> QgsRasterLayer with the server's colour map and level details
"""

import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from qgis.core import (QgsColorRampShader, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject,
                       QgsRasterLayer, QgsRasterShader, QgsRectangle, QgsSingleBandPseudoColorRenderer)
from qgis.PyQt.QtGui import QColor

DEFAULT_SERVER = "http://127.0.0.1:8765"
MAX_WIDTH = 4096      # widest image requested in "match screen" mode (the box's width on screen, capped)
MIN_WIDTH = 64
METHODS = {"slope": ["Horn", "ZevenbergenThorne"], "aspect": ["Horn", "ZevenbergenThorne"],
           "hillshade": ["Horn", "ZevenbergenThorne"], "TRI": ["Riley", "Wilson"], "TPI": [], "roughness": []}
LABELS = {"slope": "Slope", "aspect": "Aspect", "hillshade": "Hillshade", "TRI": "Ruggedness (TRI)",
          "TPI": "Topographic position (TPI)", "roughness": "Roughness"}
UNITS = {"slope": "degrees", "aspect": "degrees from north", "hillshade": "brightness 1-255", "TRI": "m",
         "TPI": "m", "roughness": "m"}


class ServerError(Exception):
    """The server could not be reached or refused the request; the message is meant for the user."""


def _opener(server):
    host = urllib.parse.urlparse(server).hostname or ""
    if host in ("127.0.0.1", "localhost", "::1"):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))   # never send local traffic to a proxy
    return urllib.request.build_opener()


def get_info(server, timeout=5):
    try:
        with _opener(server).open(server.rstrip("/") + "/info", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ServerError(f"cannot reach the GeoGuessers server at {server} ({e}). Start it with: python -m server")


def view_body(dataset, bbox, width, op, method="", mode="auto", azimuth=None, full_resolution=False):
    """JSON body for POST /view. `bbox` is (xmin, ymin, xmax, ymax) in the dataset's CRS. In "match screen" mode the
    server picks the pyramid level whose cells fit `width` pixels across the box; full_resolution asks for level 0."""
    body = {"dataset": dataset, "bbox": [float(v) for v in bbox], "width": int(width), "op": op, "mode": mode,
            "format": "tif"}
    if method:
        body["method"] = method
    if op == "hillshade" and azimuth is not None:
        body["azimuth"] = float(azimuth)
    if full_resolution:
        body["level"] = 0
    return body


def post_view(server, body, timeout=300):
    """-> (status, data, headers) with lower-case header names. 204 = the box misses the dataset."""
    req = urllib.request.Request(server.rstrip("/") + "/view", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with _opener(server).open(req, timeout=timeout) as r:
            return r.status, r.read(), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail", "")
        except (ValueError, OSError):
            detail = ""
        raise ServerError(f"the server refused the box (HTTP {e.code}): {detail or e.reason}")
    except (urllib.error.URLError, OSError) as e:
        raise ServerError(f"cannot reach the GeoGuessers server at {server} ({e})")


def box_in_crs(rect, src_crs, dst_crs):
    """A canvas rectangle as (xmin, ymin, xmax, ymax) in the dataset CRS (the bounding box of the reprojected box)."""
    if src_crs != dst_crs:
        rect = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance()).transformBoundingBox(rect)
    return rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum()


def screen_width(rect, map_units_per_pixel):
    """The box's width on screen in pixels (what "match screen" asks the server to fill), clamped."""
    px = rect.width() / map_units_per_pixel if map_units_per_pixel > 0 else MAX_WIDTH
    return int(min(max(round(px), MIN_WIDTH), MAX_WIDTH))


def output_folder():
    folder = os.path.join(tempfile.gettempdir(), "geoguessers_qgis")
    os.makedirs(folder, exist_ok=True)
    return folder


def save_result(data, op, dataset, headers, folder=None):
    folder = folder or output_folder()
    level = headers.get("x-level", "x")
    n = 1
    while True:
        path = os.path.join(folder, f"{dataset}_{op}_L{level}_{n:03d}.tif")
        if not os.path.exists(path):
            break
        n += 1
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def layer_name(op, dataset, headers, mode):
    cell = float(headers.get("x-level-cell", "nan"))
    cell_txt = f"{cell:.1f} m" if cell < 10 else f"{cell:.0f} m"
    tag = {"exact": ", exact", "precomputed": ", precomputed"}.get(mode, "")
    return f"{LABELS.get(op, op)} · {dataset.replace('_', ' ')} · level {headers.get('x-level', '?')} ({cell_txt}{tag})"


def describe(op, dataset, headers, mode):
    lines = [f"{LABELS.get(op, op)} ({UNITS.get(op, '')}) computed by the GeoGuessers server for {dataset}.",
             f"Pyramid level {headers.get('x-level', '?')}, cell size {headers.get('x-level-cell', '?')} m, "
             f"mode {mode}."]
    ee = headers.get("x-expected-error")
    if ee is not None:
        lines.append("Full resolution: no pyramid error." if float(ee) == 0 else
                     f"Expected slope error from the coarse level (experiment E5): about {float(ee):.1f}° RMSE.")
    return "\n".join(lines)


def style_layer(layer, op, info):
    """The server's colour map for `op` as an interpolated pseudocolour ramp (same colours as the web viewer)."""
    stops = info.get("legends", {}).get(op)
    if not stops:
        return
    items = [QgsColorRampShader.ColorRampItem(float(v), QColor(c), f"{v:g}") for v, c in stops]
    ramp = QgsColorRampShader(float(stops[0][0]), float(stops[-1][0]))
    ramp.setColorRampType(QgsColorRampShader.Interpolated)
    ramp.setColorRampItemList(items)
    ramp.setClip(False)
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(ramp)
    renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
    renderer.setClassificationMin(float(stops[0][0]))
    renderer.setClassificationMax(float(stops[-1][0]))
    layer.setRenderer(renderer)


def make_layer(path, op, dataset, headers, mode, info):
    layer = QgsRasterLayer(path, layer_name(op, dataset, headers, mode), "gdal")
    if not layer.isValid():
        raise ServerError(f"QGIS could not open the result {path}")
    crs = headers.get("x-crs")
    if crs and not layer.crs().isValid():
        layer.setCrs(QgsCoordinateReferenceSystem(crs))
    style_layer(layer, op, info)
    md = layer.metadata()
    md.setAbstract(describe(op, dataset, headers, mode))
    layer.setMetadata(md)
    return layer


def dataset_crs(info, dataset):
    return QgsCoordinateReferenceSystem(info["datasets"][dataset]["crs"])


def dataset_extent(info, dataset):
    l, b, r, t = info["datasets"][dataset]["bounds"]
    return QgsRectangle(l, b, r, t)
