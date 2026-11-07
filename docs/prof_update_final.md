Dear Sir,

Here is our final update on the large-DEM project. Since the Phase 2 update (baseline benchmarks), we have built
our own engine, measured on-demand derivatives from the pyramid, and built and measured the interactive viewer you
asked for. The final report, the slides and a demo video are in the repository
(https://github.com/Swayamgoyal/Geoguessers, folder `report/`).

**1. Our own engine, CPU and GPU (Phase 3).**
- **CPU:** a tiled, parallel engine (Numba) reproduces all ten gdaldem configurations. Slope is 2.1–3.5× faster than
  gdaldem: 60 s vs 208 s on the 1 m grid of 10.8 billion cells. Memory stays at about 1.4 GB on every grid size,
  while a whole-grid NumPy version runs out of memory on the 2 m synthetic and 1 m grids. Three products in one pass cost little more than one.
- **GPU (RTX 4060):** our CUDA kernel computes slope 50× faster than the CPU kernel. The whole run, however, is only
  1.0–1.4× faster (43.8 s at 1 m), because copying data to and from the GPU is 95% of the GPU's own time. The GPU
  beats the CPU from 512 × 512 cells per window.
- **The bottleneck:** once computation is parallel, it moves to decompressing input and writing output. Decoding
  and moving data cost more than the slope arithmetic.

**2. Derivatives on demand from the pyramid (Phase 4; research gap G2).**
- **Cost:** computing slope from a pyramid level makes every 512 × 512 display tile cost 5–8 ms at any zoom. That is
  8–450× cheaper than computing it at full resolution and averaging.
- **Error:** the price is a systematic underestimate of slope. On the real 2 m Chamoli DEM the RMSE is about 2.5°
  one level up, growing by about 1.5° per further level, and is worst on the steepest ground.
- **Aspect** survives coarse levels much better (median error 2–8°).
- **Comparison with other data:** a pyramid level of the 2 m data is closer to the truth than an independent DEM of
  the same resolution (HMA 8 m, Copernicus 30 m and 90 m).

**3. Interactive viewer (Phase 5).**
- **What we built:**
  - a tile server that computes only the visible tiles, from the pyramid level that matches the screen;
  - a browser viewer that pans and zooms continuously, with a short trailing debounce on zoom and prefetching of
    the neighbouring views;
  - a QGIS plugin: drag a box, and the result is added as a georeferenced layer. A full-resolution box is identical
    to gdaldem's slope.
- **How we measured it:** 17 scripted interaction traces, 24 configurations, 1,068 runs (experiment E6). The
  results:
  - **Panning is seamless:** 98–100% of the tiles entering the view are already in the browser, at up to two view
    widths per second. Without prefetch the figure is 0–50%.
  - **The zoom debounce cuts server work 3.3×** (62 → 19 tiles per zoom gesture), and the first exact tile follows
    within about 70 ms. Notched mouse-wheel traces set the debounce to 150 ms.
  - **Prefetch does not slow what the user is looking at.** On identical tiles, the server's 95th-percentile latency
    is 90 ms with prefetch and 95 ms without. Prefetch runs on the efficiency cores and stops whenever the user
    acts.
  - **The remaining latency** comes from the browser's six connections per server and from block decoding, not from
    computing the derivatives. This is the same bottleneck the earlier phases found.
  - **A real browser (headless Chrome)** reproduces the simulated client's request counts and timings within 10%.

**Not done:** G3 (viewshed, terrain distance) remains future work, together with a GPU path for tiles and a Cesium
globe. Phase 3 predicts little GPU gain at tile size once the transfer is counted.

Thank you for the guidance during the project. Please let us know if you would like anything changed before the
presentation.

Regards,
Swayam Goyal, Siddharth Choudhary, Yakkala Viswanadha Kartikeya
