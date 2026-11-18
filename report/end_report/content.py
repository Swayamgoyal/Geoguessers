"""Text of the end report, as blocks for build_report.py.

Block types:
  ("title", text) | ("authors", [(name, sup)]) | ("emails", text) | ("affil", text)
  ("h1", text) | ("h2", text) | ("h3", text) | ("p", text) | ("abstract", text) | ("keywords", text)
  ("eq", key, number)                      equations are defined in build_report.py
  ("fig", path, caption)                   caption below the figure
  ("table", caption, header, rows, note)   caption above, horizontal rules only
  ("ref", text)                            reference list entry (author-year, no numbers)
Inline *italic* and **bold** are supported in p/abstract/caption text.
"""

TITLE = ("Where the Bottleneck Lies: Processing and Interactive Viewing of Billion-Cell Digital Elevation Models "
         "on a Single Laptop")

BLOCKS = [
    ("title", TITLE),
    ("authors", [("Swayam Goyal", "1"), ("Siddharth Choudhary", "1"), ("Yakkala Viswanadha Kartikeya", "1")]),
    ("emails", "swayam.goyal@research.iiit.ac.in¹, Siddharth.c@research.iiit.ac.in¹, "
               "kartikeya.yakkala@research.iiit.ac.in¹"),
    ("affil", "¹International Institute of Information Technology Hyderabad, Gachibowli, Hyderabad, Telangana, "
              "500032, India."),

    # ------------------------------------------------------------------ abstract
    ("h1u", "Abstract"),
    ("abstract",
     "A 1 m digital elevation model (DEM) of a 100 km × 100 km Himalayan area holds 10.8 billion cells, 43 GB as "
     "float32, 2.6 times the memory of our laptop. We asked how far such data can be processed and displayed on "
     "one laptop, and which stage limits the work. On real DEMs from 90 m to 2 m and synthetic 2 m and 1 m grids "
     "of the Garhwal Himalaya, six experiments with 2,885 measured runs covered GDAL and QGIS, a tiled CPU and GPU "
     "terrain engine, slope computed on demand from pyramid levels, and an interactive viewer. gdaldem never ran "
     "out of memory but used one thread and spent 73% of its time computing. Our engine was 2.1–3.5 times faster "
     "with identical results; the GPU kernel was 50 times faster than the CPU kernel, but whole runs only 1.0–1.4 "
     "times, because copying, decompression and writing dominated. On demand, a 512 × 512 display tile cost 5–8 ms "
     "at every zoom level, 8–450 times less than an exact computation, at a slope underestimate of 2.3–6.4° RMSE "
     "one to four levels up. The viewer kept up with continuous pan and zoom, also on a 2.85-billion-cell lidar "
     "DEM."),
    ("keywords", "Digital elevation model; Terrain derivatives; Multi-resolution pyramid; GPU computing; "
                 "Interactive visualisation; Performance benchmarking"),

    # ------------------------------------------------------------------ 1 introduction
    ("h1", "1. Introduction"),
    ("p",
     "A digital elevation model is a raster in which every cell stores a ground height, and most terrain analysis "
     "starts from one. Desktop GIS tools derive slope, aspect, hillshade and roughness from a DEM with local "
     "operators that look at the 3 × 3 window around each cell (Horn 1981; Zevenbergen and Thorne 1987), and "
     "the same data feed non-local analyses such as viewsheds and least-cost paths. Each halving of the cell size "
     "quadruples the number of cells. A 100 km × 100 km area holds 169 million cells at 8 m, 2.7 billion at 2 m and "
     "10.8 billion at 1 m, or 43 GB as 4-byte floating-point numbers. High-resolution DEMs from stereo satellite "
     "imagery and airborne lidar now reach this size for single study areas, while much of the analysis is still "
     "done on a laptop with 16 GB of memory and a screen that shows about two million pixels."),
    ("p",
     "The mismatch between data and display is large. A 1920 × 1080 screen shows about two million pixels, so a "
     "whole-area view of a 1 m grid of such an area can show at most one cell in five thousand; the other 99.98% "
     "are read, decoded and computed only to be averaged away. Analysis of mountain hazards adds a second pressure. "
     "After events such as the February 2021 Chamoli rock and ice avalanche in the Garhwal Himalaya, "
     "high-resolution DEMs of the affected valleys were released soon afterwards (Bhushan and Shean 2021), and the "
     "people who use them often have a laptop rather than a cluster. Knowing which stage limits the work on such "
     "a machine, and what it costs to look at the data at a coarser resolution, is therefore a practical question "
     "as much as a technical one."),
    ("p",
     "The local operators share a simple property: each visits every cell once, so a naive implementation and a "
     "highly optimised one both cost O(N) for N cells and differ only in how the work is organised. The variants "
     "in common use differ in their weighting rather than their cost. Horn (1981) weights the four direct "
     "neighbours twice as heavily as the diagonal ones, Zevenbergen and Thorne (1987) fit a surface through the "
     "window, and the terrain ruggedness index has two common forms (Riley et al. 1999; Wilson et al. 2007) that "
     "Trevisani et al. (2023) revisited. Guth and Kane (2021) adapted slope, aspect and hillshade to non-square "
     "cells and found that computed slope changes roughly logarithmically with grid spacing. The cost of terrain "
     "analysis at high resolution is therefore a question of data volume and implementation, not of algorithmic "
     "complexity."),
    ("p",
     "Resolution also changes the result. Zhang and Montgomery (1994) showed that computed slope decreases as the "
     "grid becomes coarser, Deng et al. (2007) found that the size of the change depends on where a point lies in "
     "the landform, and Polidori and El Hage (2020) argue that errors in the source data propagate into every "
     "derivative, so that nominal resolution is a weak guide to a DEM's usefulness. On the cost side, global "
     "products show how large the data become: Amatulli et al. (2020) computed geomorphometric layers for the "
     "whole globe, and Ho et al. (2025) note that a 1 arc-second global grid holds about 202 billion pixels and can "
     "only be processed in tiles with overlap, in parallel. Both precompute every layer at fixed scales."),
    ("p",
     "Work on scaling terrain computation has mostly addressed throughput. Barnes (2016) tiled the DEM in a "
     "producer–consumer scheme that runs unchanged on one core, many cores or a cluster and reached "
     "trillion-cell datasets on ordinary hardware. Yu et al. (2024) scheduled neighbourhood operations on the CPU "
     "and the GPU together and reported a speed-up of about 29 on a 1.7 GB raster, a fifth better than with the GPU "
     "alone. For non-local operations the methods differ in complexity as well: GPU versions of the XDraw viewshed "
     "have been built (Cauchi-Saunders and Lewis 2015) and load-balanced over equal-area partitions (Dou et al. "
     "2019), and Sanchez-Fernandez et al. (2021) found that relocating the DEM in memory mattered more than adding "
     "GPUs. For display, Losasso and Hoppe (2004) cached terrain in nested grids centred on the viewer, so that "
     "detail follows the view at a steady frame rate whatever the dataset size, and Campos et al. (2020) built a "
     "multi-resolution pyramid for virtual globes one tile at a time because a continent-scale mesh does not fit "
     "in commodity memory. These pyramids carry elevation only; derived products are still computed in advance."),
    ("p",
     "Two gaps follow from this literature. First, the reported speed-ups range from about 29 to several hundred "
     "times across different baselines and hardware, and none of the studies separates disk reading, "
     "decompression, CPU–GPU transfer, computation, writing and display. It is therefore unclear where standard "
     "GDAL and QGIS tools stop being practical on a single laptop, and when a GPU actually helps (gap G1). "
     "Second, pyramids are used to display elevation, but derivatives are not computed from them on demand, and "
     "the error of slope taken from a coarse pyramid level has not been measured against the time it saves "
     "(gap G2). A third gap, the accuracy of approximate viewsheds and of A* path search (Hart et al. 1968) in "
     "high-relief terrain, was set as a stretch goal and is left for future work."),
    ("p",
     "The project was framed as a systems study after a discussion with the course instructor: work within the "
     "available hardware, find the actual bottleneck before assuming that a GPU is the answer, render only the "
     "part of the data in view, compute derivatives for that part on demand from a pyramid, and integrate with "
     "GDAL and QGIS rather than rebuild a GIS. This study therefore has four objectives:"),
    ("p",
     "(1) to measure where GDAL's gdaldem and QGIS stop being practical on one laptop, from 1.3 million to "
     "10.8 billion cells, and which stage limits them; (2) to build a parallel terrain engine for the CPU and the "
     "GPU and measure where the bottleneck moves once computation is parallel; (3) to measure the slope and aspect "
     "error of every pyramid level against the time saved per view, on real high-resolution data; and (4) to "
     "build an interactive viewer and a QGIS plugin on these results and measure whether on-demand computation "
     "keeps up with continuous pan and zoom, first in a controlled experiment and then on a larger, independent "
     "lidar DEM on a second laptop."),
    ("p",
     "The contribution lies in the stage-by-stage measurement on one machine rather than in any single "
     "algorithm: the operators, tiling and pyramids used here are established. What is new is the separation of "
     "where time goes from the standard tools to a GPU engine, a measured error-against-time trade-off for "
     "derivatives computed from pyramid levels, and a viewer policy chosen from 1,068 measured runs."),

    # ------------------------------------------------------------------ 2 study area
    ("h1", "2. Study Area"),
    ("p",
     "Run time depends on the number of cells rather than on which mountain is processed, so all experiments use "
     "one study area and vary only the grid size. The area is NASA High Mountain Asia (HMA) tile-571 in the "
     "Garhwal Himalaya, Chamoli district, Uttarakhand (Figure 1a), between 79.125–80.235°E and 30.033–30.970°N, "
     "about 105 km × 103 km in UTM zone 44N. Elevations range from 674 m to 7,790 m, and the relief combines deep "
     "river valleys with glaciated ridges around the Nanda Devi massif (Figure 1b). Mean true slope is 31° over the "
     "8 m tile and 38° over the Chamoli sub-area, so the area is steeper than most landscapes, which matters for "
     "the slope errors reported later. Inside the tile lies the Chamoli (Rishiganga) sub-area, about 30 km × "
     "35 km, which is covered by a real 2 m DEM composite of pre-event imagery (September 2015) released after the "
     "February 2021 Chamoli disaster (Bhushan and Shean 2021). The same region was used in the pilot test of the team's literature review, "
     "which makes the earlier and the present measurements comparable."),
    ("fig", "figures/fig1_study_area.png",
     "**Figure 1.** Study area. (a) Location of the study tile (HMA tile-571, red box) in Uttarakhand (shaded), India; "
     "district boundaries from the course dataset. (b) Shaded relief of the 8 m DEM of the tile, with the Chamoli "
     "sub-area covered by the real 2 m DEM (orange box)."),

    # ------------------------------------------------------------------ 3 data and methods
    ("h1", "3. Data and Methods"),
    ("h2", "3.1 Elevation Data and Preparation"),
    ("p",
     "Six grids of the study area form a resolution ladder (Table 1). The 90 m and 30 m grids are Copernicus "
     "GLO-90 and GLO-30 tiles distributed by OpenTopography (European Space Agency 2021), the 8 m grid is the HMA "
     "8 m mosaic for tile-571 (Shean 2017), and the 2 m grid is the Chamoli composite (Bhushan and Shean 2021). No "
     "free 1 m DEM exists for this region, so the 2 m and 1 m grids of the whole tile were made by cubic upsampling "
     "of the 8 m mosaic. To test whether such grids are fit for timing, an 8 m crop of 16 million cells was rebuilt "
     "from a 16 m version of itself. It gave the same gdaldem run time as the real crop (0.87–0.90 s) but a slope "
     "RMSE of 2.3–3.0° against it, so synthetic grids were used for timing only and never for accuracy. Cubic "
     "resampling was chosen because nearest-neighbour data compressed 26% better than real terrain and would have "
     "made reads look faster than they are."),
    ("table", "**Table 1.** Resolution ladder of the study area. Real grids are used for timing and accuracy, "
              "synthetic grids for timing only.",
     ["Resolution", "Source", "Type", "Cells", "Valid", "Role"],
     [["90 m", "Copernicus GLO-90", "real", "1.3 M", "100%", "coarsest level"],
      ["30 m", "Copernicus GLO-30", "real", "12 M", "100%", "baseline level"],
      ["8 m", "HMA 8 m mosaic, tile-571", "real", "169 M", "84%", "finest real, whole tile"],
      ["2 m", "Chamoli 2 m composite", "real", "264 M", "94%", "accuracy truth (sub-area)"],
      ["2 m", "cubic upsample of 8 m", "synthetic", "2.7 B", "~89%", "timing only"],
      ["1 m", "cubic upsample of 8 m", "synthetic", "10.8 B", "~89%", "timing only (43 GB)"]],
     None),
    ("p",
     "All grids were reprojected with GDAL (GDAL/OGR contributors 2024) to WGS 84 / UTM zone 44N (EPSG:32644), so "
     "that cell sizes are true metres, on one aligned grid whose origin lies on a 360 m lattice divisible by every "
     "cell size. Each grid is stored as a Cloud-Optimized GeoTIFF (COG): 512 × 512 tiles, ZSTD compression and "
     "internal overviews built by averaging. The overviews form the pyramid: level k has a cell size of about 2ᵏ "
     "times the base cell (on the 2 m data, 4 m to 128 m). Downloads were checksum-verified. Where the 2 m and 8 m "
     "DEMs overlap, the 2 m DEM averaged to 8 m differs from the 8 m DEM by a median of −0.7 m with a normalised "
     "median absolute deviation of 5.1 m over 14 million cells. The 8 m DEM lies 24.5 m below Copernicus because "
     "HMA heights refer to the WGS 84 ellipsoid and Copernicus heights to the EGM2008 geoid; a near-constant offset "
     "does not affect slope, aspect or hillshade."),
    ("p",
     "For the validation in Section 4.5, a larger and independent dataset was added: swissALTI3D, the 2 m lidar "
     "terrain model of Switzerland (swisstopo 2024). 8,765 one-kilometre tiles over Valais and the Bernese Oberland "
     "(LV95 E 2555–2675 km, N 1075–1170 km; surveys 2019–2025) were merged into one COG with the same settings: "
     "60,000 × 47,500 = 2.85 billion cells, 77% valid (the rest lies outside Switzerland), elevations 366–4,634 m, "
     "5.6 GB, seven overview levels. This is about eleven times the cell count of the Chamoli grid."),

    ("h2", "3.2 Terrain Operators"),
    ("p",
     "All products are computed from the 3 × 3 window around each cell. With the window labelled a, b, c in the "
     "top row, d, e, f in the middle and g, h, i in the bottom row, and cell sizes Δx and Δy, Horn's (1981) "
     "gradients are"),
    ("eq", "horn_x", 1),
    ("eq", "horn_y", 2),
    ("p", "and slope θ follows from the gradient magnitude:"),
    ("eq", "slope", 3),
    ("p",
     "Aspect is the direction of the same gradient vector and hillshade combines both with a sun azimuth and "
     "altitude. Ten gdaldem configurations were used: slope, aspect and hillshade with the Horn and the "
     "Zevenbergen–Thorne (1987) methods, the terrain ruggedness index after Riley et al. (1999) and Wilson et al. "
     "(2007), the topographic position index and roughness."),

    ("h2", "3.3 Benchmark Harness and Protocol"),
    ("p",
     "All timing experiments ran on one laptop: an Intel Core Ultra 9 185H (6 performance, 8 efficiency and 2 "
     "low-power cores, 22 threads), 16 GB of RAM, an NVMe SSD and an NVIDIA RTX 4060 Laptop GPU with 8 GiB, under "
     "Windows 11, with GDAL 3.13.3 and QGIS 3.44.14 (QGIS Development Team 2024) as the baseline. Each measurement "
     "ran one tool as a separate process, and the harness recorded that process's wall time, peak memory, CPU "
     "time and bytes read and written; CPU time divided by wall time gives the number of threads in use. Before "
     "every cold run the operating system's file cache was emptied and the full re-read of the file was verified. "
     "Real grids were run five times cold and five times warm after one warm-up, the synthetic grids three times "
     "cold and once warm, and medians are reported; the median interquartile range of all configurations was "
     "1.2–1.6% of the median. gdaldem runs 1.7 times slower on an efficiency core, and the scheduler moved one "
     "unpinned run between core types so that it took 108.9 s instead of about 56 s, so all tools were pinned to "
     "the 12 performance-core threads. Background scanning of the 10–40 GB temporary outputs slowed later runs by "
     "25–35%, so only the scratch folders were excluded from scanning and every final number was re-measured."),
    ("p",
     "For each grid, two reference runs split a gdaldem run into stages: a pure read and decompress of every "
     "block, and a copy to an uncompressed GeoTIFF of the same size. Writing was then estimated as copy minus "
     "read, and computation as gdaldem minus copy. If computation takes a share p of a run, Amdahl's bound limits "
     "the speed-up from making computation faster to"),
    ("eq", "amdahl", 4),
    ("p", "The six experiments are summarised in Table 2."),
    ("table", "**Table 2.** The six experiments. E5 runs inside one long-lived process, as a viewer's server would; "
              "the others run every measurement as a separate process.",
     ["ID", "Question", "What was varied", "Runs"],
     [["E1", "How does gdaldem scale?", "10 operator configurations, 6 grids, cold and warm cache", "560"],
      ["E2", "Does storage layout matter?", "7 layouts: strips or tiles, 256 or 512, four compressions", "224"],
      ["QGIS", "What limits display?", "whole area or zoomed in, with or without pyramid, 3 grids", "48"],
      ["E3", "How fast is a parallel CPU engine?", "threads, operators, fused products, window size", "501"],
      ["E4", "When does the GPU help?", "kernel versions, precision, windows, reader threads", "484"],
      ["E5", "Error against time on the pyramid", "every pyramid level of two real DEMs, three routes", "in-process"],
      ["E6", "Does the viewer keep up?", "24 configurations × 17 interaction traces", "1,068"]],
     None),

    ("h2", "3.4 Terrain Engine for the CPU and the GPU"),
    ("p",
     "The engine processes a grid in 2048 × 2048-cell windows, each read with a one-cell border (halo) so that the "
     "3 × 3 operators are exact at window edges. Three stages overlap: four reader threads, each with its own GDAL "
     "handle and at most six windows in flight so that memory stays bounded; the compute kernel, compiled with "
     "Numba (Lam et al. 2015) and spread over all cores; and one writer thread, since GDAL advises against "
     "writing from several threads. Slope, aspect and hillshade can be computed in one fused pass because they "
     "share the gradient. The GPU engine replaces only the compute stage: each window is copied into a "
     "page-locked host buffer, sent to the GPU, processed by our own CUDA kernels compiled at run time through "
     "CuPy (Okuta et al. 2017), and copied back, with two streams so that the copies of one window overlap the "
     "kernel of the next. Arithmetic is float32, as in GDAL. The engine reproduces all ten gdaldem configurations, "
     "and a full-grid check compared both engines with gdaldem on every cell of the 90 m, 30 m, 8 m and 2 m real "
     "grids; once gdaldem's float32 summation of the Horn neighbours was reproduced, every cell matched."),

    ("h2", "3.5 Derivatives on Demand from the Pyramid"),
    ("p",
     "E5 uses only the two real high-resolution DEMs: Chamoli 2 m (levels 1–6, 4 m to 128 m) and the HMA 8 m tile "
     "(levels 1–5, 16 m to 256 m). For each level, slope and aspect were computed on demand from the level-k "
     "DEM with that level's cell size. The reference is what a screen pixel of that size should show: slope "
     "computed at full resolution and averaged over exactly the fine cells that each coarse cell covers (the "
     "circular mean for aspect). GDAL halves each level and rounds down, so footprints were taken from geometry, "
     "and every measurement was repeated on an exact power-of-two pyramid. Only cells whose footprint and "
     "neighbours contain no missing data were scored, from 61 million cells at 4 m down to 51 thousand at 128 m on "
     "Chamoli. With sᵢ the slope shown in coarse cell i and s̄ᵢ the averaged full-resolution slope, the error at "
     "a level is"),
    ("eq", "rmse", 5),
    ("p",
     "and the bias is the mean of sᵢ − s̄ᵢ. Time was measured for three ways of serving one 512 × 512 display tile "
     "at level k, at eight random places per level: on demand (read the tile from level k with a halo and "
     "compute), full resolution (read the same ground at full resolution, compute and average, the exact answer "
     "without precomputation), and precomputed (read the tile from a slope pyramid built in advance)."),

    ("h2", "3.6 Interactive Viewer and its Evaluation"),
    ("p",
     "The viewer system has four parts. The tile engine renders a fixed 512 × 512 tile lattice per pyramid "
     "level, aligned to the COG blocks, with single-threaded Numba kernels that release Python's interpreter "
     "lock, so tiles run in parallel; decoded blocks are cached in a 1 GiB cache and shared by neighbouring tiles, "
     "and encoded tiles in a 512 MiB cache. A scheduler keeps visible (foreground) and prefetch (background) "
     "queues, places foreground work on the performance cores and prefetch on the efficiency cores, merges "
     "identical requests and cancels work superseded by a newer view. A FastAPI server exposes tiles, a "
     "whole-map overview and a box endpoint that returns a GeoTIFF. A browser viewer draws the tiles of the "
     "level whose cell best matches one screen pixel, chosen as"),
    ("eq", "level", 6),
    ("p",
     "where rₖ is the cell size of level k and m the metres per screen pixel. Zoom commits once after a trailing "
     "debounce, panning requests tiles at once, and after each commit the eight neighbouring views are prefetched "
     "in the direction of travel first. A QGIS plugin sends a box drawn on the map to the same server and adds the "
     "result as a styled layer; a full-resolution slope box was identical to gdaldem's slope (1.22 million cells, "
     "maximum difference 0)."),
    ("p",
     "E6 replayed 17 seeded interaction traces (straight and reversing pans at three speeds, a random walk, "
     "smooth and notched mouse-wheel zoom bursts, alternating zoom and pan, and nested box zooms) in real time "
     "against a fresh server, through a Python port of the viewer's policy with a browser's limit of six "
     "connections. Each of 24 configurations ran one warm-up and five measured runs per trace on the Chamoli 2 m "
     "DEM. Two gates were fixed in advance: prefetching must not raise the 95th-percentile (p95) latency of visible "
     "tiles by more than 10%, and the zoom debounce must reduce the tiles the server renders per gesture while the "
     "first frame arrives within 100 ms of the debounce. Three traces were replayed in headless Chrome to check the "
     "simulated client."),
    ("p",
     "The validation sessions of Section 4.5 used the swissALTI3D grid on a second laptop (AMD Ryzen 7 7840HS, 16 "
     "threads, 14 GiB, NVMe SSD, NVIDIA RTX 4050 Laptop GPU and an AMD Radeon 780M integrated GPU that drives the "
     "display; Linux, QGIS 4.2). Seven hand-driven sessions used the web viewer, the QGIS plugin or both. The "
     "server logged every request with its stage timings, its own memory and cache counters every 2 s, and a "
     "separate sampler recorded CPU use per core, both GPUs, memory and disk once a second."),

    # ------------------------------------------------------------------ 4 results
    ("h1", "4. Results"),
    ("h2", "4.1 Where Standard Tools Stop Being Practical"),
    ("p",
     "gdaldem's run time grew linearly with the number of cells (Figure 2a): one slope pass took 4.0 s at 8 m, "
     "53.7 s on the 2 m synthetic grid and 208 s at 1 m, about 19–25 ns per cell once program start-up stopped "
     "mattering. Peak memory levelled off at 0.87 GB, so 43 GB of input were processed without any memory "
     "problem. The tool used 0.99 of 22 available threads, and the stage split showed that about 73% of every "
     "large run was this single-threaded computation, 14–15% reading and decompressing and 11–14% writing "
     "(Table 3). Cold and warm cache differed by 2% or less. Enabling GDAL's parallel decompression made gdaldem "
     "2–4% slower, because decompression is only a small share of its time, so the default configuration was also "
     "its fastest."),
    ("table", "**Table 3.** Slope (Horn) on the resolution ladder: gdaldem, the CPU engine on the same 12 threads and "
              "the GPU engine (warm cache, medians), with gdaldem's stage shares.",
     ["Grid", "Cells", "gdaldem", "Compute share", "CPU engine", "GPU engine", "GPU vs gdaldem"],
     [["8 m", "169 M", "4.02 s", "71%", "1.94 s", "1.90 s", "2.1×"],
      ["2 m real", "264 M", "6.63 s", "74%", "2.53 s", "2.18 s", "3.0×"],
      ["2 m synthetic", "2.7 B", "53.7 s", "74%", "16.3 s", "11.3 s", "4.7×"],
      ["1 m synthetic", "10.8 B", "208.4 s", "73%", "60.3 s", "43.8 s", "4.75×"]],
     None),
    ("p",
     "Storage layout (E2) changed gdaldem's time by up to about 40%, because decompression runs inside its single "
     "thread: on the 2 m synthetic grid LZW compression made slope 39% slower than uncompressed strips and ZSTD "
     "only 14%. ZSTD was 2.9 times smaller than uncompressed and decoded 2.6 times faster than LZW, which is why it "
     "was used for all COGs. For display, QGIS drew one 1920 × 1080 view of the whole area in 0.09 s with the "
     "pyramid at every resolution, but 31.9 s without it at 1 m, because it then read the full-resolution level, "
     "about 12.7 GB. A zoomed-in view read only its window and took about 0.1 s either way."),
    ("fig", "figures/fig2_scaling_crossover.png",
     "**Figure 2.** (a) gdaldem run time against grid size (warm cache): slope, hillshade and the two reference runs "
     "used for the stage split. (b) One slope window held in memory: CPU kernel on 12 threads against the GPU with "
     "and without the copies to and from the GPU."),

    ("h2", "4.2 Parallel Computation on the CPU and the GPU"),
    ("p",
     "The CPU engine was 2.1–3.5 times faster than gdaldem on the same cores, with the gain growing with grid "
     "size (Table 3): 60.3 s against 208.4 s at 1 m, about 5.6 ns per cell. Its memory stayed flat at about 1.4 GB "
     "at every size. Twelve performance-core threads beat all 22 threads (60 s against 68 s at 1 m), because the "
     "work is split evenly and the slower cores hold the others up. A naive program that loads the whole grid "
     "into memory needed about 24 bytes per cell and failed on the 2 m synthetic grid, so on 16 GB whole-grid "
     "processing stops working at roughly 0.5–0.7 billion cells, whereas streaming tools have no such limit. The "
     "speed came from the compiled parallel kernel rather than from tiling alone: the same pipeline with a "
     "single-threaded NumPy kernel was 2.6–3 times slower than gdaldem. Computing slope, aspect and hillshade in "
     "one fused pass took 134.8 s at 1 m, against more than 367 s for three gdaldem runs."),
    ("p",
     "Once computation was parallel, the run became limited by moving data. At 1 m the kernel needed 33 s while the "
     "writer thread was busy for 65 s writing 43 GB; without output the run waited 23 s for windows to be "
     "decompressed. Decompression, not the disk, limited reading: with no output, eight reader threads instead of "
     "four cut the read wait on the 2 m synthetic grid from 5.8 s to 1.2 s. Window size also mattered, because the "
     "halo of a window w cells wide forces (w/512 + 2)² stored tiles to be decoded instead of (w/512)²: nine times "
     "the work at 512 cells and 2.25 times at 2048, which made 2048 the best size."),
    ("p",
     "The GPU kernel computed slope for the whole 10.8-billion-cell grid in 1.1 s, against 34 s for the CPU "
     "kernel, about 50 times faster, yet a whole run was only 1.0–1.4 times faster than the CPU engine (43.8 s "
     "against 60.3 s at 1 m; Table 3). Figure 2b shows why: for a 2048 × 2048 window the kernel took 0.18 ms and "
     "kernel plus copies 3.85 ms, so copying over PCIe was 95% of the GPU's own time. Including copies, the GPU "
     "was 2.2–2.4 times faster than the CPU kernel for windows of 1024² cells and above, only 1.3 times at 512², and "
     "slower below 512². How the GPU was used mattered more than the GPU itself: a direct port of the NumPy code to "
     "CuPy took 17.0 s on the 2 m synthetic grid, slower than the CPU engine, and our own kernel, page-locked "
     "buffers and two streams brought it to 11.3 s. Three fused products gained most (81.4 s at 1 m against 134.8 s "
     "on the CPU). With the kernel almost free, the main thread at 1 m spent 25.7 s waiting for decompressed input; "
     "eight readers cut that wait to 3.2 s, but writing then became the limit and the total only fell from 43.8 s "
     "to 42.6 s (Figure 3)."),
    ("fig", "figures/fig3_stages.png",
     "**Figure 3.** Where the time goes for slope (warm cache) at four grid sizes: gdaldem from the stage split, and "
     "the CPU and GPU engines from their own stage timings. Computation shrinks from gdaldem to the engines, while "
     "reading, copying and writing remain."),

    ("h2", "4.3 Error and Time of Derivatives from the Pyramid"),
    ("p",
     "Slope computed from a coarser pyramid level was systematically too low, and more so the coarser the level "
     "(Table 4, Figure 4a). On Chamoli the RMSE grew from 2.3° at 4 m to 6.4° at 32 m and 10.0° at 128 m, and the "
     "mean slope shown fell from 99% to 81% of the true mean. What mattered was the number of levels above the base "
     "rather than the cell size in metres: the two DEMs gave errors within 0.5° of each other for the same number "
     "of levels up to four levels, roughly 2.5° one level up and about 1.5° more per further level. GDAL's "
     "overviews behaved like an exact power-of-two pyramid, within 0.2° RMSE at every level."),
    ("table", "**Table 4.** Slope computed on demand from each pyramid level of the Chamoli 2 m DEM against the "
              "averaged full-resolution truth, and time for one 512 × 512 tile (warm, median of eight places).",
     ["Level", "Cells scored", "RMSE", "Bias", "≥45° shown / truth", "On demand", "Full resolution",
      "Time saved"],
     [["4 m", "61.4 M", "2.3°", "−0.5°", "32.1 / 33.2%", "7.2 ms", "56 ms", "7.8×"],
      ["8 m", "15.2 M", "4.4°", "−1.2°", "29.2 / 32.3%", "6.4 ms", "192 ms", "30×"],
      ["16 m", "3.7 M", "5.6°", "−2.2°", "25.7 / 30.8%", "6.6 ms", "624 ms", "94×"],
      ["32 m", "0.91 M", "6.4°", "−3.3°", "21.9 / 29.3%", "6.4 ms", "2,867 ms", "447×"],
      ["64 m", "0.22 M", "7.9°", "−5.0°", "16.5 / 28.4%", "–", "–", "–"],
      ["128 m", "51 k", "10.0°", "−7.3°", "10.1 / 27.4%", "–", "–", "–"]],
     "Timing was measured up to four levels above the base; at 64 m and 128 m only the error was evaluated."),
    ("p",
     "Steep ground lost the most. At 32 m the bias was −0.9° on slopes of 0–10° but −4.0° on slopes of 40–50°, and "
     "36% of the 40–50° cells were off by more than 5°, against 10% of flat cells. Thresholds therefore shift: one "
     "level up, a map of slopes at or above 45° was still 97% the same, but four levels up a quarter of the terrain "
     "above 45° had disappeared (29.3% to 21.9%), and six levels up almost two thirds (27.4% to 10.1%). Aspect "
     "survived much better, with a median error of 1.8° at 4 m, 6.3° at 32 m and 8.5° at 128 m, and at most 13.7% "
     "of cells off by more than one 16-point compass sector. Over the Chamoli footprint, the 2 m data averaged to "
     "8 m, 30 m or 90 m was always closer to the 2 m truth (slope RMSE 4.5°, 6.3° and 8.7°) than independent DEMs "
     "of the same cell size (HMA 8 m 8.6°, Copernicus 30 m 9.4°, Copernicus 90 m 9.9°)."),
    ("p",
     "The time per tile hardly changed with the level (Table 4, Figure 4b). Computed on demand, a tile took 5–8 ms "
     "at every zoom, because it always means reading 514 × 514 cells and running the kernel on them, while the "
     "exact full-resolution route read four times more ground per level and reached 2.9 s for one tile at 32 m. "
     "Each level up therefore saved 2–5 times in time: 7.8–447 times per tile for one to four levels on Chamoli "
     "and 7.6–193 times on the 8 m DEM. Cold and warm cache differed by at most 1.5 ms. A precomputed slope pyramid "
     "was 1.3–3.0 ms faster per tile but cost a full pass per product: 10.6 s and 1,005 MB for Chamoli, 1.5 times "
     "the elevation pyramid itself, to be rebuilt whenever a parameter or the DEM changes."),
    ("fig", "figures/fig4_pyramid.png",
     "**Figure 4.** (a) Slope RMSE and underestimate (negative bias) per pyramid level for the Chamoli 2 m and HMA "
     "8 m DEMs. (b) Time for one 512 × 512 slope tile per pyramid level on Chamoli: on demand, full resolution then "
     "averaged, and precomputed, for warm and cold cache."),

    ("h2", "4.4 Interactive Viewing"),
    ("p",
     "On-demand computation kept up with continuous viewing (Table 5). After a zoom gesture the first exact tile "
     "arrived 57–89 ms after the commit and the whole view 76–158 ms after it; after a box zoom the first exact "
     "tile appeared 64 ms after the animation ended and the whole view after 127 ms. The server never needed more "
     "than 982 MiB in these runs. Without a debounce, every wheel tick committed a new view (up to 121 times in a "
     "2 s burst) and the server rendered a median of 62 foreground tiles per gesture; with a trailing debounce it "
     "rendered 19, 3.3 times fewer, and the first exact tile followed 63–71 ms after the debounce fired, so the "
     "second gate passed (Figure 5a). Smooth 60 Hz bursts could not separate debounce values from 100 to 250 ms, "
     "but a notched mouse wheel could: at 100 ms the viewer committed between notches and rendered 36 tiles, as "
     "many as without a debounce, while 150 ms and longer coalesced the gesture into 15. Because 200 ms only added "
     "40–50 ms of delay, 150 ms became the default."),
    ("table", "**Table 5.** Main viewer results (E6, medians over five runs per trace; Chamoli 2 m DEM).",
     ["Measure", "Without the policy", "With the policy"],
     [["Server tiles per zoom gesture, 60 Hz bursts", "62 (no debounce)", "19 (debounce)"],
      ["Server tiles per gesture, notched wheel 30–150 ms", "36 (100 ms)", "15 (150 ms)"],
      ["First exact tile after the debounce", "–", "63–71 ms"],
      ["Tiles already cached when panned into view", "0% straight, ~50% reversing", "98–100%"],
      ["Foreground requests per pan", "36–202", "0–5"],
      ["Visible-tile p95 on identical tiles, server / client", "95 / 138 ms (prefetch off)",
       "90 / 129 ms (prefetch on)"],
      ["Blocks decoded on mixed traces", "1,128 (no block cache)", "185 (1 GiB cache)"]],
     None),
    ("p",
     "Prefetching made panning seamless: with it, 98–100% of the tiles entering the view during a pan were already "
     "in the browser at every pan speed, and the pans needed 0–5 foreground requests instead of 36–202 (Figure 5b). "
     "Without it, the hit rate was 0% on a straight pan and about 50% on a pan that turned back. The cost was "
     "precision: the ring of eight neighbouring views fetched 2–5 tiles for every tile used (precision 0.20–0.56). "
     "Loading the direction of travel first kept the hit rate at 0.99 at two view widths per second, against 0.91 "
     "in a fixed order. The first gate was tested like for like on the box trace, where the visible tiles are "
     "identical with and without prefetch: server p95 was 90 ms with prefetch and 95 ms without, and client p95 129 "
     "against 138 ms, so prefetch did not slow the visible tiles and the gate passed. Only 3% of visible tiles were "
     "ever requested while a prefetch request was in flight, and all 122,215 prefetch jobs ran on efficiency cores."),
    ("p",
     "The remaining latency came from the browser and from decoding. Clients saw about 40 ms more than the server "
     "at p95, because tiles waited for one of six connections, and 4, 6 or 8 server workers gave the same client "
     "latency. Without the decoded-block cache the server decoded six times more blocks and client p95 rose 40%. "
     "Flushing the operating system's file cache changed nothing, and the product, the 8 m DEM and slope or aspect "
     "instead of hillshade changed latency by about 10% at most. Replayed in real headless Chrome, three traces "
     "gave the same commits and requests as the simulated client and view-complete times within 10%, so the "
     "simulated latencies are slight upper bounds."),
    ("fig", "figures/fig5_viewer.png",
     "**Figure 5.** (a) Zoom bursts: foreground tiles the server renders per gesture and the time from the last "
     "wheel tick to the first exact tile, against the debounce. (b) Share of tiles already cached in the browser when "
     "they enter the view, by pan speed and prefetch policy."),

    ("h2", "4.5 Validation on a 2.85-Billion-Cell Lidar DEM"),
    ("p",
     "The seven sessions on the swissALTI3D grid served about 18,000 web-viewer tiles and drew 125 boxes in QGIS "
     "(Table 6). In the default mode, which computes from the pyramid level, tiles took a median of 6.9–14.1 ms "
     "per session, and a full view on a 625-million-cell part of the same data loaded in 91 ms, within the 76–158 ms "
     "range of E6 on a dataset eleven times smaller. Decompression accounted for 52–55% of a tile read from disk, as "
     "in E5. Of the 125 QGIS boxes, 122 succeeded at the level matching the box on screen, in 10–225 ms for "
     "ordinary boxes and 3.2–4.4 s for full-resolution boxes near the 64-million-cell limit; the three refusals were "
     "boxes over that limit. The tile server used a median of 0.01–0.02 cores in this mode. In a nine-minute session "
     "using both tools, QGIS took 62% of all CPU time while redrawing layers, the server 22% and the browser 4%. "
     "The NVIDIA GPU was never used by the system, and the integrated GPU stayed almost always at its lowest clock."),
    ("table", "**Table 6.** Validation sessions on the swissALTI3D 2 m DEM (2.85 billion cells) on a second laptop.",
     ["Measure", "Result"],
     [["Sessions", "7 (3 web viewer, 2 QGIS, 2 both), 2.2–9.1 min"],
      ["Tile time in the default mode (median per session)", "6.9–14.1 ms"],
      ["Decompression share of a tile read from disk", "52–55%"],
      ["QGIS boxes accepted / drawn", "122 / 125 (3 over the size limit)"],
      ["Server memory without / with Exact work", "1.9–2.3 GB / 2.9–3.9 GB"],
      ["Exact whole-map overview", "47–129 s on one core"],
      ["CPU share in a mixed session (QGIS / server / browser)", "62% / 22% / 4%"],
      ["NVIDIA GPU use by the system", "0%"]],
     None),
    ("p",
     "The sessions also exposed a limitation that E6 did not test. In the exact mode, which computes every view from "
     "full-resolution cells, the whole-map overview covered all 2.85 billion cells on one thread and took 47–129 s, "
     "during which the viewer issued no new tile requests for up to 36 s in one session. When the sun direction "
     "was changed in this mode, each new direction started a new overview, and superseded overviews were not "
     "cancelled: eight ran to completion, up to six at once. Server memory, 1.9–2.3 GB without exact work and so at "
     "the planned budget of about 2.2 GB, rose to 2.9–3.6 GB with one to three exact overviews and 3.9 GB with six at once, and "
     "stayed at 2.2–3.0 GB for several minutes afterwards in two sessions (Figure 6). A single exact box in QGIS "
     "was slow (17–99 s) but stayed within memory, and other boxes kept returning in 20–40 ms meanwhile."),
    ("fig", "figures/fig6_swiss_run4.png",
     "**Figure 6.** One validation session on the swissALTI3D grid (7.3 min). Top: CPU cores used by the tile server "
     "and the browser. Bottom: server memory and its two caches; dotted line, the planned budget of about 2.2 GB. "
     "Grey bands mark exact-mode work, including six whole-map overviews running at once."),

    # ------------------------------------------------------------------ 5 discussion
    ("h1", "5. Discussion"),
    ("p",
     "The measurements point to one pattern: arithmetic is never the limit for long. gdaldem is limited by "
     "computation only because it computes on one thread. Its 73% compute share bounds the speed-up from parallel "
     "computation at about 3.7 times by Amdahl's law (Equation 4), and the CPU engine reached 3.5 times. After "
     "that, decompression and writing limit whole-grid runs, and the GPU, which removes computation almost "
     "entirely, adds PCIe copies to the same two costs. This agrees with Sanchez-Fernandez et al. (2021), who found "
     "that the layout of the data in memory mattered more than the number of GPUs, and with Barnes (2016), whose "
     "tiled design treats moving data as the central problem. It differs from the common reading that the disk "
     "is the slow part: on an NVMe SSD a flushed file cache changed run times by at most 2%, and reading was "
     "limited by decompression in the CPU. The pilot of the literature review, which saw caching triple the run "
     "time at 5 m, was timed through the QGIS interface on a different laptop and probably included one-off "
     "start-up costs."),
    ("p",
     "The GPU results also qualify the large speed-ups reported in earlier work. Yu et al. (2024) reported about 29 "
     "times for neighbourhood operations coordinated across CPU and GPU, and our kernel alone was about 50 times "
     "faster than the CPU kernel, yet whole runs were 1.0–1.4 times faster. The difference lies in what is counted: "
     "a kernel-to-kernel comparison leaves out the copies and the input and output that a complete run cannot "
     "avoid. Our crossover measurements give a practical rule in line with their finding that the CPU and the GPU "
     "suit different parts of the work: below 512 × 512 cells the CPU is faster, and the GPU pays off for large "
     "windows and fused products, or for results that stay in memory. A direct port of array code to the GPU was "
     "slower than the CPU engine, so the gain depends on writing kernels for the device rather than on the device "
     "itself."),
    ("p",
     "For display, the results support the pyramid approach of Losasso and Hoppe (2004) and Campos et al. (2020) "
     "and extend it from elevation to derived products computed on demand. Because each tile at the level that "
     "matches the screen reads the same number of cells, the time per view stays at a few milliseconds at every "
     "zoom, and the whole cost of a new product or sun angle is computing it for the cells in view. Precomputed "
     "products, as used for global layers by Amatulli et al. (2020) and Ho et al. (2025), are exact and slightly "
     "faster per tile, but each costs a full pass and storage of about 1.5 times the elevation pyramid on our data. "
     "The trade-off is an error that is now quantified. The decrease of slope with cell size reported by Zhang and "
     "Montgomery (1994) appears here level by level, and its concentration on steep ground is consistent with Deng "
     "et al. (2007), who found the change depends on landform position. That a pyramid level of the 2 m data was "
     "closer to the truth than independent DEMs of the same cell size supports the argument of Polidori and El Hage "
     "(2020) that source quality matters as much as nominal resolution, and the roughly logarithmic growth of "
     "the error with the number of levels resembles the dependence on grid spacing reported by Guth and Kane (2021)."),
    ("p",
     "These numbers have practical consequences. For viewing, a slope map from the level whose cell is about one "
     "screen pixel keeps every valley and ridge, and its expected error can be shown beside it. For analysis that "
     "thresholds slope, such as landslide susceptibility, a coarse level is not acceptable: four levels up a "
     "quarter of the terrain steeper than 45° disappears. Such work should read full-resolution data or a "
     "precomputed slope pyramid. The viewer offers both an approximate and an exact mode for this reason."),
    ("p",
     "The viewer results show where interactive latency comes from once computation is cheap. Debouncing and "
     "prefetching follow from the same principle as the pyramid: compute only what the user will see. The debounce "
     "removes work for views the user never stops at, and prefetch spends idle efficiency-core time on views the "
     "user is likely to reach. Neither slowed the visible tiles, because prefetch yields to foreground work and "
     "runs on other cores. What remained was the browser's limit of six connections and the decoding of compressed "
     "blocks, which a shared block cache reduced six-fold. The validation on a second laptop and a dataset eleven "
     "times larger reproduced the per-tile cost and the decoding share, which suggests that the design depends on "
     "the size of a tile rather than the size of the dataset."),
    ("p",
     "The validation also showed that the clients, not the server, used most of the CPU in ordinary use, and that "
     "the exact mode breaks this design on large data. An exact whole-map overview has to read every cell of the "
     "dataset, which contradicts the rule that a view should cost the same at every zoom. Two fixes follow directly: "
     "always build the overview from its own pyramid level, and cancel superseded overview requests as tiles are "
     "already cancelled. The memory that stayed high after exact work is likely held by the process for reuse rather "
     "than lost, since it did not grow without bound, but this was not verified."),

    # ------------------------------------------------------------------ 6 limitations
    ("h1", "6. Limitations and Future Scope"),
    ("p",
     "All controlled timings come from one laptop with a local NVMe SSD, so ratios such as speed-ups and stage "
     "shares transfer better than absolute times; a network-hosted COG would add latency to every request. The "
     "1 m and whole-tile 2 m grids are synthetic and were used only for timing, because no free 1 m DEM exists "
     "for the region. Accuracy was measured in one region of steep terrain, where pyramid errors are larger than "
     "they would be in flatter landscapes, and the reference is itself a DEM with its own errors. Only GDAL and "
     "QGIS served as the baseline. E6 covered one client with short scripted traces from a cold server, so caches "
     "never filled; the validation sessions filled them but were hand-driven, of different lengths and on a "
     "different laptop, and core pinning was not active there. The viewer runs on the CPU only, so the GPU's "
     "behaviour for display tiles is predicted from the crossover measurements rather than measured end to end. "
     "The simulated client was checked against a real browser on only three traces, and a QGIS drawing baseline "
     "for the same boxes as the plugin was planned but not run. The exact mode was not part of E6, so its cost on "
     "large data is known only from the hand-driven sessions, and the cause of the memory that stayed high after "
     "exact work was not established."),
    ("p",
     "Several directions follow. The exact-mode overview should be built from its own level and superseded "
     "requests cancelled. Decompression could move to the GPU, so that compressed blocks cross PCIe (2.2–2.6 times "
     "fewer bytes on our data) and decoding leaves the CPU; from the E4 crossover we estimate up to about 1.4 times "
     "on the GPU stage, while runs that write to disk would stay limited by writing. A per-level correction factor "
     "could remove most of the slope bias, though not its spread. Longer sessions with several clients would "
     "measure the result cache and returning users. Finally, the third gap remains open: the accuracy of the "
     "approximate XDraw viewshed against the exact method (Cauchi-Saunders and Lewis 2015; Dou et al. 2019) and of "
     "A* against Dijkstra for terrain distance (Hart et al. 1968) in high-relief terrain."),

    # ------------------------------------------------------------------ 7 conclusions
    ("h1", "7. Conclusions"),
    ("p",
     "Standard terrain tools do not fail on a 16 GB laptop even at 10.8 billion cells; they become slow. gdaldem "
     "streams 43 GB in 0.87 GB of memory but computes on one thread, and QGIS without a pyramid reads "
     "full-resolution data for every whole-area redraw. A tiled engine with a compiled parallel kernel removes the "
     "computation limit, 2.1–3.5 times faster with identical results, and the GPU reduces computation further, but "
     "then decompression, copying and writing set the run time, so the GPU gains only 1.0–1.4 times over the CPU "
     "engine. On a laptop the limit is moving and decoding data, not arithmetic."),
    ("p",
     "The way past that limit is to read and compute less. Derivatives computed on demand from the pyramid level "
     "that matches the screen cost 5–8 ms per tile at every zoom, 8–450 times less than an exact computation, with "
     "a measured slope underestimate of about 2.5° one level up and 1.5° more per further level, largest on steep "
     "ground. A viewer built on this, with a 150 ms zoom debounce and direction-aware prefetch, keeps up with "
     "continuous pan and zoom and held on a 2.85-billion-cell lidar DEM on a second laptop. For thresholds and "
     "hazard maps, slope should still come from full-resolution data, and an exact overview of a very large DEM "
     "remains the case the design does not yet handle."),

    # ------------------------------------------------------------------ acknowledgements
    ("h1u", "Acknowledgements"),
    ("p",
     "We thank the course instructor for the guidance that shaped the project. Elevation data were provided by "
     "NASA's National Snow and Ice Data Center (High Mountain Asia 8 m DEM mosaics), by S. Bhushan and D. Shean "
     "through Zenodo (Chamoli 2 m composite), by the European Space Agency and OpenTopography (Copernicus GLO-30 "
     "and GLO-90, produced using Copernicus WorldDEM-30 © DLR e.V. 2010–2014 and © Airbus Defence and Space GmbH "
     "2014–2018), and by the Federal Office of Topography swisstopo (swissALTI3D © swisstopo). The work used the "
     "open-source GDAL, QGIS, Numba, CuPy and FastAPI projects."),

    # ------------------------------------------------------------------ references
    ("h1u", "References"),
    ("ref", "Amatulli G, McInerney D, Sethi T, Strobl P, Domisch S (2020) Geomorpho90m, empirical evaluation and "
            "accuracy assessment of global high-resolution geomorphometric layers. Sci Data 7:162"),
    ("ref", "Barnes R (2016) Parallel Priority-Flood depression filling for trillion cell digital elevation models "
            "on desktops or clusters. Comput Geosci 96:56–68"),
    ("ref", "Bhushan S, Shean D (2021) Chamoli Disaster Pre-event 2-m DEM Composite: September 2015. Zenodo. "
            "https://doi.org/10.5281/zenodo.4554647"),
    ("ref", "Campos R, Quintana J, Garcia R, Schmitt T, Spoelstra G, Schaap DMA (2020) 3D simplification methods "
            "and large scale terrain tiling. Remote Sens 12:437"),
    ("ref", "Cauchi-Saunders AJ, Lewis IJ (2015) GPU enabled XDraw viewshed analysis. J Parallel Distrib Comput "
            "84:87–93"),
    ("ref", "Deng Y, Wilson JP, Bauer BO (2007) DEM resolution dependencies of terrain attributes across a "
            "landscape. Int J Geogr Inf Sci 21:187–213"),
    ("ref", "Dou W, Li Y, Wang Y (2019) An equal-area triangulated partition method for parallel Xdraw viewshed "
            "analysis. Concurr Comput Pract Exp 31:e5216"),
    ("ref", "European Space Agency (2021) Copernicus Global Digital Elevation Model (GLO-30). Distributed by "
            "OpenTopography. https://doi.org/10.5069/G9028PQB"),
    ("ref", "GDAL/OGR contributors (2024) GDAL/OGR Geospatial Data Abstraction software Library. Open Source "
            "Geospatial Foundation. https://gdal.org"),
    ("ref", "Guth PL, Kane M (2021) Slope, aspect, and hillshade algorithms for non-square digital elevation "
            "models. Trans GIS 25:2309–2332"),
    ("ref", "Hart PE, Nilsson NJ, Raphael B (1968) A formal basis for the heuristic determination of minimum cost "
            "paths. IEEE Trans Syst Sci Cybern 4:100–107"),
    ("ref", "Ho Y-F, Grohmann CH, Lindsay J, Reuter HI, Parente L, Witjes M, Hengl T (2025) GEDTM30: Global "
            "ensemble digital terrain model at 30 m and derived multiscale terrain variables. PeerJ 13:e19673"),
    ("ref", "Horn BKP (1981) Hill shading and the reflectance map. Proc IEEE 69:14–47"),
    ("ref", "Lam SK, Pitrou A, Seibert S (2015) Numba: A LLVM-based Python JIT compiler. In: Proceedings of the "
            "Second Workshop on the LLVM Compiler Infrastructure in HPC, pp 1–6"),
    ("ref", "Losasso F, Hoppe H (2004) Geometry clipmaps: Terrain rendering using nested regular grids. ACM Trans "
            "Graph 23:769–776"),
    ("ref", "Okuta R, Unno Y, Nishino D, Hido S, Loomis C (2017) CuPy: A NumPy-compatible library for NVIDIA GPU "
            "calculations. In: Workshop on Machine Learning Systems (LearningSys), NIPS 2017"),
    ("ref", "Polidori L, El Hage M (2020) Digital elevation model quality assessment methods: A critical review. "
            "Remote Sens 12:3522"),
    ("ref", "QGIS Development Team (2024) QGIS Geographic Information System. Open Source Geospatial Foundation "
            "Project. https://qgis.org"),
    ("ref", "Riley SJ, DeGloria SD, Elliot R (1999) A terrain ruggedness index that quantifies topographic "
            "heterogeneity. Intermt J Sci 5:23–27"),
    ("ref", "Sanchez-Fernandez AJ, Romero LF, Bandera G, Tabik S (2021) A data relocation approach for terrain "
            "surface analysis on multi-GPU systems: A case study on the total viewshed problem. Int J Geogr Inf Sci "
            "35:1500–1520"),
    ("ref", "Shean D (2017) High Mountain Asia 8-meter DEM Mosaics Derived from Optical Imagery, Version 1. NASA "
            "National Snow and Ice Data Center DAAC. https://doi.org/10.5067/KXOVQ9L172S2"),
    ("ref", "swisstopo (2024) swissALTI3D: The high precision digital elevation model of Switzerland. Federal "
            "Office of Topography swisstopo. https://www.swisstopo.admin.ch/en/height-model-swissalti3d"),
    ("ref", "Trevisani S, Teza G, Guth PL (2023) Hacking the topographic ruggedness index. Geomorphology "
            "439:108838"),
    ("ref", "Wilson MFJ, O'Connell B, Brown C, Guinan JC, Grehan AJ (2007) Multiscale terrain analysis of "
            "multibeam bathymetry data for habitat mapping on the continental slope. Mar Geod 30:3–35"),
    ("ref", "Yu Z, Zhou C, Li M (2024) A parallel strategy to accelerate neighborhood operation for raster data "
            "coordinating CPU and GPU. Cartogr Geogr Inf Sci 51:813–829"),
    ("ref", "Zevenbergen LW, Thorne CR (1987) Quantitative analysis of land surface topography. Earth Surf Process "
            "Landf 12:47–56"),
    ("ref", "Zhang W, Montgomery DR (1994) Digital elevation model grid size, landscape representation, and "
            "hydrologic simulations. Water Resour Res 30:1019–1028"),
]
