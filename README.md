# GeoGuessers: Large-Scale DEM Processing and Visualisation

Spatial Informatics course project. We investigate how far large, high-resolution DEMs can be processed and visualised on a single laptop, using pyramids, on-demand terrain derivatives (slope, aspect, hillshade, ...) and CPU/GPU processing chosen by measured bottlenecks.

- Plan and timeline: [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md)
- Meeting notes: [project_mom.md](project_mom.md)
- Literature review: [GeoGuessers_lit_review.pdf](GeoGuessers_lit_review.pdf)

## Setup

1. Install [Miniforge](https://github.com/conda-forge/miniforge) and QGIS LTR.
   The Miniforge install path must not contain spaces (e.g. use `D:\miniforge3`, not `C:\Users\first last\...`):
   ```
   winget install --id CondaForge.Miniforge3 -e --scope user --location "D:\miniforge3"
   winget install --id OSGeo.QGIS_LTR -e
   ```
2. Create the environment:
   ```
   conda env create -f environment.yml
   conda activate geo
   ```
3. Record the machine spec (needed with every benchmark result):
   ```
   python bench/machine_info.py
   ```
4. Check:
   ```
   gdalinfo --version
   python -c "import cupy; cupy.show_config()"
   ```
5. Cold-cache benchmarks (one-time, needs one admin prompt): download
   [RAMMap64.exe](https://live.sysinternals.com/RAMMap64.exe) to `D:\geoguessers_data\tools\`, then in an
   **admin** PowerShell run
   ```
   powershell -ExecutionPolicy Bypass -File bench\register_flush_task.ps1
   ```
   This registers a scheduled task that empties the file cache (`RAMMap -Et`). Benchmarks trigger it
   through `bench/cache.py` and do not need admin themselves.

Raw DEMs are kept outside the repo in `D:\geoguessers_data\`; every dataset is listed in [datasets/manifest.csv](datasets/manifest.csv).

## Data

**Storage rule:** everything a benchmark reads or writes stays on the laptop's internal NVMe SSD
(`D:\geoguessers_data\prepared`, `synthetic`, `bench_out`), so timings measure the tools, not a USB disk.
The external drive is only an archive: raw downloads, old test files, logs and finished experiment copies live in
`K:\GeoGuessers_archive\`. Scripts find the raw downloads through the `GEO_RAW` environment variable
(`K:\GeoGuessers_archive\raw_downloads` on the benchmark laptop; defaults to `datasets/`). Raw files are only
needed to rebuild the prepared grids.

```
$env:OPENTOPO_API_KEY = "<your key>"; python datasets/download_cop.py   # Copernicus 30 / 90 m
python datasets/prepare.py               # real 90 / 30 / 8 / 2 m -> aligned UTM 44N COGs
python datasets/prepare.py --synthetic   # + 2 m and 1 m grids for timing only (~22 GB)
```
The HMA 8 m tile (NASA Earthdata login) and the Chamoli 2 m DEM (Zenodo 4554647) are downloaded by hand into `$GEO_RAW`.

## Benchmarks (Phase 2)

Run from the repo root in the `geo` env, plugged in, with other apps closed. Each sweep skips runs already in
`results/runs.csv`, so an interrupted sweep can just be started again.
```
python -m bench.experiments.e1_baseline --plan   # list runs; drop --plan to run (E1: gdaldem scaling)
python -m bench.experiments.e2_storage           # E2: storage layout / compression
python -m bench.experiments.e1_qgis              # QGIS open + draw, with / without pyramid
python -m bench.analysis.phase2_report           # tables (results/phase2_tables.md) + plots (results/plots/)
```
Or all three sweeps unattended: `powershell -ExecutionPolicy Bypass -File bench\run_phase2.ps1`
(progress in `D:\geoguessers_data\phase2_log.txt`).

## Layout

| Folder | Contents |
|---|---|
| `demlab/` | Processing engine: tiled IO, pyramid, CPU/GPU kernels |
| `bench/` | Benchmark harness and experiment scripts (E1–E8) |
| `server/` | On-the-fly tile server |
| `viz/cesium/` | Cesium web client |
| `tests/` | Correctness tests against gdaldem |
| `results/` | `runs.csv`, `machine.json`, plots |
| `report/` | Final report and slides |

## Team

Swayam Goyal · Siddharth Choudhary · Kartikeya
