# GeoGuessers: Project Plan

**Large-scale DEM processing and visualisation on a laptop**
Spatial Informatics · Team: Swayam Goyal (SG), Siddharth Choudhary (SC), Kartikeya (KK)
Deadline: **31 Oct 2026** · Plan date: 9 Oct 2026

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

**Why this matters.** For a ~100 km × 100 km Himalayan study area in float32:

| Resolution | Cells | Size in memory | Fits in 16 GB? |
|---|---|---|---|
| 30 m | ~11 M | 44 MB | yes |
| 10 m | ~100 M | 0.4 GB | yes |
| 5 m | ~400 M | 1.6 GB | yes |
| 2 m | ~2.5 B | 10 GB | borderline (input + output do not both fit) |
| **1 m** | **~10 B** | **40 GB** | **no, out-of-core processing required** |

The point where whole-array processing fails (between 2 m and 1 m) is exactly what we want to measure and then get past.

---

## 3. Datasets

### 3.1 What we already have (`datasets/`)

| File | Contents | Use |
|---|---|---|
| `rasters_COP90.tar.gz` → `output_hh.tif` | Copernicus GLO-90 crop, 272 × 191 px, float32, 3″ (~90 m), WGS84 geographic. Top-left 86.813°E, 28.063°N (Everest / Khumbu) | Correctness fixture |
| `viz (1).tar.gz` | OpenTopography gdaldem outputs for the same area: slope, aspect, hillshade, roughness, color-relief | Reference outputs. Our kernels must reproduce these |

These are far too small for scaling (~52 k cells) but ideal for unit tests. Note: they are in degrees, so the slope comparison must apply the degree→metre scale factor (or we reproject first).

### 3.2 What to download

| Resolution | Dataset | Coverage | Role | Source |
|---|---|---|---|---|
| 30 m | **Copernicus GLO-30** | Global | Real-data baseline; top pyramid levels | OpenTopography, or AWS open data `copernicus-dem-30m` |
| 30 m | NASADEM / ALOS AW3D30 / CartoDEM v3 | Global / India | Optional: cross-check of DEM source error | OpenTopography, Bhuvan |
| **8 m** | **High Mountain Asia 8 m DEM** (NSIDC `HMA_DEM8m_MOS`) | Himalaya | **Real high-resolution Himalayan terrain** for accuracy work | NSIDC (needs a free NASA Earthdata login) |
| 0.5–2 m | **swissALTI3D** or **USGS 3DEP 1 m** lidar | Swiss Alps / US Rockies | Real ~1 m alpine relief for the top of the scaling curve (no free 1 m Himalayan DEM exists) | swisstopo; AWS / OpenTopography |
| 15/10/5/2/1 m (synthetic) | Resampled from GLO-30 | Same AOI | **Timing only.** Adds cells but no terrain detail | Our own `gdalwarp` |

**Areas of interest**
- **Uttarakhand, N30 E79**, reprojected to UTM 44N (EPSG:32644). Main scaling region, same as the pilot.
- **Everest / Khumbu**, UTM 45N (EPSG:32645). 8 m HMA accuracy work and the demo.

**Rules**
1. Timing experiments use the size ladder on one AOI, so only size changes.
2. Accuracy experiments (E5, E7) use **only real high-resolution data**, never resampled grids.
3. All DEMs are reprojected to a metric UTM CRS before computing derivatives.
4. Every file goes into `datasets/manifest.csv` (name, source, resolution, CRS, size, cells, checksum). Raw data lives in `D:\geoguessers_data\` and is not committed.

**First check (KK):** confirm that the HMA 8 m tiles actually cover the Khumbu AOI without large gaps, and that total download sizes fit on D:.

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
| **E5** Pyramid on demand | How wrong is slope from a coarse level, and how much time does it save? | pyramid level 0..k on **real** 8 m and ~1 m data; slope-from-overview vs full-res slope aggregated to the same grid | RMSE, bias, % cells with error > 5°, split by slope class; time per level | **G2** |
| **E6** Interactive | Can on-the-fly computation keep up with pan and zoom? | precomputed tiles vs on-the-fly CPU vs GPU; cache on/off | tile latency p50/p95, cache hit rate, Cesium FPS | G1, G2 |
| E7 *(stretch)* Viewshed | Speed and accuracy of approximate visibility | R3 vs XDraw vs `gdal_viewshed`; DEM size, observer height | time, % cells misclassified vs R3 | G3 |
| E8 *(stretch)* Terrain distance | How much does the A* heuristic save? | Dijkstra vs A*; grid size | time, nodes expanded, path equality | G3 |

**Correctness gate:** before any engine timing is reported, our kernels must match `gdaldem` within float tolerance on the COP90 fixture and on the 30 m AOI.

---

## 6. Benchmark methodology

### 6.1 Recording format
One row per run, appended to `results/runs.csv`:

```
run_id, timestamp, machine_id, git_sha,
dataset, res_m, cells, format, compression, tile_px,
op, method, impl, device, threads, cache_state,
t_read, t_compute, t_h2d, t_d2h, t_write, t_total,
peak_rss_mb, peak_vram_mb, cpu_pct, ok, error
```
`results/machine.json` stores CPU, RAM, GPU, driver, OS, and GDAL/Python/library versions.

### 6.2 Protocol
- Laptop plugged in, Windows "Best performance" power mode, other applications closed.
- **1 warm-up run + 5 measured runs** per configuration; report **median and IQR**.
- **Cold cache:** flush the Windows standby list before the run (Sysinternals RAMMap `-Ec`, admin). **Warm cache:** immediate repeat.
- Peak memory: sample the **child process** (e.g. gdaldem) with psutil every 50 ms. This fixes the pilot, which measured QGIS and not gdaldem.
- GPU timings use CUDA events. Transfer and kernel time are reported separately.
- Failures (out-of-memory, > 30 min timeout) are recorded as rows with `ok = false`. A failure is a result, not a missing value.

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

```
Oct   9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31
P0    ███████
P1       ███████████████
P2             ██████████████████
P3                   ███████████████████████████
P4                                  █████████████████████
P5                                     ███████████████████████
P6 (stretch)                                        ░░░░░░░░░░░
P7                                                        ███████████████████
```

### Phase 0: Setup (9–11 Oct) · SG
- Install Miniforge and create conda env `geo` (Python 3.12, conda-forge) from `environment.yml`.
- Install QGIS LTR (OSGeo4W or standalone).
- Set up the Cesium client (Node + Vite) in `viz/cesium/`.
- Repo scaffold, `bench/machine_info.py` to write `results/machine.json`.
- **Exit check:** `gdalinfo --version` works; `python -c "import cupy; cupy.show_config()"` sees the RTX 4060; QGIS opens the COP90 fixture.

### Phase 1: Data (10–14 Oct) · KK
- Download GLO-30 for Uttarakhand, HMA 8 m for Khumbu, and one swissALTI3D / 3DEP 1 m block.
- Reproject to UTM and convert to COG with overviews.
- Build the synthetic size ladder 30/15/10/5/2/1 m.
- Fill `datasets/manifest.csv`.

### Phase 2: Baseline benchmark, E1 + E2 (12–17 Oct) · SC (harness by SG)
- `bench/harness.py`: subprocess runner, psutil sampler, cache flush, CSV writer.
- Run `gdaldem` for all ops × sizes × cold/warm, with spot checks through QGIS tools.
- Find and document the break point. Run the format/compression sweep.
- **Milestone, 17 Oct: baseline curves done. Send a progress update to the professor.**

### Phase 3: Engine, E3 + E4 (14–22 Oct) · SG (CPU, tiling), KK (GPU)
- `demlab/kernels/` with NumPy, Numba and CUDA versions of Horn/ZT slope, aspect, hillshade, TRI, TPI, roughness.
- `demlab/tiling.py`: windowed read + halo + write for out-of-core runs.
- Correctness tests against gdaldem (must pass first). Then thread scaling, tile-size sweep, GPU stage split, and the GPU crossover point.

### Phase 4: Pyramid on demand, E5 (19–25 Oct) · SC
- Compute slope directly from overview level k using that level's cell size.
- Compare with full-resolution slope aggregated to the same grid, on real 8 m and ~1 m data.
- Error-vs-time-saved curves, split by slope class (flat / moderate / steep). **Headline result.**

### Phase 5: Tile server and visualisation, E6 (20–27 Oct) · SG (server), KK (Cesium, QGIS)
- FastAPI server: zoom → level → windowed read → kernel → colour map → PNG, with LRU cache.
- QGIS XYZ layer; CesiumJS page with terrain + slope/aspect/hillshade overlay and an op switcher.
- Measure tile latency: precomputed vs on-the-fly CPU vs GPU.
- Record a demo video as a backup for the live demo.

### Phase 6 (stretch): Viewshed and distance, E7 + E8 · SC
Only if Phases 2–5 are on track by **24 Oct**. R3 vs XDraw vs `gdal_viewshed` on a 30 m crop; Dijkstra vs A*.

### Phase 7: Report and demo (26–31 Oct) · all
- Report: introduction → literature review (reuse, fix grammar) → method → results E1–E6 → **bottleneck discussion** (where the real bottleneck is at each size) → limitations → conclusion.
- Slides + live demo (video fallback). Freeze code, tag the release.

### Weekly checkpoints
| Date | Must be true |
|---|---|
| 11 Oct | Environment works on the benchmark laptop |
| 14 Oct | All datasets downloaded and in the manifest |
| 17 Oct | E1/E2 curves done; update sent to the professor |
| 22 Oct | Engine passes correctness tests; E3/E4 results in CSV |
| 25 Oct | E5 results done; tile server serves slope tiles |
| 27 Oct | Cesium/QGIS demo works; E6 measured |
| 31 Oct | Report, slides, code submitted |

---

## 9. Risks and fallbacks

| Risk | Fallback |
|---|---|
| HMA 8 m download slow, or AOI has gaps | Use swissALTI3D / 3DEP for all high-resolution accuracy work |
| CuPy install fails on Windows | Numba-CUDA kernels |
| Cesium terrain provider too fiddly | Slope overlay on Cesium World Terrain; QGIS becomes the main demo |
| 1 m runs too slow to repeat 5 times | 3 runs at 1 m, stated in the report |
| Behind schedule | Drop Phase 6 entirely (the meeting marked these "if possible") |

---

## 10. Repository layout

```
Geoguessers/
  docs/            PROJECT_PLAN.md, prof_questions.md
  datasets/        small fixtures + manifest.csv  (raw data in D:\geoguessers_data, gitignored)
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
