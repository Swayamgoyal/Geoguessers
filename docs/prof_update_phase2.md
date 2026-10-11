Dear Sir,

Here is a short update on our large-DEM project. The data preparation and the baseline benchmarks are complete.

**Data.** We work on one Himalayan study area (Uttarakhand, Nanda Devi; about 100 × 100 km) at several resolutions:
real 90 m and 30 m (Copernicus), 8 m (NASA High Mountain Asia DEM) and 2 m for the Chamoli valley (Bhushan and Shean, 2021).
To go beyond the laptop's 16 GB of RAM we also made 2 m and 1 m versions of the whole area by upsampling; these
are used only for timing, never for accuracy. The largest grid has 10.8 billion cells (43 GB as float32).

**Baseline results** (GDAL / gdaldem and QGIS on one laptop: Core Ultra 9, 16 GB RAM, NVMe SSD; 832 measured runs):
1. gdaldem does not run out of memory even at 1 m: it streams the grid and peaks at 0.87 GB. Its time grows linearly
   with grid size (about 19–25 ns per cell), so one slope pass over the 1 m area takes 3.5 minutes.
2. The bottleneck is computation on a single CPU thread (about 73% of the time; 1 of 22 threads used), not disk
   reading (about 14%) or memory. Whether the file is already cached makes no real difference.
3. For display, the bottleneck is reading full-resolution data. Without a pyramid, QGIS needs 32 s to redraw the whole
   1 m area; with a pyramid it needs 0.09 s at every resolution.
4. File layout matters by up to about 40% (LZW compression is the slowest; tiled ZSTD is the best compressed format),
   but computation still dominates.
5. Slope, aspect, hillshade, TRI, TPI and roughness all cost about the same per cell, and Horn vs
   Zevenbergen–Thorne differ by at most 6%.

So on a laptop, the standard tools stop being practical rather than failing: processing is limited by
single-threaded computation, and display by reading data without a pyramid.

**Next steps.** We are now building our own engine: tiled, parallel CPU (Numba) and GPU (CuPy) versions of these
operators, computing several derivatives in one pass, and then on-demand computation from the pyramid levels for an
interactive QGIS / Cesium viewer. We will also measure how much slope accuracy is lost at each pyramid level,
against the real 2 m data.

Please let us know if you would like any changes in direction.

Regards,
Swayam Goyal, Siddharth Choudhary, Kartikeya
