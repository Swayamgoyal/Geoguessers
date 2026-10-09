# Unused files (kept for reference)

These files were collected early in the project but are **not used** in the current plan, which works on a single study area (HMA tile-571, Uttarakhand / Nanda Devi; see `docs/PROJECT_PLAN.md` §3). They are kept here in case we need them later.

`.tif` and `.png` files are gitignored, so the HMA strips exist only on the machine where they were downloaded. The source links below let anyone fetch them again.

| File | What it is | Area | Res / grid | Why not used | Possible later use |
|---|---|---|---|---|---|
| `rasters_COP90.tar.gz` → `output_hh.tif` | Copernicus GLO-90 crop from OpenTopography | Everest / Khumbu: top-left 86.813°E, 28.063°N | 90 m (3″), 272 × 191 px, EPSG:4326, elev 4,298–8,726 m | Different area from our study area; too small for benchmarking | Tiny unit-test input |
| `viz (1).tar.gz` → `viz.hh_{slope,aspect,hillshade,roughness,color-relief}.tif` | OpenTopography's gdaldem outputs for `output_hh.tif` | Same as above | Same as above; nodata -9999 | We can now generate gdaldem references ourselves for any area | Independent reference: QGIS slope (scale 111120) matched `viz.hh_slope.tif` to 1e-5° on all 51,030 valid cells |
| `hma8m_strips/HMA_DEM8m_AT_20161105_0531_…F500.tif` | NSIDC `HMA_DEM8m_AT` v1: single along-track stereo strip | Uttarakhand / Kumaon, lon 79.978–80.151, lat 30.495–30.619 (inside tile-571) | 8 m, 2051 × 1696, EPSG:32644, 78.2% valid, elev 3,873–7,126 m | Superseded by the 8 m mosaic (tile-571) | Compare one raw strip against the mosaic |
| `hma8m_strips/HMA_DEM8m_AT_20161106_0456_…BA00.tif` | NSIDC `HMA_DEM8m_AT` v1: single along-track stereo strip | Nepal / Ganesh Himal, lon 85.039–85.256, lat 28.250–28.581 | 8 m, 2582 × 4534, EPSG:32645, 60.5% valid, elev 2,383–7,348 m | Outside the study area | Test nodata / gap handling (40% missing) |
| `hma8m_strips/HMA_DEM8m_AT_20161117_…_hs_az315.png` | Hillshade **preview image** (not elevation data) of an HMA strip | Bhutan, ~90.75–90.94°E, 27.90–28.39°N | PNG | Not a DEM; outside the study area | None |
| `*.tar.gz.properties` | Archive size metadata (written by an editor extension) | – | – | Not data | None |

## Other old or one-off files

Project rule: nothing is deleted; anything no longer needed is moved here. (`.tif`, `.png`, `.exe` and `.aux.xml` are gitignored, so those exist only on the benchmark laptop.)

| Folder | What it is |
|---|---|
| `scratch_tests/` | Outputs of one-off checks: the synthetic-data reliability test (8 m crop rebuilt from 16 m with nearest / bilinear / cubic, plus their slopes and LZW sizes; results in `docs/PROJECT_PLAN.md` §3.6) and the first gdaldem slope outputs per grid. |
| `qgis_test_images/` | Images from the first headless QGIS render test (8 m grid with and without pyramid). |
| `tools_diagnostics/` | Disk-space investigation: scripts and reports that found 108 GB of deleted-but-still-open benchmark outputs in NTFS `$Deleted` (released once Defender finished scanning), `handle64.exe`, the old E1 launcher, and the log of the cache-flush task registration. |
| `gdal_aux_cache/` | `.aux.xml` statistics caches that GDAL/QGIS had written next to the benchmark grids. Moved away so QGIS "open layer" timings start from a clean state (QGIS reuses these caches). |

## Where they came from
- Copernicus crops: OpenTopography Global DEM (Copernicus GLO-90), <https://portal.opentopography.org/>
- HMA strips: NASA Earthdata, collection `HMA_DEM8m_AT` (C3249536271-NSIDC_CPRD), <https://search.earthdata.nasa.gov/search/granules?p=C3249536271-NSIDC_CPRD> (Earthdata login required)

## Reading the archives without extracting
```python
import rasterio
rasterio.open('/vsitar/unnecessary/rasters_COP90.tar.gz/output_hh.tif')
rasterio.open('/vsitar/unnecessary/viz (1).tar.gz/viz.hh_slope.tif')
```
