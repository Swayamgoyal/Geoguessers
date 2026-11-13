# Experiment report: the viewer and the QGIS plugin on a 2.85-billion-cell DEM (Linux laptop)

Hand-driven test sessions of the Phase 5 system (tile server, web viewer, QGIS plugin) on 2026-11-12, with CPU, GPU,
iGPU, memory and disk sampled once a second. The goal was to check the final report's claims at a larger scale and
on a second machine, and to measure what E6 did not: client-side cost and long sessions where the caches fill up.

*Revised after runs 4 and 5. Run 2's tile figures now exclude its 43 Exact tiles (the first version mixed them in),
and the memory finding is restated: the overshoot comes from Exact overviews, not from GDAL's caches as first
guessed.*

## Summary

- **The system works as designed at about 11× E6's dataset size.** On `swiss_quarter_2m` (2.85 B cells, real lidar),
  web-viewer tiles in *Auto* mode took a median of 6.9–14.1 ms over three runs (p95 16.5–41.4 ms). 43 of the 44
  *Auto* QGIS boxes came back in 10–225 ms at the expected levels; the 44th was refused for exceeding the box size
  limit, as designed.
- **CPU only, as the report states.** The tile server never used the NVIDIA GPU. The AMD iGPU stayed at its lowest
  clock (800 MHz) and showed no load beyond ordinary desktop drawing.
- **The clients cost more CPU than the server** in normal use. The browser used a median of 0.2–0.5 cores against the
  server's 0.01–0.02, and QGIS peaked at 8.4 cores while redrawing layers, against the server's 0.27.
- ***Exact* mode is where it breaks down on a dataset this large**, in three ways:
  1. **Memory.** Without Exact work the server stayed within its ≈2.2 GB budget (peaks 1.9–2.3 GB). Exact overviews
     pushed it to **2.9 GB** with one running and **3.9 GB** with six running at once.
  2. **Stalls.** An Exact whole-map overview takes **47–129 s** on one core. During one, the viewer requested no tiles
     for about 36 s.
  3. **No cancellation.** Changing the sun direction in Exact mode started a new overview each time, and the old ones
     were never cancelled: eight ran to completion, six of them at once.

  An Exact box in QGIS (99 s for a 22 × 25 km box) is slow but stays within memory, and the server keeps answering
  other requests meanwhile.

## Setup

| | |
|---|---|
| Machine | AMD Ryzen 7 7840HS (8 cores / 16 threads, no efficiency cores), 14 GiB RAM, Samsung NVMe SSD (1 TB), NVIDIA RTX 4050 Laptop (6 GiB) + AMD Radeon 780M iGPU (drives the screen) |
| OS and software | CachyOS, Linux 7.3.3; GDAL 3.13.3; Python 3.14.9; numba 0.68.1, rasterio 1.5.2, FastAPI 0.162.4, uvicorn 0.54.0; QGIS 4.2.3 (Qt6); Brave 157 |
| Code | repository at `cf7a105` (plugin ported to QGIS 4 / Qt6; otherwise unchanged) |
| Server settings | defaults: 8 foreground and 3 background workers, 1024 MiB block cache, 512 MiB result cache, `GDAL_CACHEMAX` 128 MB. Core pinning is Windows-only (`demlab/cpus.py`) and was **not active** |
| Dataset | `swiss_quarter_2m`: swisstopo swissALTI3D at 2 m, LV95 (EPSG:2056), E 2555–2675 km × N 1075–1170 km (Valais and Bernese Oberland). 8,765 lidar tiles (surveys 2019–2025) merged into one COG: 60000 × 47500 = 2.85 B cells, 77% valid (the rest is outside Switzerland), 366–4634 m, ZSTD, 512 blocks, 7 overview levels, 5.6 GB. Built with the same COG settings as `datasets/prepare.py` |

For comparison, E6 used Chamoli 2 m (264 M cells) with hillshade on a 22-thread Intel laptop with an RTX 4060. That
is the machine all numbers in the final report come from.

**Instruments** (all under `logs/qgis_session/`):
- `requests.jsonl`: every HTTP request with start time, wall time, status, bytes, the `/view` body, and the response's
  `Server-Timing` and cache-tier headers.
- `stats.jsonl`: the server's own counters every 2 s (memory, cache bytes, hits and evictions, scheduler queues).
- `usage.jsonl`: one sample per second: CPU per logical core, memory, disk read and write, the tile server, QGIS and
  Brave (CPU, memory), the NVIDIA GPU (`nvidia-smi`), and the AMD iGPU (`gpu_busy_percent`, clock, VRAM, package
  power from sysfs).

## Sessions

| Run | Start | Length | What was done | Charts |
|---|---|---|---|---|
| 1, web viewer | 15:50:38 | 8.5 min | pan, zoom, box zoom; hillshade, slope, aspect, TPI, TRI; one switch to *Exact* | [overview](charts/run1_webview/overview.png), [tile stages](charts/run1_webview/tile_stages.png), [summary](charts/run1_webview/summary.md) |
| 2, web viewer | 18:12:32 | 3.0 min | same, mostly at levels 0–1; five products incl. roughness; one switch to *Exact* | [overview](charts/run_20261112_1842/overview.png), [tile stages](charts/run_20261112_1842/tile_stages.png), [summary](charts/run_20261112_1842/summary.md) |
| 3, QGIS plugin | 18:46:45 | 2.2 min | 21 boxes (the first is a hillshade backdrop drawn at start-up); all *Auto*, 3 at full resolution | [overview](charts/run_qgis_20261112/overview.png), [summary](charts/run_qgis_20261112/summary.md) |
| 4, web viewer | 22:03:58 | 7.3 min | mostly levels 0–1; hillshade, aspect, slope, roughness; two periods of *Exact*, dragging the sun direction during the first | [overview](charts/run4_webview/overview.png), [tile stages](charts/run4_webview/tile_stages.png), [summary](charts/run4_webview/summary.md) |
| 5, QGIS plugin | 22:23:46 | 6.0 min | 24 boxes (incl. the start-up backdrop) over 7 products; one *Exact* box | [overview](charts/run5_qgis/overview.png), [summary](charts/run5_qgis/summary.md) |

Conditions that affect the readings:
- **Run 1** did not sample the iGPU or the browser; both were added before run 2.
- **iGPU idle baseline** (Brave closed, 206 s just after run 1): median 21% busy, p95 26%, at 800 MHz, package power
  median 8.0 W.
- **Run 4:** an unrelated application that used the NVIDIA GPU was running in the background. It accounts for all the
  NVIDIA activity in that run (up to 92%, 959 MB) and took a median of 1.8 cores (other runs: 0.3–0.6). Whole-machine
  CPU and package power in run 4 are therefore not comparable with the other runs. The server's own numbers are
  measured per process and are unaffected.
- **Run 5:** a system monitor (Mission Center) was open on the iGPU page, which adds its own drawing to the iGPU
  figures.

## Results

### Web viewer: tiles

*Auto* tiles only. Exact tiles are listed separately because each one computes from full-resolution cells.

| | Run 1 | Run 2 | Run 4 |
|---|---|---|---|
| *Auto* tiles served | 4,789 | 2,315 | 4,014 |
| Share at levels 0–1 (finest) | 10% | 54% | 76% |
| From decoded blocks / disk / finished-tile cache | 77% / 18% / 5% | 55% / 45% / 0.2% | 75% / 25% / 0% |
| Tile time median / p95 / max | 6.9 / 16.5 / 77 ms | 14.1 / 41.4 / 188 ms | 8.1 / 19.9 / 264 ms |
| Mean tile time, blocks already decoded | 5.8 ms | 10.1 ms | 6.1 ms |
| Mean tile time, blocks read from disk | 14.1 ms | 21.7 ms | 16.2 ms |
| Decompression's share of a disk-read tile | 52% (7.4 ms) | 55% (11.9 ms) | 55% (9.0 ms) |
| Visible / prefetched tiles completed | 1,091 / 3,788 (1 : 3.5) | 548 / 1,846 (1 : 3.4) | 827 / 3,341 (1 : 4.0) |
| Aborted (499) / cancelled (409) | 16 / 10 | 14 / 5 | 68 / 4 |
| *Exact* tiles completed: n, median, max | 0 | 43, 201 ms, 330 ms | 94, 787 ms, 1.6 s |

What drives the differences:
- **Finest levels.** Run 2 was the slowest because most of its tiles came from the finest levels, so more blocks had
  to be decoded from disk. It also used the heavier roughness and TRI products.
- **Cache reuse in run 4.** Run 4 also spent most of its time at levels 0–1 but returned to areas it had already
  visited, so three quarters of its tiles found their blocks already decoded.
- **The finished-tile cache** rarely hit in any run: the product and sun direction changed often, and each
  combination has its own cache entries.

### Resources

| | Run 1 (viewer) | Run 2 (viewer) | Run 3 (QGIS) | Run 4 (viewer) | Run 5 (QGIS) |
|---|---|---|---|---|---|
| Whole machine, max cores busy (of 16) | 3.1 | 6.0 | 8.8 | 12.9 † | 4.3 |
| Tile server CPU, median / max (cores) | 0.01 / 1.3 | 0.02 / 4.1 | 0.01 / 0.27 | 1.58 / 7.3 | 0.01 / 1.0 |
| Client CPU, median / max (cores) | not sampled | Brave 0.47 / 1.72 | QGIS 0.12 / 8.4 | Brave 0.20 / 1.60 | QGIS 0.03 / 1.09 |
| Tile server memory, max | 2,248 MB | 2,903 MB | 432 MB | 3,924 MB | 733 MB |
| Client memory, max | not sampled | Brave 1,777 MB | QGIS 1,252 MB | Brave 1,785 MB | QGIS 807 MB |
| Block cache at end | 1,023 MB (cap 1,024), 492 evictions | 1,024 MB, 634 evictions | 91 MB | 1,023 MB, 501 evictions | 130 MB |
| Result cache at end | 512 MB (cap 512), 2,414 evictions | 479 MB | 0 | 512 MB, 1,821 evictions | 0 |
| Disk reads, max | 141 MB/s | 118 MB/s | 90 MB/s | 344 MB/s | 197 MB/s |
| NVIDIA GPU | 0% in 478 samples | 0% in 159 samples | 0% in 122 samples | 0% from the tile server † | 0% in 336 samples |
| AMD iGPU busy, median / p95 / max | not sampled | 14 / 26 / 29% | 5 / 20 / 33% | 11 / 26 / 44% | 8 / 33 / 52% ‡ |
| iGPU above its lowest clock (800 MHz) | — | 0% of samples | — | 0% | 1% |

† An unrelated background application used the NVIDIA GPU and about 1.8 cores during run 4 (see Sessions).
‡ A system monitor was drawing iGPU graphs during run 5.

In runs 2 and 4 the server's CPU median (0.02 vs 1.58 cores) differs because of Exact work: run 4 spent about 4.2 of
its 7.3 minutes computing Exact overviews and tiles.

### QGIS plugin

- **Auto boxes:** 43 of 44 succeeded across runs 3 and 5, over 7 products. The level followed the box size on screen:
  128 m for a dataset-wide box, then 64, 16, 8, 4 and 2 m as boxes shrank. Server time was 10–225 ms per box. The
  largest was a full-resolution aspect box of 1148 × 1103 cells (0.21 s, 4.4 MB GeoTIFF).
- **Rejected box:** a full-resolution box of 43 × 38 km (about 400 M cells) was refused in 1 ms with HTTP 400. The
  server's limit is 64 M cells (`MAX_BOX_CELLS`, about 16 × 16 km at 2 m), so this is the intended behaviour.
- **Exact box (run 5):** an aspect box of about 22 × 25 km at 32 m (696 × 779 cells) took **99 s** on one core. In
  Exact mode each of its 0.54 M output cells is computed from 256 cells at 2 m, about 139 M cells in all.
  - Server memory stayed at 733 MB.
  - Two Auto boxes drawn while it was running came back in 20–40 ms. QGIS stayed usable throughout, because the
    plugin computes each box in a background task.
- **Where the time goes:** in normal use each box's CPU spike belongs to QGIS (reading the GeoTIFF and redrawing all
  layers in parallel), not to the server.

## Findings that need action

### 1. Exact overviews push server memory past the ≈2.2 GB budget

The spec (`docs/FINAL_PLAN.md`, goal 6) and the final report (§ Interactive viewing) give the server a memory budget
of about 2.2 GB. E6 reports a peak of 982 MiB. Splitting each run's samples by whether Exact work was in progress:

| | Run 1 | Run 2 | Run 4 | Run 5 |
|---|---|---|---|---|
| Server memory max, **no** Exact work | 2,248 MB | 2,292 MB | 1,938 MB | 622 MB |
| … of which outside the two caches, max | 713 MB | 800 MB | 589 MB | 493 MB |
| Server memory max, **during** Exact work | 2,207 MB | **2,903 MB** | **3,924 MB** | 733 MB |
| … of which outside the two caches, max | 1,066 MB | 1,400 MB | 3,209 MB | 603 MB |
| Exact work running | 1 overview | 1 overview | up to 6 overviews at once, plus tiles | 1 box |

What the split shows:
- **Without Exact work, the server stays at the budget.** With both caches full (1.5 GB) it peaks at 1.9–2.3 GB,
  at or just over 2.2 GB in runs 1 and 2. That is above E6's 982 MiB only because E6's short traces never filled the
  caches, a case the report lists as a limitation.
- **Exact overviews are what exceed it.** Each one holds full-resolution arrays while computing: one overview took
  the server to 2.9 GB, and six at once took it to 3.9 GB.
- **Not every Exact request does.** Run 1's overview did not exceed the budget, because the caches were not yet full,
  and a single Exact box (run 5) stayed at 733 MB.
- **Memory returns when the work ends.** In run 4 it fell from about 3 GB to about 1 GB within seconds of the
  overviews finishing, so this is not a leak.

### 2. An Exact whole-map overview takes minutes and stalls the viewer

| | Run 1 | Run 2 | Run 4 |
|---|---|---|---|
| Request | TRI (Wilson), Exact | roughness, Exact | hillshade (Zevenbergen–Thorne), Exact, 8 sun directions |
| Time | 47.1 s | 50.7 s | 77–129 s each |
| Load | one core, disk 90–140 MB/s | one core, disk 50–120 MB/s | about 6 cores (one per overview), disk up to 344 MB/s |

The overview is the coarsest level (256 m) as one image. In *Exact* mode every cell of it is computed from the 2 m
cells, which means reading all 2.85 B cells on one thread. The run 4 overviews took longer than one alone because six
ran together and competed for disk and memory.

The final report says Exact tiles cost up to 2.9 s (E5, at 32 m) and are never prefetched, but it does not mention
the overview. The internal report says the overview is always loaded so the view is never blank. In run 1 the viewer
requested no tiles for about 36 s while the overview was computing, and normal requests resumed only after *Auto* was
selected again. The logs cannot show whether the screen itself went blank, because older tiles may have stayed
visible.

### 3. Superseded Exact overviews are not cancelled

In run 4, moving the sun-direction slider in Exact mode requested a new overview for each direction (azimuths 18°,
258°, 320°, 290°, 295°, then 51°, and later 166° and 252°). All eight ran to completion (HTTP 200), even though only
the latest direction was being shown. Five were running at the same time from about 1.5 min, and six from 2.2 to
3.5 min.

Tiles are cancelled as designed: all 16 Exact tiles that ran for more than 2 s were aborted by the browser (499), and
the session had 68 aborts in all. Overviews are not. They run outside the tile scheduler, so neither a new generation
nor a client abort stops them.

A browser opens at most six connections to one server, so six overviews in flight may also have held every
connection the viewer had, which would explain why almost no tiles were requested during that period. This is
plausible but not confirmed by these logs.

**Possible fixes for findings 1–3:**
- Always build the overview from its own level (*Auto*) whatever the mode.
- Or cancel a superseded overview, and cache overviews per product and sun direction.
- If Exact overviews are kept, render them in parallel.

## Comparison with the final report

| Report claim | Where | These runs | Verdict |
|---|---|---|---|
| On-demand computation keeps up with continuous pan and zoom | Conclusion; slides | *Auto* tile median 6.9–14.1 ms on 11× E6's cells; a full view in 91 ms on the 625 M-cell `swiss_alps_2m` block (E6: 76–158 ms) | Holds |
| The viewer runs on the CPU only | Limitations | The tile server never used the NVIDIA GPU | Holds |
| Decoding, not computing, is a tile's main cost | Recommendation 3 | Decompression is 52–55% of a disk-read tile | Holds |
| Byte-budgeted caches (1024 MiB blocks, 512 MiB tiles) | System table; internal report | Both stopped at their caps and evicted | Holds |
| Cancellation of stale requests | System table | Tiles: 499 and 409 responses, jobs cancelled mid-render, all slow Exact tiles aborted. Overviews: not cancelled | Holds for tiles; **not for overviews** |
| Prefetch fetches 2–5 tiles per tile used (precision 0.20–0.56) | E6 | 3.4–4.0 prefetched per visible tile (not the same metric) | Consistent |
| The QGIS plugin picks the level to match the box | System table | All 43 accepted *Auto* boxes at the expected level, 128 m → 2 m; the oversized box refused | Holds |
| Exact mode works without prefetch | Spec goal 7 | An Exact QGIS box: 99 s, within memory, server still responsive | Holds (slow on large boxes) |
| Server memory budget ≈2.2 GB; E6 peak 982 MiB | FINAL_PLAN goal 6; § Interactive viewing | 1.9–2.3 GB without Exact work; **2.9–3.9 GB** with Exact overviews | **Holds without Exact overviews; exceeded with them** |
| Exact tiles are never prefetched; the overview keeps the view from going blank | § Interactive viewing; internal report | Exact overviews take 47–129 s; no tile requests for about 36 s in run 1 | **Gap: not covered** |
| 5–8 ms per tile at every zoom level (E5) | E5; slides | 5.8–10.1 ms with decoded blocks, 14–22 ms reading from disk, under interactive load | Same order; not comparable (E5 timed one slope tile on an idle server, and its cold/warm is the OS file cache) |
| Foreground on performance cores, prefetch on efficiency cores | System table | Pinning is Windows-only; this CPU has no efficiency cores | Not tested |
| Debounce cuts tiles 3.3×; first exact tile 63–71 ms after the debounce; prefetch does not slow the foreground (gates 1 and 2) | E6 | Hand-driven sessions cannot measure these | Not tested |

**New relative to the reports:**
- **Client cost.** The reports measure the server and the latency the client sees, but not the client's own work. In
  normal (*Auto*) use the browser and QGIS use more CPU over a session than the server does.
- **Scale.** Interactive viewing works on a 2.85 B-cell real dataset; at this scale *Exact* overviews become the
  limiting case.

## Limitations of these runs

- **Hand-driven sessions.** Short (2–8.5 min), one run each, not repeatable traces. They show behaviour, not
  benchmark numbers; E6's `bench/vclient.py` traces are the reproducible test.
- **Different machine** from the report's: 16 AMD threads vs 22 Intel threads, 14 GiB vs 16 GB, and Linux without
  core pinning. Absolute times are not comparable to E6.
- **Background load.** Run 4 shared the machine with an unrelated application, and run 5 with a system monitor
  drawing on the iGPU (see Sessions).
- **Missing data.**
  - No iGPU or browser data for run 1.
  - Only one Exact box in QGIS.
  - No correctness check of plugin output against `gdaldem` in these runs.
- **Sampling.**
  - iGPU busy % is the whole GPU, including desktop compositing, so the viewer's share can only be read against the
    idle baseline.
  - Package power covers the CPU and the iGPU together.
  - Memory is sampled once a second, so short peaks may be missed.
- **Connection limit.** The link between the six-connection browser limit and the tile pause in run 4 is a
  hypothesis.

## Reproduce

The tools live outside the repository in `~/.local/share/geoguessers-tools/`:
- `test_session.sh`
- `run_server_logged.py`
- `usage_sampler.py`
- `session_charts.py`
- `swissalti3d_fetch.py`
- `qgis_open.py`

The data is in `SI/Datasets/Geoguessers/{raw,prepared}`.

```
# dataset (once): 8,765 tiles from swisstopo's STAC API, then one COG
python ~/.local/share/geoguessers-tools/swissalti3d_fetch.py 2 <raw dir> 2555 2675 1075 1170
gdalbuildvrt … && gdal_translate -of COG -co BLOCKSIZE=512 -co COMPRESS=ZSTD -co PREDICTOR=FLOATING_POINT \
  -co LEVEL=9 -co OVERVIEW_RESAMPLING=AVERAGE -co OVERVIEWS=IGNORE_EXISTING -co BIGTIFF=YES … swiss_quarter_2m.tif

# a session
~/.local/share/geoguessers-tools/test_session.sh start     # server + sampler + web viewer
qgis --code ~/.local/share/geoguessers-tools/qgis_open.py  # optional: QGIS with the plugin connected
~/.local/share/geoguessers-tools/test_session.sh stop
~/.local/share/geoguessers-tools/test_session.sh charts <name>
```

Data attribution: swissALTI3D © swisstopo.
