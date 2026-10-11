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

Benchmark grids are kept outside the repo in `D:\geoguessers_data\`; every dataset is listed in [datasets/manifest.csv](datasets/manifest.csv).

## Data

**Storage rules**
- Everything a benchmark reads or writes stays on the laptop's internal NVMe SSD (`D:\geoguessers_data\prepared`,
  `synthetic`, `bench_out`), so timings measure the tools, not a USB disk.
- The external drive (`K:\spatial project\`) is only for **large files (> 1 GB) produced by runs** once their results
  are recorded (e.g. the E2 layout copies), so the internal disk does not fill up. Move them with
  `bench\archive_large.ps1` (hash-verified).
- Small files stay in the project folder. Nothing is deleted: old or unneeded files go to the local `old files/` folder (gitignored)
  (see its README).
- Raw downloads live in `datasets/` (gitignored); `GEO_RAW` can point the scripts elsewhere.

```
$env:OPENTOPO_API_KEY = "<your key>"; python datasets/download_cop.py   # Copernicus 30 / 90 m
python datasets/prepare.py               # real 90 / 30 / 8 / 2 m -> aligned UTM 44N COGs
python datasets/prepare.py --synthetic   # + 2 m and 1 m grids for timing only (~22 GB)
```
The HMA 8 m tile (NASA Earthdata login) and the Chamoli 2 m DEM (Zenodo 4554647) are downloaded by hand into `datasets/`.

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
Results: [docs/PHASE2_RESULTS.md](docs/PHASE2_RESULTS.md).

## Our engine and its benchmark (Phase 3, CPU)

The engine processes a DEM window by window (reader threads → parallel Numba kernel → one writer thread), so its
memory stays around 1.4 GB whatever the grid size. It reproduces gdaldem's ten operator configurations.
```
python -m demlab.cli in.tif --ops slope,aspect,hillshade --out-dir OUT [--method Horn] [--threads 12]
python -m pytest tests/ -q                       # correctness vs gdaldem on 1024² crops (119 tests, CPU + GPU + pyramid)
python -m tests.check_full_grid                  # CPU and GPU engine vs gdaldem on the full 8 m and 2 m real grids
python -m bench.experiments.e3_cpu --plan        # E3: engine vs gdaldem; drop --plan to run
python -m bench.analysis.phase3_report           # tables (results/phase3_tables.md) + plots (results/plots/e3_*)
```
`--impl numpy` runs the single-threaded NumPy reference kernel in the same pipeline, and `--impl naive` loads the
whole grid into memory (it runs out of memory on the big grids, as intended).
Unattended: `powershell -ExecutionPolicy Bypass -File bench\run_e3.ps1` (progress in `logs\e3_log.txt`).
Results: [docs/PHASE3_RESULTS.md](docs/PHASE3_RESULTS.md).

## GPU engine and its benchmark (Phase 3, GPU)

Needs an NVIDIA GPU and CuPy. The same pipeline with our CUDA kernels; GPU memory use is capped at 4 GB, and the
sweep waits for the GPU to cool below 75 °C before each run and stops at 85 °C.
```
python -m demlab.cli in.tif --ops slope --out-dir OUT --impl cuda [--precision fp32|fp64] [--no-pinned] [--gpu-streams 2]
python -m bench.experiments.e4_gpu --plan        # E4: GPU vs CPU engine vs gdaldem; drop --plan to run
python -m bench.experiments.e4_crossover         # from which window size the GPU beats the CPU
python -m bench.analysis.e4_report               # tables (results/e4_tables.md) + plots (results/plots/e4_*)
```
Unattended: `powershell -ExecutionPolicy Bypass -File bench\run_e4.ps1` (progress in `logs\e4_log.txt`).
Results: [docs/PHASE3_GPU_RESULTS.md](docs/PHASE3_GPU_RESULTS.md).

## Derivatives on demand from the pyramid (Phase 4, E5)

How wrong is slope computed from a coarse pyramid level, and how much time does it save?
```
python -m bench.experiments.e5_timing --precompute   # once: slope pyramids to compare against (~20 s)
python -m bench.experiments.e5_accuracy              # error per level, by slope class, aspect, other DEMs (~5 min)
python -m bench.experiments.e5_timing                # time per tile / whole grid, three routes (~30 min)
python -m bench.analysis.e5_report                   # tables (results/e5_tables.md) + plots (results/plots/e5_*)
```
Unattended timing: `powershell -ExecutionPolicy Bypass -File bench\run_e5.ps1` (progress in `logs\e5_timing_log.txt`).
Results: [docs/PHASE4_RESULTS.md](docs/PHASE4_RESULTS.md).

Run variability for every experiment (median, quartiles and IQR of every configuration):
`python -m bench.analysis.run_stats` → `results/run_stats.md`.

## Layout

| Folder | Contents |
|---|---|
| `demlab/` | Processing engine: tiled IO, pyramid, CPU/GPU kernels |
| `bench/` | Benchmark harness and experiment scripts (E1–E8) |
| `server/` | Box server: computes only the selected box at the right pyramid level (Phase 5) |
| `viz/web/`, `qgis_plugin/` | Box-zoom viewers: browser page and QGIS plugin (Phase 5); `viz/cesium/` Cesium globe (stretch) |
| `tests/` | Correctness tests against gdaldem |
| `results/` | `runs.csv`, `machine.json`, plots |
| `report/` | Final report and slides |

## Team

Swayam Goyal · Siddharth Choudhary · Kartikeya
