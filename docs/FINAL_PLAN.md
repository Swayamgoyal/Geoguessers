# GeoGuessers: final plan (what is done, what is left)

This document replaces the Phase 5–7 part of `docs/PROJECT_PLAN.md` as the working plan to finish the project.
**Phase 0** summarises everything already completed. **Phases 1–6** are the work left, in order. Experiment IDs
(E1–E6) are unchanged.

The goals for the viewer come from the team's Phase 5 engineering spec, written after the professor's input
(`docs/PHASE5_DEBOUNCED_ZOOM_SPEC.md`, by Kartikeya). The internal architecture below follows that spec where it is
the best choice and differs where noted ("Our choice").

| This plan | Original plan (`PROJECT_PLAN.md`) |
|---|---|
| Phase 0: done | Phases 0–4 (setup, data, baseline E1/E2, engine E3/E4, pyramid E5), audit, reports, hand-off |
| Phases 1–4: tile engine, server, web viewer, QGIS plugin | Phase 5 (interactive viewer) |
| Phase 5: E6 benchmark and tuning | Phase 5 (E6) |
| Phase 6: final report, slides, demo | Phase 7 |
| Stretch | Phase 6 (viewshed, distance), Cesium globe, GPU tile path |

---

## Phase 0: what is done (and done properly)

Every result below was audited number by number against the raw data. Details:
`report/internal_report/main.pdf` (team), `report/prof_report`, `report/phase3_report`, `report/phase4_report`
(progress reports), `docs/PHASE2_RESULTS.md`, `PHASE3_RESULTS.md`, `PHASE3_GPU_RESULTS.md`, `PHASE4_RESULTS.md`.

| Area | Done | Key result |
|---|---|---|
| Setup | Miniforge env `geo` (GDAL 3.13.3, Numba, CuPy, FastAPI), QGIS 3.44, harness with exact per-process measurement, cold-cache flush, core pinning, Defender handling | Fair, repeatable measurements: median IQR 1.2–1.6% (`results/run_stats.md`) |
| Data | One Himalayan study area: real 90 / 30 / 8 m and 2 m (Chamoli), synthetic 2 m / 1 m (timing only); aligned UTM 44N COGs with pyramids | Up to 10.8 B cells, 43 GB, 2.6× RAM |
| E1/E2/QGIS (baseline) | 832 runs | gdaldem never runs out of memory but is single-threaded and compute-bound (73%); QGIS needs 32 s per redraw at 1 m without a pyramid, 0.09 s with one |
| E3 (CPU engine) | `demlab` pipeline (readers → Numba kernel → writer), all 10 gdaldem configurations, 501 runs | 2.1–3.5× faster than gdaldem on the same cores, memory flat at ~1.4 GB; naive whole-grid NumPy fails above ~0.5–0.7 B cells |
| E4 (GPU engine) | CUDA kernels, pinned memory, 2 streams, temperature guard, 484 runs + crossover test | Kernel 50× faster but the run only 1.0–1.4×: copies 95% of GPU time; the bottleneck moved to data movement |
| E5 (pyramid on demand) | Accuracy on every pyramid level of two real DEMs; tile timing for three routes | On-demand tile 5–8 ms at every level (8–450× cheaper than exact); slope too low by ~2.5° one level up, ~1.5° more per level |
| Correctness | 119 tests; every cell of the full 90 / 30 / 8 / 2 m grids vs gdaldem | All match; Horn differences are gdaldem's float32 rounding, reproduced exactly |
| Reports and hand-off | Phase 2, 3, 4 progress reports; 25-page internal report with presentation prep; GitHub up to date; verified copy on `K:\spatial project\GeoGuessers_handoff` | — |

**Not done yet:** the professor update (`docs/prof_update_phase2.md`, Phase 2 only) has not been sent.

What Phase 0 tells the viewer design (from the measurements, not assumptions):
- A 512² tile costs 5–8 ms on demand, of which the slope kernel is ~0.5 ms. **Decoding, not computing, is the cost.**
- Every pyramid level is stored in 512 × 512 compressed blocks. A 512² window with a 1-cell halo decodes up to
  **9 blocks**. A shared decoded-block cache can bring that to ~1 per tile.
- 12 performance-core threads beat all 22; efficiency cores are 1.7× slower and slow the foreground when mixed in.
- Exact (full-resolution) tiles cost up to 2.9 s at 32 m: never prefetch them.

---

## Goals for the remaining work (from the Phase 5 spec)

1. **Continuous pan and zoom** over a fixed 512² tile lattice per pyramid level (replaces box zoom as the main
   interaction; **box zoom stays** as Shift + drag and as `POST /view` for QGIS).
2. **Debounced zoom:** commit once, ~200 ms after the last wheel tick (150–250 ms configurable); during the gesture
   the screen shows existing tiles rescaled, never a blank area.
3. **Speculative neighbour prefetch:** after each commit, load the 8 neighbouring views at low priority, on the
   efficiency cores, cancelled as soon as the user moves elsewhere.
4. **Caching at every tier:** decoded blocks and rendered tiles on the server, bitmaps in the browser.
5. **Cancellation by generation:** work for a view the user has left is dropped within one processing stage.
6. **Bounded memory** on the 16 GB laptop (server ~2.2 GB budget).
7. **Exact mode** (full resolution) without prefetch; the expected error of the shown level (from E5) is displayed.
8. **E6** measures all of this with a scripted virtual client and two gates: prefetch raises foreground p95 by at
   most 10%; debouncing cuts server tiles per zoom gesture while the first frame arrives < 100 ms after the debounce.

---

## Architecture

```
 browser (viz/web, plain ES modules, canvas)            QGIS plugin (Shift-free box tool)
   camera ─ gestures (debounce) ─ tileLayer (fallback chain) ─ tileCache (bitmap LRU) ─ prefetch (3×3 ring)
        │ GET /tiles/{level}/{tx}/{ty}.png   headers: X-Session, X-Gen, X-Priority fg|bg
        ▼                                                      │ POST /view (box)
 FastAPI, one process (server/app.py) ─ /info /overview /tiles /session/{sid}/gen /prefetch /view /stats
        ▼
 scheduler (demlab/sched.py): fg queue → 8 workers on P-cores │ bg queue → 3 workers on E-cores
   single-flight per tile key · cancel tokens checked between stages · generation per session · memory guard
        ▼
 tile renderer (demlab/view.py): lattice → blocks (+halo) → kernel (nogil, 1 thread) → palette PNG
        ▼                                   ▼
 result cache (PNG, 512 MiB, SLRU)      block cache (decoded 512² blocks, 1024 MiB, SLRU)
                                            ▼
                                   COG pyramid on SSD (GDAL, thread-local handles)
```

| Part | Spec | Our choice |
|---|---|---|
| Request unit | 512² lattice tiles aligned to each level's own block grid | **Adopt.** All levels use 512 blocks (checked), so one tile = one stored block + its halo |
| Level choice | Finest level whose cell is ≤ one device pixel, ±10% hysteresis, real cell sizes (not 2^k) | **Adopt** |
| Kernels | Recompile existing kernels with `nogil=True` | **Differ:** add separate single-threaded `nogil` tile kernels; the parallel engine kernels stay untouched, so E3/E4 results remain reproducible |
| Tile encoding | PNG | **Differ:** 8-bit palette PNG (one byte per cell + palette, nodata transparent, fast zlib level). Smaller and faster to encode than RGBA |
| Block cache | Own cache before GDAL, segmented LRU | **Adopt:** our reader reads whole aligned blocks, caches them (all-nodata blocks as a 0-byte sentinel) and assembles windows |
| Result cache, single-flight | BLAKE2b key of the canonical tile spec | **Adopt** |
| Scheduler | Two priority queues, fg pool on P-cores, bg pool on E-cores, cancel tokens, promotion, backpressure | **Adopt**, pinning per thread with `SetThreadAffinityMask` |
| Server | FastAPI, one worker, disconnect watch, `Server-Timing` | **Adopt** |
| GPU in the viewer | Optional fg dispatcher | **Stretch:** a 512² tile is exactly the CPU/GPU crossover (E4), so the GPU gains little per tile |
| Frontend | Canvas, camera/gestures/tileLayer/tileCache/prefetch/api modules, `policy.json` | **Adopt**, plain ES modules served by FastAPI, no build step |
| E6 driver | Python virtual client reading the same `policy.json`, traces, Playwright check | **Adopt**; Playwright is not installed yet (needs the team's OK to add it) |

---

## Phase 1: tile engine core (backend only) · ✅ done

**Goal:** render any lattice tile fast and correctly, with decoded blocks shared between neighbouring tiles.
Steps 1–4 of the spec; useful on their own, because they also speed up box zoom.

**Result:** `demlab/view.py`, `kernels/tile_k.py`, `blockcache.py`, `resultcache.py`, `slru.py`, `colormap.py`,
`cancel.py`; 24 new tests (`tests/test_view.py`, `tests/test_caches.py`), 143 in total, all passing.
- Every auto-mode tile equals the existing engine's result on the whole level, cell for cell, for all 8 operator
  configurations, on every level of a test pyramid with data gaps and partial edge tiles. Exact and precomputed modes,
  box assembly and level choice (all Chamoli and tile-571 levels, with hysteresis) are tested.
- Parallel gate (`python -m bench.check_tile_parallel`, Chamoli 2 m, 64 tiles, warm blocks): 8 threads **5.4× faster**
  than 1 (8.2 ms → 1.5 ms per tile of throughput). This needed the colour quantiser compiled GIL-free and the PNG
  written with `zlib` (run-length deflate: 2–3× faster than default deflate for 5–15% larger tiles); with NumPy
  quantising and Pillow encoding it was 4.3×.
- Block cache: 64 neighbouring tiles decode **100 blocks instead of up to 576**; each block decodes once, warm tiles
  decode none.

| Task | Files | Done when |
|---|---|---|
| Lattice per level from its own geotransform and size; level choice with hysteresis; partial and edge tiles (nodata fill, transparent) | `demlab/view.py`, `demlab/pyramid.py` | Level choice correct on every Chamoli and tile-571 level; tiles outside the DEM answered as empty |
| Single-threaded `nogil` kernels for slope / aspect / hillshade (+ TRI, TPI, roughness) | `demlab/kernels/tile_k.py` | 8 threads rendering 64 tiles ≥ 5× faster than 1 thread |
| `render_tile(level, tx, ty, op, params, mode)` with per-stage timings (read, decode, kernel, colour, encode); modes auto, exact (full-resolution + average), precomputed (E5 slope pyramid) | `demlab/view.py` | Every cell equals the same window computed by the existing engine, edge and nodata tiles included |
| Block cache: aligned block reads, byte budget, SLRU, nodata sentinel, counters | `demlab/blockcache.py` | Warm 3 × 3 neighbourhood decodes ~1 block per tile (from up to 9); outputs unchanged |
| Result cache + canonical key + single-flight | `demlab/resultcache.py` | 100 identical concurrent requests compute once; key stable across runs and changes with every parameter |
| Colormaps (slope, aspect, hillshade, TRI/TPI/roughness) as 256-entry palettes | `demlab/colormap.py` | Palette PNG round-trips to the right values |
| Tests | `tests/test_view.py`, `test_blockcache.py`, `test_resultcache.py` | All pass with the existing 119 |

## Phase 2: scheduler and server API

**Goal:** many tiles at once on the right cores, cancellable, served over HTTP with timing headers. Spec steps 5–6.

| Task | Files | Done when |
|---|---|---|
| Scheduler: fg / bg priority queues (newest generation, then distance / pan direction), worker pools pinned to P- and E-cores, cancel tokens checked before dequeue, after each block read, before the kernel and before encoding; promotion bg → fg; queue cap 256; pause bg below 2.5 GB free RAM; stats | `demlab/sched.py` | With the bg queue saturated, fg p95 within 10% of an idle server; cancelled jobs stop at the next stage |
| API: `GET /info`, `GET /overview`, `GET /tiles/{level}/{tx}/{ty}.png` (ETag, cache headers, `Server-Timing`, `X-Expected-Error`), `POST /session/{sid}/gen`, `POST /prefetch`, `POST /view` (box, assembled from lattice tiles), `GET /stats`; disconnect watch | `server/app.py` | Aborting a fetch cancels its job within 50 ms; `/view` output equals the assembled tiles |
| Settings by environment variables (cache budgets, worker counts) | `server/settings.py` | Defaults ≈ 2.2 GB server memory |
| Tests | `tests/test_sched.py`, `tests/test_server.py` (FastAPI test client) | Pass |

## Phase 3: web viewer

**Goal:** smooth pan and zoom in the browser with debounce, fallbacks and prefetch. Spec steps 7–9.

| Task | Files | Done when |
|---|---|---|
| Camera (UTM centre, metres per device pixel, DPR cap), level choice mirrored from the server | `viz/web/camera.js` | Same level as the server for the same view |
| Tile layer: frame loop, overview base layer, fallback chain (level k → coarser cached → finer cached → overview), bilinear preview during gestures | `viz/web/tileLayer.js` | 60 fps from cache with the network cut; no blank cells |
| Bitmap cache: byte-accounted LRU 256 MiB, other levels evicted first, `close()` on evict | `viz/web/tileCache.js` | Memory stays under budget during long sessions |
| Gestures: wheel (passive: false, cursor-anchored), pinch, drag pan, keyboard; trailing debounce from `policy.json`; generation + `AbortController` | `viz/web/gestures.js`, `api.js` | A 2 s wheel burst gives exactly one commit; old requests show as cancelled on the server |
| Prefetch: 3 × 3 ring, velocity-first ordering, max 2 in flight, recentre at 25% offset (≤ 1 per 100 ms), off in exact mode / hidden tab / slow foreground | `viz/web/prefetch.js` | Neighbours load in pan order; a reversal aborts the far side within one recentre |
| UI: op, method, mode (auto / exact / precomputed), legend, level + cell size + expected error, breadcrumb, Shift + drag box zoom | `viz/web/index.html`, `ui.js` | Usable demo on both datasets |
| Policy shared with E6 | `viz/web/policy.json` | Read by the browser and the virtual client |

## Phase 4: QGIS plugin

**Goal:** the meeting asked for QGIS integration; the plugin uses the same server and caches.

| Task | Files | Done when |
|---|---|---|
| Map tool: drag a rectangle on the QGIS canvas → `POST /view` → result added as a georeferenced layer (UTM 44N); op / mode choice | `qgis_plugin/` | Works in QGIS 3.44 on both datasets; layer lines up with the DEM |
| Install notes | `qgis_plugin/README.md` | A teammate can install it from the notes |

## Phase 5: E6 benchmark, tuning and results

**Goal:** measure the viewer the same way E1–E5 were measured, set the defaults from the data. Spec step 10.

| Task | Files | Done when |
|---|---|---|
| Virtual client (Python port of the browser policy, `httpx.AsyncClient`, simulated 60 Hz frames, aborts as disconnects) | `bench/vclient.py` | Replays a trace and logs every request and frame |
| Seeded traces: `pan-line`, `pan-reverse`, `pan-walk`, `zoom-burst`, `zoom-pan`, `box` | `bench/traces/*.json` | Stored and reproducible |
| Sweeps, one factor at a time: debounce (off, 100–250 ms), prefetch on / off, ring order, bg on E-cores vs shared, worker counts, block cache 0 / 256 / 1024 MiB, result cache on / off, op, mode, dataset, cold / warm | `bench/experiments/e6_view.py`, `bench/run_e6.ps1` | 1 warm-up + 5 measured runs per configuration; median + IQR |
| Metrics: client hit rate, server tier mix, blank area-time, TTFF, time to complete view, server tiles per gesture (used / cancelled / superseded), prefetch precision and recall, fg interference, memory, CPU per core class | `results/e6_requests.csv`, `e6_frames.csv`, `runs.csv` | Both gates evaluated |
| Baseline: QGIS drawing the same boxes (as E1q) | `bench/experiments/e6_view.py` | Comparable numbers |
| Browser check (optional): 3 traces in Chrome via Playwright | `bench/e6_browser.py` | Needs Playwright installed (team's OK) |
| Report script, charts, write-up; update `policy.json` defaults | `bench/analysis/e6_report.py`, `docs/PHASE5_RESULTS.md` | Hit rate vs pan speed, TTFF and tiles vs debounce, fg p95 by prefetch config, memory timeline |

## Phase 6: final deliverables

| Task | Output |
|---|---|
| Final report (LaTeX): introduction, literature, data, method, E1–E6 results, the bottleneck story (G1), the pyramid trade-off (G2), the viewer, limitations, conclusion | `report/final_report/` |
| Slides and a recorded demo video (fallback for the live demo) | `report/slides/`, demo video |
| Professor update covering Phases 3–5 | `docs/prof_update_final.md` |
| Update `README.md`, `PROJECT_PLAN.md`, internal report; freeze code; tag the release; push; refresh the drive copy | — |

## Stretch (only if Phases 1–6 are on track)

- GPU tile path as an E6 variant (expected small gain at 512², per E4).
- Cesium globe showing the viewer's tiles draped on terrain.
- Viewshed (R3 vs XDraw vs `gdal_viewshed`) and terrain distance (Dijkstra vs A*): original Phase 6, gap G3.

---

## Risks

| Risk | Mitigation |
|---|---|
| Numba kernels not releasing the GIL → no tile-level parallelism | Separate `nogil` tile kernels, checked in Phase 1 before anything is built on them |
| Too many threads (Numba, GDAL, pools) | 1 Numba and 1 GDAL thread per tile; fixed pools |
| Browser allows 6 connections per origin | At most 2 prefetch requests in flight |
| GDAL reads cannot be interrupted | Cancel checks between stages; worst case one block decode |
| Exact mode and HiDPI screens multiply the work | No prefetch in exact mode; DPR cap 1 for level choice; ring shrinks to cardinals above 150 tiles |
| Memory beside browser, QGIS and Windows | Byte budgets (~2.2 GB server, 256 MiB client); bg pauses below 2.5 GB free |
| Pan-zoom client not finished in time | Phases 1–2 also make box zoom fast; box zoom remains the fallback demo |

## Team decisions

1. **Confirmed:** continuous debounced pan / zoom is the main interaction; box zoom is kept as Shift + drag and for
   QGIS. This replaces the decision recorded in `PROJECT_PLAN.md` §4.
2. **Confirmed owners:** backend and server (Phases 1–2) Swayam; web viewer and prefetch (Phase 3) Kartikeya, author
   of the spec; E6 (Phase 5) Siddharth; QGIS plugin and final deliverables shared.
3. Open (decide before Phase 5): installing Playwright (Python package + browser) for the optional in-browser E6 check.
