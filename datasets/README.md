# Raw data

Sources, extents, sizes and checksums of every file are in `manifest.csv`.

| File | In this repository | Source |
|---|---|---|
| `cop90_tile571.tif` (6.7 MB) | yes | Copernicus GLO-90 via OpenTopography (`download_cop.py`) |
| `cop30_tile571.tif` (59 MB) | yes | Copernicus GLO-30 via OpenTopography (`download_cop.py`) |
| `HMA_DEM8m_MOS_20170716_tile-571.tif` (405 MB) | no (over GitHub's 100 MB file limit) | NASA NSIDC HMA_DEM8m_MOS v1, tile 571 (Earthdata login), doi:10.5067/KXOVQ9L172S2 |
| `Chamoli_Sept2015_Composite_DEM2m_wmean.tif` (810 MB) | no (over GitHub's 100 MB file limit) | Bhushan & Shean (2021), Zenodo 4554647, doi:10.5281/zenodo.4554647 |

The two large DEMs are downloaded by hand into this folder (they are also on the project's external-drive copy).
Then `python datasets/prepare.py` builds the benchmark grids (`--synthetic` adds the 2 m and 1 m timing grids).

Copernicus DEM attribution: produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and
Space GmbH 2014-2018, provided under COPERNICUS by the European Union and ESA; all rights reserved. Distributed by
OpenTopography (doi:10.5069/G9028PQB).
