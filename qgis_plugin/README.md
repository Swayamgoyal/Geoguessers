# GeoGuessers terrain: QGIS plugin

Drag a box on the QGIS map and the GeoGuessers tile server computes slope, aspect, hillshade, TRI, TPI or roughness
for that box. The result is added as a georeferenced GeoTIFF layer (UTM 44N) with the same colours as the web viewer.
The server picks the pyramid level whose cells match the box's size on screen, so a large box comes back quickly from
a coarse level, and a smaller box drawn inside it comes back at a finer level. You can also ask for full resolution.
The plugin uses the same server and caches as the web viewer (`POST /view`).

## Requirements

- QGIS 3.22 or newer (checked with QGIS 3.44 LTR on Windows). No extra Python packages: the plugin uses the standard
  library and QGIS itself.
- The tile server running on this machine, started from the repository root:

  ```
  conda activate geo
  python -m server            # http://127.0.0.1:8765
  ```

## Install

1. Copy the plugin into your QGIS profile with the script (it keeps any earlier copy as `geoguessers_view.previous_*`):

   ```
   powershell -ExecutionPolicy Bypass -File qgis_plugin\install.ps1
   ```

   Or copy the `qgis_plugin\geoguessers_view` folder by hand to
   `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`.
2. Restart QGIS, open **Plugins → Manage and Install Plugins → Installed** and tick **GeoGuessers terrain**.
3. Click the toolbar button (mountain inside a dashed box) or use **Raster → GeoGuessers → GeoGuessers terrain**. A
   panel opens on the right.

## Use

1. **Server**: keep `http://127.0.0.1:8765` and press **Connect**. The datasets on the server are listed.
2. Choose the **Dataset**, the **Product**, the **Method** (Horn or Zevenbergen–Thorne; Riley or Wilson for TRI), and
   the **Sun direction** for hillshade.
3. **Values**:
   - *Auto*: computed on the chosen pyramid level. This is fast; the expected slope error for that level (from
     experiment E5) is shown in the status line and saved in the layer's metadata.
   - *Exact*: computed from full-resolution cells and then averaged to the level. This is slower and has no pyramid
     error.
   - *Precomputed*: the stored gdaldem slope pyramid (slope with the Horn method only).
4. **Cell size**: *Match the box on screen* (the default) or *Full resolution (level 0)*. A full-resolution box is
   limited to 64 M cells (about 16 km × 16 km on the 2 m dataset); for a larger box the server says so and adds no
   layer.
5. Press **Zoom to dataset** to see where the data is. Then press **Draw a box** and drag on the map. The box is
   computed in the background, so you can keep working, and the new layer appears when it is ready. The tool stays
   active, so you can draw the next box at once.

The map can use any CRS: the box is reprojected to the dataset's CRS (UTM 44N) before it is sent. Results are saved
as GeoTIFFs in `%TEMP%\geoguessers_qgis\`, named `<dataset>_<product>_L<level>_<n>.tif`. Save a layer elsewhere
(right-click → Export) if you want to keep it.

## Check (for developers)

With the server running, the headless check loads the plugin into QGIS, draws boxes and compares the result with the
DEM:

```
set QT_QPA_PLATFORM=offscreen
"C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat" qgis_plugin\check_plugin.py
```

It passes when:
- a full-resolution slope box is on the DEM's cell grid and equal to gdaldem's slope of the full-resolution DEM;
- a box drawn on a WGS 84 map is reprojected and gets the level rule's level;
- both datasets work;
- an oversized box and a box outside the data give messages instead of layers.

## Files

| File | What it does |
|---|---|
| `geoguessers_view/__init__.py` | QGIS entry point (`classFactory`) |
| `geoguessers_view/plugin.py` | Panel, map tool (`QgsMapToolExtent`), background task (`QgsTask`), adding the layer |
| `geoguessers_view/client.py` | Server calls (`GET /info`, `POST /view`), box reprojection, screen width, layer styling and metadata; no GUI code |
| `geoguessers_view/metadata.txt`, `icon.svg` | Plugin metadata and icon |
| `install.ps1` | Copies the plugin into a QGIS profile |
| `check_plugin.py` | Headless end-to-end check against a running server |
