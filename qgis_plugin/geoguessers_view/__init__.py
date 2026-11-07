"""GeoGuessers terrain: QGIS plugin that computes terrain derivatives for a dragged box on the GeoGuessers server."""


def classFactory(iface):  # noqa: N802 (QGIS plugin entry point)
    from .plugin import GeoguessersPlugin
    return GeoguessersPlugin(iface)
