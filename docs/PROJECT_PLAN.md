# GeoGuessers: Project Plan

**Large-scale DEM processing and visualisation on a laptop**
Spatial Informatics · Team: Swayam Goyal (SG), Siddharth Choudhary (SC), Kartikeya (KK)
Duration: **3 weeks** (Week 1–3), ending at the course submission deadline

---

## 1. Goal

After the meeting with the professor (`project_mom.md`), the project is more than benchmarking slope/aspect algorithms. The goal is:

> Given a very large, high-resolution DEM and a laptop, process and display **only what is currently in view**, using a pyramid (multi-resolution) representation, **on-demand computation** of terrain derivatives, and CPU/GPU processing chosen by the **measured** bottleneck. Along the way, report where standard GDAL/QGIS tools stop being practical.

Our literature review gives us three gaps to answer:

| Gap | Statement | Answered by |
|---|---|---|
| **G1** | No study reports where standard GDAL/QGIS terrain tools stop being practical on a single laptop, broken down by stage (disk read, compute, CPU↔GPU transfer, write, render). | E1–E4, E6 |
| **G2** | No study computes derivatives on demand from pyramid levels or measures **coarse-level slope error against the time it saves**. | **E5 (headline result)** |
| G3 (stretch) | Accuracy loss of XDraw vs exact R3 viewshed in high-relief terrain; A* vs Dijkstra for terrain distance. | E7, E8 |

---

## 2. Benchmark machine

All reported numbers come from one machine so they are comparable. (The lit-review pilot ran on a different laptop: 24 GB, RTX 3050. It will be re-run here.)

| Component | Spec |
|---|---|
| CPU | Intel Core Ultra 9 185H (16 cores / 22 threads) |
| RAM | **16 GB** |
| GPU | NVIDIA RTX 4060 Laptop, **8 GB VRAM** (plus Intel Arc iGPU, unused) |
| Disk | NVMe SSD; data stored on **D:** (~195 GB free) |
| OS | Windows 11 |

**Why this matters.** For our 100 km × 100 km study area (HMA tile-571) in float32:

| Resolution | Cells | Size in memory | Fits in 16 GB? |
|---|---|---|---|
| 90 m | ~1.2 M | 5 MB | yes |
| 30 m | ~11 M | 44 MB | yes |
| **8 m (real)** | **156 M** | **0.6 GB** | yes |
| 4 m | 625 M | 2.5 GB | yes |
| 2 m | 2.5 B | 10 GB | borderline (input + output do not both fit) |
| **1 m** | **10 B** | **40 GB** | **no, out-of-core processing required** |

The point where whole-array processing fails (between 2 m and 1 m) is exactly what we want to measure and then get past.

---

## 3. Datasets

### 3.1 Design: one area, many resolutions

All benchmarking uses **one study area at several resolutions**. Run time depends on the number of cells, not on which mountain is being processed, so changing the area would only add a second variable. Keeping the area fixed means resolution is the only thing that changes.

**Study area: HMA tile-571, Uttarakhand / Nanda Devi.** 79.125–80.235°E, 30.033–30.970°N (~100 × 100 km). Elevation 674–7,790 m. It is in the same region as the lit-review pilot (N30 E79).

### 3.2 Resolution ladder (all for tile-571)

| Res | File | Source | Real / generated | Cells | Role |
|---|---|---|---|---|---|
| 90 m | `datasets/cop90_tile571.tif` | Copernicus GLO-90, OpenTopography API | **Real** (have it) | 1.6 M | Coarsest level; secondary accuracy check |
| 30 m | `datasets/cop30_tile571.tif` | Copernicus GLO-30, OpenTopography API | **Real** (have it) | 14.7 M | Baseline level; secondary accuracy check |
| **8 m** | `datasets/HMA_DEM8m_MOS_20170716_tile-571.tif` | NSIDC `HMA_DEM8m_MOS`, NASA Earthdata | **Real** (have it) | 156 M | 8 m level; "truth" for accuracy over the full tile |
| 2 or 1 m (only if needed) | `D:\geoguessers_data\synthetic\` | Upsampled from the 8 m tile with `gdalwarp -r cubic` | Generated | 2.5 B / 10 B | **Timing only**: made in Phase 2 only if needed to reach the 16 GB RAM limit |

**Real high-resolution sub-area: Chamoli / Rishiganga** (79.48–79.81°E, 30.29–30.59°N, ~32 × 33 km, inside tile-571):

| Res | File | Source | Real / generated | Cells | Role |
|---|---|---|---|---|---|
| **2 m** | `datasets/Chamoli_Sept2015_Composite_DEM2m_wmean.tif` | Chamoli pre-event 2 m DEM composite, Sept 2015 ([Zenodo 4554647](https://zenodo.org/records/4554647); NSIDC `HMA2_CPRE`), CC-BY-NC-4.0 | **Real** (have it, 810 MB) | 270 M | **Finest real level; accuracy truth for E5** |
Intermediate levels (4, 16, 32 … m) are **not separate datasets**. They are the pyramid levels (overviews) inside each COG. Downsampling real fine data keeps real terrain; upsampling (8 m → 1 m) adds cells but no information (see §3.6).

**No free 1 m DEM exists for this area.** India has no public lidar. Bhuvan CartoDEM is free only at 30 m (the 10 m version is restricted), and commercial 0.5–5 m products (AW3D Enhanced, WorldDEM Neo) are paid. So 1 m stays synthetic and is used for timing only.

All real data is listed in `datasets/manifest.csv`. The Copernicus files are re-created with `python datasets/download_cop.py` (needs `OPENTOPO_API_KEY` set in the environment; the key is never committed).

### 3.3 Unused files

Early downloads that are not part of this design (the Everest 90 m crop with its OpenTopography reference outputs, and the single 8 m HMA strips) are kept in the local `old files/` folder (gitignored; its README describes each file). Project rule: nothing is deleted; old scripts, files and logs move to `old files/`, and only large (> 1 GB) files produced by runs are moved to the external drive (`K:\spatial project\`). Correctness references for our kernels are now generated with `gdaldem` directly on the study-area data.

### 3.4 Data checks done

- **Coverage:** tile-571 is 90.4% valid. Most of the tile is 85–99% valid; gaps are concentrated in the south-east corner (that corner's blocks are only 23–80% valid). The Copernicus 30/90 m files cover the whole tile with no gaps.
- **Vertical datum:** the 8 m minus Copernicus 30 m difference has median **−24.5 m** (std 21.8 m). This is consistent with HMA heights being relative to the WGS84 ellipsoid and Copernicus to the EGM2008 geoid. A near-constant offset does not affect slope, aspect, hillshade, TRI or roughness. It **does** matter for viewshed (E7) and absolute-height comparisons, so apply a geoid correction (`gdalwarp` with an EGM2008 vertical CRS) before those.
- **Projection:** the 8 m tile uses a custom Albers equal-area projection and Copernicus is in degrees. Everything is reprojected to **UTM 44N (EPSG:32644)** before computing derivatives.

### 3.5 Rules

1. **Timing** experiments use the tile-571 ladder (90 / 30 / 8 m real, 4 / 2 / 1 m synthetic).
2. **Accuracy** experiments use real data only. On the Chamoli sub-area the truth is the real 2 m DEM, and coarser levels (4, 8, 16 … m) are built from it (same source). On the full tile the truth is the 8 m DEM. Copernicus 30/90 m and HMA 8 m are secondary comparisons, since they come from different sensors and dates.
3. Synthetic grids are made with **cubic** upsampling, never nearest-neighbour (see §3.6).
4. Every file is listed in `datasets/manifest.csv`. Rasters are gitignored. Large generated grids live in `D:\geoguessers_data\` (C: has only ~60 GB free).

### 3.6 How reliable is synthetic (upsampled) data? (measured)

Test: a 4000 × 4000 crop (16 M cells) of the real 8 m tile, compared with an 8 m grid rebuilt from a 16 m version of itself.

| Version | gdaldem slope time | LZW file size | Slope RMSE vs real | Cells off by > 5° |
|---|---|---|---|---|
| Real 8 m | 0.90 s | 56.2 MB | – | – |
| Synthetic, nearest | 0.89 s | **41.8 MB (−26%)** | 3.04° | 8.3% |
| Synthetic, bilinear | 0.87 s | 57.3 MB | 2.78° | 7.1% |
| Synthetic, cubic | 0.88 s | 57.3 MB | 2.32° | 4.5% |

- **Compute timing: reliable.** Run time is the same within noise (0.87–0.90 s). gdaldem does the same work per cell whatever the values are.
- **Disk / IO timing: reliable only with bilinear or cubic.** Nearest-neighbour data compresses 26% better than real terrain, which would make reads look faster than they are. The lit-review pilot used nearest; our runs will use cubic.
- **Accuracy: not reliable.** Even a single 2× upsample gives a slope error of 2.3–3.0° RMSE. 8 m → 1 m (8×) adds no real detail at all. Synthetic grids are never used for accuracy results.

---

## 4. System architecture

We **do not modify GDAL's C++ internals**. We build our own small engine (`demlab`) and plug it into the existing ecosystem, as the meeting suggested: integrate with GDAL/QGIS rather than recreate a GIS.

```
 DEM (GeoTIFF)
   │ gdal_translate / gdaladdo
   ▼
 Cloud-Optimized GeoTIFF (tiled 512, ZSTD) + internal overviews  ← the pyramid
   │ windowed reads via GDAL / rasterio (only the tiles in view)
   ▼
 demlab engine
   • tile + 1-pixel halo (so 3×3 kernels are exact at tile edges)
   • cell size = base_res × 2^level (slope must use the level's true cell size)
   • kernels: NumPy (naive) │ Numba parallel CPU │ CuPy / Numba-CUDA GPU
   • ops: slope (Horn, ZT), aspect, hillshade, TRI, TPI, roughness, (curvature)
   • LRU tile cache
   │
   ▼
 FastAPI tile server   /tiles/{op}/{z}/{x}/{y}.png   /heightmap/{z}/{x}/{y}
   │                                   │
   ▼                                   ▼
 QGIS (XYZ tile layer)        CesiumJS globe
                              (UrlTemplateImageryProvider for the overlay,
                               CustomHeightmapTerrainProvider for elevation)
```

**Flow for one request:** user zooms → zoom level selects the pyramid level → read only that window (+halo) from the COG → compute the op on CPU or GPU → colour-map → PNG → cache.

**GDAL integration options** (a is required; b and c are stretch):
- (a) The engine reads and writes through GDAL/rasterio, so it works on any GDAL-readable DEM.
- (b) GDAL VRT **Python pixel function**: a `.vrt` whose "slope" band is computed on read, so `gdalinfo`, `gdal_translate` and QGIS all see an on-the-fly slope layer.
- (c) A QGIS Processing provider that wraps `demlab`.

**Projection note:** compute derivatives in UTM (true metres), then warp the result tile to Web Mercator for display. Do not compute slope directly on Mercator pixels without a latitude scale correction.

---

## 5. Experiments

| ID | Question | Variables | Measured outputs | Gap |
|---|---|---|---|---|
| **E1** Baseline scaling | Where do `gdaldem` and the QGIS tools break on this laptop? | op × resolution (30 → 1 m) × cold/warm cache | time per stage, peak RSS **of the gdaldem process**, CPU %, disk MB/s, failure point | G1 |
| **E2** Storage / IO | Does file layout matter more than the algorithm? | striped GTiff vs tiled COG; none / LZW / DEFLATE / ZSTD; block 256 / 512 | read time, file size, total time | G1 |
| **E3** CPU engine | How much do tiling and parallelism help? | naive NumPy vs Numba with 1 → 22 threads; tile size | time, speedup, RSS | G1 |
| **E4** GPU | When does the GPU actually help? | size × tile size; **H2D / kernel / D2H timed separately**; 8 GB VRAM limit | GPU-vs-CPU crossover size; share of time spent on transfer | G1 |
| **E5** Pyramid on demand | How wrong is slope from a coarse level, and how much time does it save? | pyramid levels built from **real** data (Chamoli 2 m → 4–64 m; tile-571 8 m → 16–128 m); slope-from-level vs full-res slope aggregated to the same grid; secondary: vs independent HMA 8 m and Copernicus 30/90 m | RMSE, bias, % cells with error > 5°, split by slope class; time per level | **G2** |
| **E6** Interactive | Can on-the-fly computation keep up with pan and zoom? | precomputed tiles vs on-the-fly CPU vs GPU; cache on/off | tile latency p50/p95, cache hit rate, Cesium FPS | G1, G2 |
| E7 *(stretch)* Viewshed | Speed and accuracy of approximate visibility | R3 vs XDraw vs `gdal_viewshed`; DEM size, observer height | time, % cells misclassified vs R3 | G3 |
| E8 *(stretch)* Terrain distance | How much does the A* heuristic save? | Dijkstra vs A*; grid size | time, nodes expanded, path equality | G3 |

**Correctness gate:** before any engine timing is reported, our kernels must match `gdaldem` within float tolerance on the COP90 fixture and on the 30 m AOI.

---

## 6. Benchmark methodology

### 6.1 Recording format
One row per run, appended to `results/runs.csv` by `bench/harness.py`:

```
run_id, experiment, machine_id, git_sha, dataset, variant, res_m, cells, real_or_synthetic,
format, compression, op, method, impl, device, threads, cpu_set, cache_state, rep,
t_total, t_internal, peak_rss_mb, avg_cores, proc_read_mb, proc_write_mb, disk_read_mb,
ok, error, extra, cmd
```
- `t_total`: wall time of the whole process. `t_internal`: time the tool reports for its own core work (e.g. the read loop without Python start-up, or QGIS draw time). `rep 0` is a warm-up and is excluded from results.
- `peak_rss_mb`, `avg_cores`, `proc_read/write_mb` are **exact totals for the measured process** (read from its handle after it exits), not samples. This fixes the pilot, which measured QGIS instead of gdaldem.
- `disk_read_mb`: bytes physically read from disk during the run (separates real disk reads from cache hits).
- No timestamps per run. Per-sweep conditions go to `results/env/<experiment>_<n>.json`: power plan, AC power, Defender state, CPU core classes, pinned CPUs, free RAM, busiest processes. `results/machine.json` stores hardware and library versions.
- GPU runs (Phase 3) will add transfer and kernel times to `extra`, measured with CUDA events.

### 6.2 Protocol
- Laptop plugged in (the harness refuses to run on battery and blocks sleep), other applications closed.
- **Core pinning.** This CPU has 6 performance cores (12 threads) plus 8 efficiency and 2 low-power cores. Measured: gdaldem is **1.7× slower on an efficiency core and up to 2.7× slower on a low-power core**, and Windows can move a background process between them mid-run (the first E1 pass had one 2 m run take 108.9 s instead of ~56 s). Single-threaded tools are therefore pinned to the 12 performance-core threads, detected automatically (`performance_cpus()`). This measures every baseline tool at its best, so any speedup we report later is conservative. The unpinned first pass is kept in `results/e1_first_pass_unpinned.csv` as evidence.
- **Power plan:** Windows default "Balanced", recorded per sweep. With pinning, repeated runs agree within a few %, so it was not changed.
- **Windows Defender: on, with only the two benchmark scratch folders excluded** (`D:\geoguessers_data\bench_out`, `D:\geoguessers_data\e2`). Defender's CPU use *during* a run is small (0.02–0.05 of a core), but it scans each large output *after* the run: a deleted 10–40 GB output stays reserved in the hidden NTFS `$Deleted` area until the scan ends, which took over 15 minutes per file. Measured consequences: 108 GB (first attempt) and 35.6 GB (second attempt) of disk held by deleted outputs, and following runs slowed by 25–35% while the scans competed for disk and turbo budget (Chamoli 2 m warm runs with 1–2 GB of foreign disk reads; E2 2 m slope runs with growing foreign reads). The scratch files are written by our own GDAL tools and deleted within minutes, so excluding them protects nothing less; input data, the repo and the rest of the PC stay scanned. All final Phase 2 numbers were re-run under this setup; the earlier attempts are kept as evidence (`results/e1_first_pass_unpinned.csv`, `results/e1_chamoli_background_interference.csv`, `results/phase2_attempt2_defender_scanning.csv`).
- **GDAL settings for the baseline: defaults.** Checked: `GDAL_NUM_THREADS=ALL_CPUS` (parallel tile decoding) makes gdaldem 2–4% slower, and a 4 GB `GDAL_CACHEMAX` does not help (`docs/PHASE2_RESULTS.md`), so the default is gdaldem at its best.
- **Between runs** the harness waits until a deleted output's space is really free (outside the timed part) and stops cleanly if it is not released within 15 minutes, so the disk can never fill during a sweep.
- **1 warm-up run + 5 measured runs** per configuration; report **median and IQR**.
- **Exception for the synthetic 2 m / 1 m grids (> 1 B cells):** only read/copy references + slope (Horn) + hillshade (Horn), 3 cold runs + 1 warm run (the preceding cold run is the warm-up). Method and operator comparisons are size-independent, so they come from the four real grids, which get the full protocol. On these grids the file is too big for the cache to hold, so "warm" runs still read most of the file from disk; they are reported as such, not as true warm-cache runs.
- **Cold cache:** flush the Windows standby list before the run with Sysinternals RAMMap `-Et`, via the elevated scheduled task `\GeoGuessers\GeoGuessers-FlushCache` (`bench/cache.py`; the benchmark itself runs without admin). Verified: after a flush the whole file is read from disk again. **Warm cache:** immediate repeat.
- **Stage split** (where the time goes): `read` = read + decompress every full-resolution block and nothing else (`bench/read_blocks.py`, its own loop time); `copy` = `gdal_translate` to an uncompressed GeoTIFF (same read + same-size write as gdaldem). Then write + tool overhead ≈ copy − read, and compute ≈ gdaldem − copy. (The first version used `gdalinfo -checksum` as the read reference; computing the checksum itself cost more than half its time, so it was replaced.)
- Below ~30 m the runs take < 0.3 s and are dominated by program start-up; they are not used for per-cell speed claims.
- Failures (e.g. out-of-memory) are recorded as rows with `ok = False`. A failure is a result, not a missing value.

### 6.3 Standard plots
1. Time vs cells (log-log), one line per implementation, with the 16 GB RAM line marked.
2. Stacked bars of stage times (read / compute / transfer / write) per size.
3. Peak memory vs size.
4. **E5:** slope error vs speedup per pyramid level.
5. **E6:** tile latency CDF.

---

## 7. Labelling: naive, baseline and state of the art

| Operation family | Naive | Baseline (industry standard) | Optimised (ours / state of the art) |
|---|---|---|---|
| Slope, aspect, hillshade, TRI, TPI, roughness | Whole-array NumPy, single thread | `gdaldem` (Horn, ZT); QGIS tools. References: xarray-spatial, WhiteboxTools | Tiled + halo, Numba parallel, CuPy GPU, pyramid on-demand |
| Viewshed | R3 (exact, O(N^1.5)) | `gdal_viewshed` | XDraw, O(N), CPU then GPU |
| Terrain distance | Dijkstra | QGIS / GRASS `r.cost` | A* with admissible heuristic |

For the O(N) local operators, naive and optimised versions have the same complexity. The difference is **implementation and data movement**, as the lit review concludes. Horn vs ZT is a *method* choice: it is timed in E1, but it is not where speedups come from.

---

## 8. Phases and timeline

The project runs for three weeks (Week 1–3), ending at the submission deadline.

```
      |Week 1              |Week 2              |Week 3
P0    ███████
P1       ███████████████
P2             ██████████████████
P3                   ███████████████████████████
P4                                  █████████████████████
P5                                     ███████████████████████
P6 (stretch)                                        ░░░░░░░░░░░
P7                                                        ███████████████████
```

### Phase 0: Setup (start of Week 1) · SG · ✅ done
- Miniforge at `D:\miniforge3` (the install path must not contain spaces); conda env `geo` from `environment.yml` (Python 3.12, GDAL 3.13.3, CuPy 14.2, Numba 0.68).
- QGIS LTR 3.44.14 installed; `qgis_process` works headless.
- Repo scaffold; `results/machine.json` written by `bench/machine_info.py`.
- Exit checks passed: `gdalinfo --version`; CuPy runs on the RTX 4060; COP90 fixture opens; QGIS slope matches the OpenTopography reference.
- Remaining: Cesium client (Node + Vite) in `viz/cesium/`, moved to Phase 5.

### Phase 1: Data (Week 1) · KK · ✅ done
- ✅ Real data for tile-571 at 8 / 30 / 90 m and Chamoli at 2 m downloaded, checked and listed in the manifest (§3). Chamoli 2 m MD5 matches Zenodo; all tiles readable.
- ✅ `python datasets/prepare.py`: all four reprojected to UTM 44N on one aligned grid (origin snapped to 360 m) and written as COGs (512 tiles, ZSTD, AVERAGE overviews) to `D:\geoguessers_data\prepared\`. gdaldem slope runs on all four (90 m 0.15 s / 30 m 0.55 s / 8 m 9.7 s / 2 m 8.2 s).
- ✅ Chamoli 2 m is re-gridded with nearest-neighbour (source is already 2 m UTM 44N, only 0.09 / 0.16 m off our grid), so its elevation values are unchanged: it stays a clean accuracy truth. 264 M cells, 93.9% valid.
- ✅ Cross-source check: Chamoli 2 m averaged to 8 m vs the independent HMA 8 m tile: median difference −0.7 m, NMAD 5.1 m. The two share the same vertical reference, and the 8 m tile is consistent with the 2 m truth.
- Decision: **no extra 4 m / 16 m datasets.** The real ladder is 2 / 8 / 30 / 90 m; intermediate levels come from the COG overviews.
- ✅ Synthetic timing grids: `python datasets/prepare.py --synthetic` built 2 m (2.7 B cells) and 1 m (10.8 B cells, 43 GB as float32, past the 16 GB RAM) by cubic upsampling of the 8 m tile, in `D:\geoguessers_data\synthetic\`. Timing only.
- Optional: geoid-correct the 8 m tile to EGM2008 (only needed for E7).

### Phase 2: Baseline benchmark, E1 + E2 (end of Week 1 – middle of Week 2) · SC (harness by SG) · ✅ done
- ✅ Harness (`bench/harness.py`, `bench/sweep.py`): exact per-process time / peak memory / CPU / bytes, cold-cache flush, pinning to performance cores, run-condition snapshots, resumable sweeps, waits for deleted outputs to be freed.
- ✅ E1 (`bench/experiments/e1_baseline.py`): 10 gdaldem configs × 6 grids (90 m → 1 m) × cold / warm, plus read and copy references for the stage split. 560 runs.
- ✅ E2 (`bench/experiments/e2_storage.py`): 7 storage layouts × 8 m and 2 m. 224 runs. Large layout copies archived to the external drive.
- ✅ QGIS display test (`bench/experiments/e1_qgis.py`): open + draw 1920×1080, whole area / zoomed, with / without pyramid, 8 m → 1 m. 48 runs.
- ✅ Results, tables and charts: **`docs/PHASE2_RESULTS.md`**. Headline: gdaldem never runs out of memory (0.83 GB at 1 m = 43 GB of data) but is single-threaded and compute-bound (73% compute, 3.5 min for slope at 1 m); without a pyramid, QGIS needs 32 s per whole-area redraw at 1 m, with one 0.09 s.
- Next: send the progress update to the professor (draft: `docs/prof_update_phase2.md`).

### Phase 3: Engine, E3 + E4 (end of Week 1 – end of Week 2) · SG (CPU, tiling), KK (GPU) · in progress
Done so far:
- ✅ `demlab/kernels/numpy_k.py`: reference slope / aspect / hillshade (Horn, ZT), TRI (Riley, Wilson), TPI, roughness, gdaldem conventions; also runs on the GPU with CuPy (`xp=cupy`).
- ✅ `demlab/kernels/numba_k.py`: parallel CPU kernels; slope + aspect + hillshade fused into one pass.
- ✅ `demlab/io.py`, `demlab/engine.py`: window-by-window processing with a 1-cell halo, threaded reads, per-stage timings, any backend.
- ✅ Correctness: `python -m pytest tests/` (60 tests) on two 1024² crops (8 m with 55% nodata, steep 2 m). With gdaldem's float32 rounding reproduced, every cell of all 10 configurations matches gdaldem; nodata masks identical; Numba = NumPy = CuPy; tiled = whole grid for windows not aligned to the tiles. Our default float64 slope is within 0.015° of gdaldem (gdaldem adds the Horn neighbours in float32).
- First informal look (8 m grid, not yet through the harness): Numba slope incl. writing 1.6 s vs gdaldem 4.0 s; slope + aspect + hillshade in one pass 3.4 s vs ~11.3 s as three gdaldem runs. Writing is now the slowest stage (single-threaded); the CuPy array-style version is slow (3.9 s) because of temporaries and per-window transfers.
Next: parallel / compressed writing, a CuPy raw kernel with timed transfers, the naive whole-array version (memory breaking point), then E3 / E4 through the harness.
- `demlab/kernels/` with NumPy, Numba and CUDA versions of Horn/ZT slope, aspect, hillshade, TRI, TPI, roughness.
- `demlab/tiling.py`: windowed read + halo + write for out-of-core runs.
- Correctness tests against gdaldem (must pass first). Then thread scaling, tile-size sweep, GPU stage split, and the GPU crossover point.

### Phase 4: Pyramid on demand, E5 (middle of Week 2 – middle of Week 3) · SC
- Compute slope directly from overview level k using that level's cell size.
- Main: on the Chamoli sub-area, compare slope from levels 4, 8, 16, 32, 64 m with the real 2 m slope aggregated to the same grid.
- Full tile: the same comparison with 8 m as truth (levels 16–128 m).
- Cross-source: does our 8 m level from the Chamoli 2 m match the independent HMA 8 m DEM?
- Secondary check: does slope from our 32 m / 64 m level match slope from the real Copernicus 30 m / 90 m as well as the two products match each other?
- Error-vs-time-saved curves, split by slope class (flat / moderate / steep). **Headline result.**

### Phase 5: Tile server and visualisation, E6 (end of Week 2 – middle of Week 3) · SG (server), KK (Cesium, QGIS)
- FastAPI server: zoom → level → windowed read → kernel → colour map → PNG, with LRU cache.
- QGIS XYZ layer; CesiumJS page with terrain + slope/aspect/hillshade overlay and an op switcher.
- Measure tile latency: precomputed vs on-the-fly CPU vs GPU.
- Record a demo video as a backup for the live demo.

### Phase 6 (stretch): Viewshed and distance, E7 + E8 · SC
Only if Phases 2–5 are on track by the **start of Week 3**. R3 vs XDraw vs `gdal_viewshed` on a 30 m crop; Dijkstra vs A*.

### Phase 7: Report and demo (Week 3) · all
- Report: introduction → literature review (reuse, fix grammar) → method → results E1–E6 → **bottleneck discussion** (where the real bottleneck is at each size) → limitations → conclusion.
- Slides + live demo (video fallback). Freeze code, tag the release.

### Weekly checkpoints
| When | Must be true |
|---|---|
| Start of Week 1 | Environment works on the benchmark laptop |
| End of Week 1 | All datasets downloaded and in the manifest |
| Middle of Week 2 | E1/E2 curves done; update sent to the professor |
| End of Week 2 | Engine passes correctness tests; E3/E4 results in CSV |
| Middle of Week 3 | E5 results done; tile server serves slope tiles |
| Late Week 3 | Cesium/QGIS demo works; E6 measured |
| End of Week 3 (deadline) | Report, slides, code submitted |

---

## 9. Risks and fallbacks

| Risk | Fallback |
|---|---|
| Gaps in the 8 m tile (9.6% nodata) bias E5 | Report error only on cells whose full 3×3 neighbourhood is valid at every level; optionally restrict E5 to the gap-free northern part of the tile |
| CuPy kernels misbehave on Windows | Numba-CUDA kernels (CuPy itself is installed and working) |
| Cesium terrain provider too fiddly | Slope overlay on Cesium World Terrain; QGIS becomes the main demo |
| 1 m runs too slow to repeat 5 times | 3 cold + 1 warm on synthetic 2 m / 1 m (adopted), stated in the report |
| Behind schedule | Drop Phase 6 entirely (the meeting marked these "if possible") |

---

## 10. Repository layout

```
Geoguessers/
  docs/            PROJECT_PLAN.md, prof_questions.md
  datasets/        real rasters (gitignored), fixtures, manifest.csv, download_cop.py
                   (generated 4/2/1 m grids in D:\geoguessers_data, outside the repo)
  demlab/          io.py, tiling.py, pyramid.py, ops.py, kernels/{numpy_k,numba_k,cuda_k}.py
  bench/           harness.py, sampler.py, machine_info.py, experiments/e1_baseline.py … e6_tiles.py
  server/          app.py (FastAPI tile server)
  viz/cesium/      Vite + CesiumJS client
  tests/           test_kernels_vs_gdaldem.py
  results/         runs.csv, machine.json, plots/
  report/          final report + slides
  environment.yml, README.md
```

---

## Appendix A: Meeting points → where they are covered

| MoM section | Covered by |
|---|---|
| 1. Systems approach, laptop-only | §2 machine, all experiments on one laptop |
| 2. Real DEMs, 1 m → 30 m, push to the limit | §3 datasets, E1 size ladder |
| 3. Render only the required subset | §4 windowed COG reads, tile server |
| 4. Pyramid / multi-resolution | §4 COG overviews, E5 |
| 5. On-the-fly slope/aspect (+ hillshade, LOS, viewshed, distance) | demlab ops, E6; E7/E8 stretch |
| 6. Find the real bottleneck | §6 per-stage timing, E1–E4 |
| 7. CPU vs GPU split | E3, E4 (crossover, transfer share) |
| 8. Resolution follows the view | zoom → level mapping in the tile server |
| 9. Limits of existing algorithms | E1 break point for gdaldem / QGIS |
| 10. Integrate with GDAL / QGIS | §4 integration options (a)–(c) |
| 11. QGIS, Cesium, browser globe | Phase 5 |
| 12. Main direction | §1 goal |
