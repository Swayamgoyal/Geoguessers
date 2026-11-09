"""QGIS side: a dock with the server and product settings, and a map tool. Drag a box on the canvas and the box is
computed by the server in the background (QgsTask) and added as a layer, so several boxes can be drawn one after
another (nested boxes = zooming in with ever finer pyramid levels)."""

import os

from qgis.core import Qgis, QgsApplication, QgsMessageLog, QgsProject, QgsSettings, QgsTask
from qgis.gui import QgsMapToolExtent
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (QAction, QComboBox, QDockWidget, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                                 QPushButton, QSpinBox, QVBoxLayout, QWidget)

from . import client

TITLE = "GeoGuessers terrain"
SETTINGS = "geoguessers/"


def log(msg, level=Qgis.Info):
    QgsMessageLog.logMessage(msg, "GeoGuessers", level)


class ViewTask(QgsTask):
    """POST /view in a background thread; the layer is added in finished(), on the main thread."""

    def __init__(self, server, body, mode, on_done):
        super().__init__(f"GeoGuessers: {client.LABELS.get(body['op'], body['op'])} for a box", QgsTask.CanCancel)
        self.server, self.body, self.mode, self.on_done = server, body, mode, on_done
        self.path = self.headers = self.error = None

    def run(self):
        try:
            status, data, headers = client.post_view(self.server, self.body)
            if status == 204:
                self.error = "the box does not overlap the dataset"
                return False
            if self.isCanceled():
                return False
            self.headers = headers
            self.path = client.save_result(data, self.body["op"], self.body["dataset"], headers)
            return True
        except client.ServerError as e:
            self.error = str(e)
            return False

    def finished(self, ok):
        self.on_done(self, ok)


class Panel(QWidget):
    def __init__(self):
        super().__init__()
        form = QFormLayout()
        self.server = QLineEdit(QgsSettings().value(SETTINGS + "server", client.DEFAULT_SERVER))
        self.connect = QPushButton("Connect")
        row = QHBoxLayout()
        row.addWidget(self.server, 1)
        row.addWidget(self.connect)
        form.addRow("Server", row)
        self.dataset, self.op, self.method, self.mode, self.res = (QComboBox() for _ in range(5))
        self.mode.addItem("Auto (pyramid level)", "auto")
        self.mode.addItem("Exact (from full resolution)", "exact")
        self.mode.addItem("Precomputed (slope, Horn)", "precomputed")
        self.res.addItem("Match the box on screen", False)
        self.res.addItem("Full resolution (level 0)", True)
        self.azimuth = QSpinBox()
        self.azimuth.setRange(0, 359)
        self.azimuth.setValue(315)
        self.azimuth.setSuffix("°")
        form.addRow("Dataset", self.dataset)
        form.addRow("Product", self.op)
        form.addRow("Method", self.method)
        form.addRow("Values", self.mode)
        form.addRow("Cell size", self.res)
        form.addRow("Sun direction", self.azimuth)
        self.draw = QPushButton("Draw a box")
        self.draw.setCheckable(True)
        self.zoom = QPushButton("Zoom to dataset")
        buttons = QHBoxLayout()
        buttons.addWidget(self.draw)
        buttons.addWidget(self.zoom)
        self.status = QLabel("Not connected. Start the server with: python -m server")
        self.status.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addLayout(buttons)
        lay.addWidget(self.status)
        lay.addStretch(1)


class GeoguessersPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.info = None
        self.tasks = []       # keep Python references until the tasks finish
        self.action = self.dock = self.panel = self.tool = None

    # ---- QGIS plugin interface -------------------------------------------------------------------------------
    def initGui(self):  # noqa: N802
        icon = QIcon(os.path.join(os.path.dirname(__file__), "icon.svg"))
        self.action = QAction(icon, TITLE, self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.toggled.connect(self.show_dock)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToRasterMenu("&GeoGuessers", self.action)

        self.panel = Panel()
        self.dock = QDockWidget(TITLE, self.iface.mainWindow())
        self.dock.setObjectName("GeoguessersDock")
        self.dock.setWidget(self.panel)
        self.dock.visibilityChanged.connect(self.action.setChecked)
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        self.dock.hide()

        canvas = self.iface.mapCanvas()
        self.tool = QgsMapToolExtent(canvas)
        self.tool.extentChanged.connect(self.box_drawn)
        canvas.mapToolSet.connect(self.tool_changed)

        p = self.panel
        p.connect.clicked.connect(self.connect_server)
        p.draw.toggled.connect(self.toggle_tool)
        p.zoom.clicked.connect(self.zoom_to_dataset)
        p.dataset.currentIndexChanged.connect(self.sync)
        p.op.currentIndexChanged.connect(self.sync)
        p.method.currentIndexChanged.connect(self.sync_mode)

    def unload(self):
        canvas = self.iface.mapCanvas()
        try:
            canvas.mapToolSet.disconnect(self.tool_changed)
        except TypeError:
            pass
        if canvas.mapTool() is self.tool:
            canvas.unsetMapTool(self.tool)
        self.iface.removeToolBarIcon(self.action)
        self.iface.removePluginRasterMenu("&GeoGuessers", self.action)
        self.iface.removeDockWidget(self.dock)
        self.dock.deleteLater()
        self.tool = None

    # ---- UI --------------------------------------------------------------------------------------------------
    def show_dock(self, on):
        self.dock.setVisible(on)
        if on and self.info is None:
            self.connect_server()

    def connect_server(self):
        p = self.panel
        server = p.server.text().strip() or client.DEFAULT_SERVER
        try:
            self.info = client.get_info(server)
        except client.ServerError as e:
            self.info = None
            p.status.setText(str(e))
            return False
        QgsSettings().setValue(SETTINGS + "server", server)
        for combo in (p.dataset, p.op):
            combo.blockSignals(True)
            combo.clear()
        for name in self.info["datasets"]:
            p.dataset.addItem(name.replace("_", " "), name)
        for op in self.info["ops"]:
            p.op.addItem(client.LABELS.get(op, op), op)
        p.op.setCurrentIndex(max(p.op.findData("slope"), 0))
        for combo in (p.dataset, p.op):
            combo.blockSignals(False)
        self.sync()
        p.status.setText(f"Connected to {server}: {len(self.info['datasets'])} datasets. Press “Draw a box” and drag "
                         "on the map.")
        return True

    def sync(self):
        p = self.panel
        op = p.op.currentData()
        methods = client.METHODS.get(op, [])
        current = p.method.currentData()
        p.method.blockSignals(True)
        p.method.clear()
        for m in methods:
            p.method.addItem("Zevenbergen–Thorne" if m == "ZevenbergenThorne" else m, m)
        if current in methods:
            p.method.setCurrentIndex(methods.index(current))
        p.method.blockSignals(False)
        p.method.setEnabled(bool(methods))
        p.azimuth.setEnabled(op == "hillshade")
        self.sync_mode()

    def sync_mode(self):
        p = self.panel
        ds = p.dataset.currentData()
        ok = bool(self.info and ds and self.info["datasets"][ds].get("precomputed")
                  and p.op.currentData() == "slope" and p.method.currentData() == "Horn")
        item = p.mode.model().item(2)
        item.setEnabled(ok)
        if not ok and p.mode.currentData() == "precomputed":
            p.mode.setCurrentIndex(0)

    def toggle_tool(self, on):
        canvas = self.iface.mapCanvas()
        if on:
            if self.info is None and not self.connect_server():
                self.panel.draw.setChecked(False)
                return
            canvas.setMapTool(self.tool)
        elif canvas.mapTool() is self.tool:
            canvas.unsetMapTool(self.tool)

    def tool_changed(self, new, old=None):
        self.panel.draw.blockSignals(True)
        self.panel.draw.setChecked(new is self.tool)
        self.panel.draw.blockSignals(False)

    def zoom_to_dataset(self):
        if self.info is None and not self.connect_server():
            return
        from qgis.core import QgsCoordinateTransform
        ds = self.panel.dataset.currentData()
        canvas = self.iface.mapCanvas()
        rect = client.dataset_extent(self.info, ds)
        src, dst = client.dataset_crs(self.info, ds), canvas.mapSettings().destinationCrs()
        if src != dst:
            rect = QgsCoordinateTransform(src, dst, QgsProject.instance()).transformBoundingBox(rect)
        canvas.setExtent(rect)
        canvas.refresh()

    # ---- a box was drawn -------------------------------------------------------------------------------------
    def request_for(self, rect, canvas_crs, map_units_per_pixel):
        """(server, body, mode) for a box drawn on the canvas, or None if it is degenerate."""
        if rect.isEmpty() or rect.width() <= 0 or rect.height() <= 0:
            return None
        p = self.panel
        ds = p.dataset.currentData()
        bbox = client.box_in_crs(rect, canvas_crs, client.dataset_crs(self.info, ds))
        mode = p.mode.currentData()
        body = client.view_body(ds, bbox, client.screen_width(rect, map_units_per_pixel), p.op.currentData(),
                                p.method.currentData() or "", mode, p.azimuth.value(), p.res.currentData())
        return p.server.text().strip() or client.DEFAULT_SERVER, body, mode

    def box_drawn(self, rect):
        canvas = self.iface.mapCanvas()
        req = self.request_for(rect, canvas.mapSettings().destinationCrs(), canvas.mapUnitsPerPixel())
        self.tool.clearRubberBand()
        if req is None:
            return
        self.start(*req)

    def start(self, server, body, mode):
        task = ViewTask(server, body, mode, self.task_done)
        self.tasks.append(task)
        self.panel.status.setText(f"Computing {client.LABELS.get(body['op'], body['op'])} for the box…")
        QgsApplication.taskManager().addTask(task)
        return task

    def task_done(self, task, ok):
        if task in self.tasks:
            self.tasks.remove(task)
        if not ok:
            msg = task.error or "cancelled"
            self.panel.status.setText(f"Failed: {msg}")
            self.iface.messageBar().pushMessage("GeoGuessers", msg, Qgis.Warning, 8)
            log(msg, Qgis.Warning)
            return None
        try:
            layer = client.make_layer(task.path, task.body["op"], task.body["dataset"], task.headers, task.mode,
                                      self.info or {})
        except client.ServerError as e:
            self.panel.status.setText(f"Failed: {e}")
            return None
        QgsProject.instance().addMapLayer(layer)
        h = task.headers
        ee = h.get("x-expected-error")
        extra = "" if ee is None else (" · full resolution" if float(ee) == 0 else f" · expected slope error ≈ "
                                                                                     f"{float(ee):.1f}° RMSE")
        self.panel.status.setText(f"Added “{layer.name()}”: {h.get('x-size', '')} cells{extra}.\nSaved to "
                                  f"{task.path}")
        log(f"added {task.path}")
        return layer
