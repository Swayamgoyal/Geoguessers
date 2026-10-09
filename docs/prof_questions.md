Dear Sir,

Following up on our earlier questions, here is how we plan to proceed. Please let us know if you would like any changes.

**1. Recording benchmarks**
Every run is recorded as one row in a CSV file with: dataset, resolution, number of cells, file format, operation, method, implementation, CPU/GPU, threads, cold or warm file cache, time per stage (disk read, compute, CPU-to-GPU transfer, write), peak memory and peak GPU memory. Each configuration gets one warm-up run and five measured runs, and we report the median and spread. Memory is measured on the processing process itself (in our pilot we had measured QGIS instead of gdaldem). All runs are on one laptop (16 GB RAM, RTX 4060 8 GB), and its full specification is saved with the results.

**2. How improvements will be implemented**
We will not modify GDAL itself. Instead we are building a small Python engine (NumPy / Numba on the CPU, CuPy on the GPU) that reads only the required window of a DEM from a multi-resolution pyramid (Cloud-Optimized GeoTIFF with overviews, read through GDAL), computes slope, aspect, hillshade and similar on the fly for that window at the matching resolution, and serves the result as map tiles to QGIS and a Cesium globe. GDAL's own tools (gdaldem, and the QGIS tools that call it) are the baseline that we measure against.

**3. Naive vs state of the art**
- Slope, aspect, hillshade, TRI, TPI, roughness: naive = whole-array, single-threaded; baseline = gdaldem (Horn and Zevenbergen–Thorne); optimised = tiled, parallel CPU, GPU and pyramid on-demand versions. These all have O(N) complexity, so the comparison is about implementation and data movement.
- Viewshed: naive = R3 (exact); baseline = gdal_viewshed; faster approximate = XDraw.
- Terrain distance: naive = Dijkstra; heuristic = A*.

The thresholds are the gdaldem baseline curve and the point where the data no longer fits in the laptop's RAM (16 GB) or GPU memory (8 GB).

We expect baseline results by 17 October and will share them with you then.

Regards,
Swayam Goyal, Siddharth Choudhary, Kartikeya
