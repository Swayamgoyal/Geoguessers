# Demo video

`geoguessers_demo.mp4` (about 58 s, 1600 × 900, silent, with captions) is the fallback for the live demo. Narration
can be added over it.

| Time | Scene |
|---|---|
| 0:00 | Whole Chamoli 2 m DEM as hillshade, from a coarse pyramid level |
| 0:05 | Wheel zoom of three levels: cached coarser tiles stand in, then one commit 150 ms after the last tick |
| 0:12 | Pan: the neighbouring views were prefetched, so new tiles are already there |
| 0:18 | Product switch to slope, then aspect (computed on demand) |
| 0:25 | Hillshade with the sun moving from 315° to 135° |
| 0:31 | Shift + drag box zoom down to full resolution (2 m cells); the status panel shows level, cell size, expected error |
| 0:40 | Back to the whole map; E6 headline numbers |
| 0:40 | QGIS plugin: the same server inside QGIS; dragging a box; the full-resolution slope layer; a large box from a coarse level |

The browser part is a real headless Chrome session of the web viewer, driven by scripted viewer actions and captured
with the Chrome DevTools screencast. The QGIS part is QGIS's own map renderer (offscreen) drawing the layers the
plugin's client code gets from the server (`POST /view`). The stills are kept as `qgis_q1.png` to `qgis_q4.png`.

Regenerate (about 2 minutes; starts its own server on port 8766):

```
conda activate geo
python -m bench.demo_video
```

Scripts: `bench/demo_video.py` (browser recording, captions, ffmpeg) and `bench/demo_qgis.py` (QGIS frames, run with
QGIS's Python).
