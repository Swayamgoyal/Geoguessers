# GeoGuessers: Large-Scale DEM Processing and Visualisation

Spatial Informatics course project. We investigate how far large, high-resolution DEMs can be processed and visualised on a single laptop, using pyramids, on-demand terrain derivatives (slope, aspect, hillshade, ...) and CPU/GPU processing chosen by measured bottlenecks.

- Plan and timeline: [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md)
- Meeting notes: [project_mom.md](project_mom.md)
- Literature review: [GeoGuessers_lit_review.pdf](GeoGuessers_lit_review.pdf)

## Setup

1. Install [Miniforge](https://github.com/conda-forge/miniforge) and QGIS LTR.
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

Raw DEMs are kept outside the repo in `D:\geoguessers_data\`; every dataset is listed in [datasets/manifest.csv](datasets/manifest.csv).

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
