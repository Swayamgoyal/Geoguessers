# GeoGuessers Phase 5: Debounced Zoom and Speculative Neighbour Prefetch — Engineering Plan

Oct 28, 2026 · @Kartikeya

## Summary

Phase 5 moves the web viewer from discrete box zoom to continuous pan and zoom over a fixed 512 × 512 tile lattice per pyramid level. Zoom commits once, 200 ms after the last wheel tick. The 8 neighbouring views are prefetched at low priority on the efficiency cores, and a shared decoded-block cache removes the halo re-decoding that E3 measured.

The levers follow from the measurements, not from the kernel. E5 puts a 512² on-demand tile at 5–8 ms, of which the slope kernel is about 0.5 ms. E3 showed a 512 window decodes up to 9 compressed blocks because of the 1-cell halo. So the work to save is decoding, and computing levels the user only scrolls through.

| Decision | Choice | Grounds |
| --- | --- | --- |
| Request unit | 512² lattice tiles aligned to each level's COG blocks, not free bounding boxes | Free bbox keys almost never repeat while panning; lattice keys do, so caches hit |
| Zoom | Trailing debounce, 200 ms default (150–250 configurable); canvas rescales existing bitmaps meanwhile | One commit per gesture instead of one per tick |
| Priority | Foreground pool on the 12 performance-core threads; prefetch pool pinned to the 8 efficiency cores | E3: 12 P-threads beat all 22; E-cores are 1.7× slower and only slow the foreground when mixed in |
| Cancellation | Generation number per commit, `AbortController` per generation, cooperative tokens checked between stages | Python threads cannot be killed; every stage is a few ms, so stage checks are fine-grained enough |
| Caching | Server: decoded blocks + rendered tiles. Client: `ImageBitmap` LRU | E3 and E5 both name re-decoding as the main cost of a tile |
| Exact mode | No prefetch | E5: the full-resolution route costs up to 2.9 s per tile at 32 m |

Two requirements are adjusted. Cache keys use lattice coordinates, not the raw bbox, or pan traffic would never hit. And memory per view does not grow with zoom depth in auto mode, since one level cell ≈ one pixel; the real memory risks are exact mode, HiDPI screens and client bitmaps (see Risks).

Box zoom stays: `POST /view` and the QGIS plugin keep their contract and are served from the same caches. Plan §4 records box zoom as a team decision, so this change needs the team's sign-off and an edit to the plan.

## Architecture and data flow

A zoom gesture costs the server nothing until 200 ms after its last tick; then one commit renders the visible tiles on the performance cores, and only after that does the 3 × 3 ring load on the efficiency cores.

&#91;embedded content: zoom, commit and prefetch sequence · 6 components, 3 phases\]

During the gesture the canvas redraws cached bitmaps at the new scale, so the screen responds every frame without the server. Panning never waits for a debounce: ring tiles are already bitmaps, and the ring recentres once the view moves 25% off centre.

### Cancellation lifecycle

Every commit carries a generation number; anything older is cancelled on the client by `AbortController` and on the server by cooperative tokens checked between stages.

| Trigger | Client | Server | Work lost at most |
| --- | --- | --- | --- |
| First tick of a zoom gesture | Abort the background controller; post the new generation | Queued background jobs dropped; running ones stop at the next stage | One stage per background worker (a few ms) |
| Commit at a new level | `gen + 1`; abort old foreground tiles not in the new visible set | Older-generation foreground jobs dropped; running ones stop at the next stage, or finish into the cache if past the kernel | About 1 ms per running job |
| Commit at the same level | Keep in-flight tiles that are still visible; abort the rest | As above for the aborted ones | Same |
| Pan within 25% of the committed centre | Nothing | Nothing | None |
| Pan beyond 25%, or a sudden reversal | Rebuild the ring; abort ring tiles outside the new ring | Matching background jobs cancelled | One stage per cancelled running job |
| Foreground request for a tile queued or running as background | — | Promote it to the foreground queue, or join the running job | None |
| Op, parameter or mode change | `gen + 1`; abort everything | All older-generation jobs cancelled; caches kept | One stage per worker |
| Tab hidden | Abort background; pause prefetch | Background jobs cancelled | One stage per background worker |

A job shared by several requests (single-flight) is cancelled only when its last waiter has gone, so an abort never kills a tile another request still needs.

## Backend engine and API (`server/`, `demlab/`)

The server renders lattice tiles through one priority scheduler and two in-process caches, in a single uvicorn worker so every request shares them.

### Request unit: the tile lattice

Each pyramid level k gets a lattice of 512 × 512-cell tiles aligned to that level's own COG block grid. Tile (tx, ty) covers level cells \[512·tx, 512·tx + 512) × \[512·ty, 512·ty + 512). The lattice comes from each level's own geotransform and size, because GDAL rounds overview sizes down (level-3 cells cover 8.002 fine rows, Phase 4).

A view of W × H screen pixels at level k needs at most (⌈W/512⌉ + 1) × (⌈H/512⌉ + 1) tiles: 20 for 1920 × 1080. The 3 × 3 ring of view-sized rectangles needs about 104, so the 8 neighbours add about 84 tiles. At E5's 5–8 ms each, that is roughly 0.5 worker-seconds per commit before block-cache savings (estimate; E6 measures it).

Level choice uses the real level cell sizes rather than 2^k. With s the ground size of one device pixel and c₀ … c\_K the level cell sizes:

```latex
k = \max\{\, j \in \{0,\dots,K\} : c_j \le s \,\} \quad (k = 0 \text{ when } s < c_0)
```

This matches the plan's rule (one level cell ≈ one screen pixel, never coarser than a pixel). A ±10% hysteresis band on s stops the level flipping when a gesture ends near a boundary.

### Endpoints

| Endpoint | Status | Inputs | Returns |
| --- | --- | --- | --- |
| `GET /info` | Extend | — | Extent, CRS, per-level cell size, size, block size, tile counts, dataset version |
| `GET /overview?op=…` | Keep | op, params | Whole-map image; the client's permanent base layer |
| `GET /tiles/{level}/{tx}/{ty}.png` | New | Query: op, method, params, mode, colormap. Headers: `X-Session`, `X-Gen`, `X-Priority: fg`/`bg` | PNG with `ETag`, `Cache-Control: private, max-age=86400` (dataset version in the URL), `Server-Timing`, `X-Level-Cell`, `X-Expected-Error` (E5 RMSE for that level) |
| `POST /session/{sid}/gen` | New | `{gen}` | 204; cancels that session's queued and running jobs of older generations |
| `POST /prefetch` | New | `{session, gen, level, op, params, mode, tiles: [[tx, ty], …]}` | 202; warms the server caches only. For the QGIS plugin and E6 |
| `POST /view` | Keep contract | `{bbox, op, mode, device, width, height}` + optional `priority` | PNG + JSON as today, assembled from lattice tiles so it shares the caches |
| `GET /stats` | New | — | Bytes, entries and hits per cache tier; queue depths; pool busy time |

`Server-Timing` carries `queue`, `read`, `decode`, `kernel`, `colormap`, `encode` and the cache tier that served the tile. E6 reads every number from these headers instead of instrumenting the client.

The tile endpoint is a GET with immutable URLs so the browser's own HTTP cache becomes a free third client tier. Priority rides in a header, not the URL, so a background tile and a later foreground request for it share one cache entry.

### Concurrency model

The event loop does only HTTP and bookkeeping; every tile runs on scheduler threads. The scheduler holds two priority queues and runs tile-level parallelism: many single-threaded tiles at once, not one multi-threaded tile.

| Pool | Threads | Pinned to | Takes | Per-tile threading |
| --- | --- | --- | --- | --- |
| Foreground | 8 (tune 4–8 in E6) | 12 performance-core logical CPUs | `fg` queue only | Numba 1 thread, `GDAL_NUM_THREADS=1` |
| Background | 3 (tune 0–4 in E6) | 8 efficiency cores | `bg` queue only | Same |
| GPU (optional) | 1 dispatcher | — | `fg` with `device=cuda` | Existing 2 CUDA streams, 4 GB cap |

- **Isolation by core class.** Prefetch never competes for performance cores, so no preemption is needed for CPU. Pinning uses `SetThreadAffinityMask` via `ctypes`, reusing the core detection in `performance_cpus()`. E6 also runs a shared-core variant where background workers yield whenever the foreground queue is non-empty.
- **GIL.** Tile-level parallelism needs the Numba kernels compiled with `nogil=True`. `numba.set_num_threads(1)` is thread-local, so each worker sets it once. GDAL reads already release the GIL.
- **Queue order.** Foreground: newest generation first, then distance from the view centre. Background: newest generation, then pan direction, cardinals before corners.
- **Single-flight.** An in-flight map from cache key to future. A foreground request for a key queued as background moves it to the foreground queue; if already running, it joins the future.
- **Disconnects.** Starlette does not cancel a plain endpoint when the client aborts. Each tile endpoint awaits `asyncio.wait({job, disconnect_watch}, return_when=FIRST_COMPLETED)`, polling `request.is_disconnected()` every 20 ms. When a job's waiter count reaches zero, its cancel token is set.
- **Cancel points.** Before dequeue, after each block read, before the kernel, before encoding. A job past the kernel finishes into the cache instead, since about 1 ms is left.
- **Backpressure.** The background queue holds at most 256 tiles, dropping the oldest generation first. Background dispatch pauses when free system memory drops below 2.5 GB (`psutil`).

Scheduler surface in `demlab/sched.py`:

```python
class TileJob:  # key, level, tx, ty, op, params, mode, session, gen, priority
    token: CancelToken

class Scheduler:
    def submit(self, job: TileJob) -> Future: ...     # single-flight by job.key
    def promote(self, key: str) -> None: ...          # bg -> fg if still queued
    def supersede(self, session: str, gen: int) -> None: ...  # cancel older gens
    def stats(self) -> dict: ...
```

### Caches

| Tier | Holds | Key | Entry | Default budget | Eviction |
| --- | --- | --- | --- | --- | --- |
| Block (`demlab/blockcache.py`) | Decoded DEM blocks, float32 | (dataset version, level, block col, block row) | 1 MiB; 0 B sentinel for all-nodata blocks | 1024 MiB | Segmented LRU: 20% probation, 80% protected |
| Result (`demlab/resultcache.py`) | Encoded tile PNGs | 128-bit BLAKE2b of the canonical tile spec | Measure in E6 | 512 MiB | Segmented LRU; prefetched tiles enter probation, move up on first foreground hit |
| GDAL block cache | GDAL's own | per dataset handle | — | `GDAL_CACHEMAX=128` | GDAL's; kept small because thread-local handles each cache their own copy |
| Client (`viz/web/tileCache.js`) | `ImageBitmap` per tile | same canonical spec | 1 MiB (512² RGBA) | 256 MiB | LRU; other levels first; `close()` on evict |

1024 MiB of blocks holds about 1000 blocks, roughly eight warm 3 × 3 rings at 1920 × 1080. Readers ask the block cache before GDAL, so neighbouring tiles share halo blocks. The target is about 1 block decoded per tile on a warm ring, down from up to 9.

The canonical result key is JSON with sorted keys, hashed with `blake2b(digest_size=16)`, over: dataset id and version (file size + mtime), level, tx, ty, tile size, op, method (Horn or ZT), z-factor (0.01), sun azimuth and altitude (rounded to 1°), mode, colormap id and stretch range. Device is left out because CPU and GPU match gdaldem on every cell (Phase 3). Rounding sun angles stops a hillshade slider from creating a new key per pixel of travel.

Server memory budget on the 16 GB machine (estimates; E6 measures):

| Item | Size |
| --- | --- |
| Python, Numba, GDAL baseline | \~0.6 GB |
| Block cache | 1.0 GB |
| Result cache | 0.5 GB |
| In-flight windows (11 jobs × \~3 MiB) | < 0.05 GB |
| Server total | \~2.2 GB |

That leaves room for Windows, the browser (client cache 256 MiB plus page) and QGIS. Budgets are set by `DEMLAB_BLOCK_CACHE_MB`, `DEMLAB_RESULT_CACHE_MB`, `DEMLAB_FG_WORKERS` and `DEMLAB_BG_WORKERS`.

## Frontend (`viz/web/`)

The viewer splits a fast transient camera, redrawn every animation frame from cached bitmaps, from a settled state that changes only on commit and is the only thing that talks to the server.

### State and layers

| State | Holds | Changes on | Touches network |
| --- | --- | --- | --- |
| Camera (transient) | Centre (UTM), metres per device pixel | Every wheel, pinch or drag event | No |
| Settled | Level k, visible tile set, ring tile set, generation | Debounced zoom commit; pan beyond hysteresis | Yes |

One `<canvas>` draws, every `requestAnimationFrame`, the overview base layer and then each visible lattice cell's best available bitmap. Drawing about 20–30 GPU-backed 512² bitmaps per frame is cheap. During a zoom gesture the camera scale changes, so existing bitmaps are drawn scaled with `imageSmoothingQuality = 'low'`: the bilinear preview.

Fallback chain per visible cell, first hit wins:

1. Level-k bitmap.
2. Nearest coarser cached level, cropped and upscaled.
3. Finer cached tiles, downscaled.
4. The overview image, which is always loaded, so no cell is ever blank.

### Gesture handling

- **Wheel:** `addEventListener('wheel', h, {passive: false})` with `preventDefault()`. Normalise `deltaMode` to pixels. Zoom factor `exp(-deltaY × 0.0015)` about the cursor; `ctrlKey` wheel events are trackpad pinches in Chrome and get the same path.
- **Pointer:** pointer events with `setPointerCapture`; one pointer pans, two pinch.
- **Keyboard:** `+` / `−` zoom about the centre, arrows pan by a quarter view.
- **First zoom tick of a gesture:** abort the background `AbortController` (the level will probably change) and post `POST /session/{sid}/gen`. Foreground requests stay alive until the commit decides.
- **Debounce:** a trailing timer, reset on every tick, fires after `debounceMs` (default 200, range 150–250 from `policy.json` or `?debounce=`). Pinch end (last `pointerup`) fires it at once. An optional `maxWaitMs` (off by default) forces a commit during very long gestures; E6 decides whether it earns a place.
- **Pan:** no debounce, since the level does not change. Missing visible tiles are requested immediately, coalesced once per animation frame.

### Commit

1. Read the camera, convert to a bbox in UTM and clip to the extent from `/info`.
2. Choose k with the rule in the backend section. Device pixels use `devicePixelRatio`, capped by `policy.dprCap` (default 1; see Risks).
3. Increment `gen`. Abort old-generation foreground requests for tiles not in the new visible set; keep the rest.
4. Request visible tiles centre-out with `fetch(url, {signal, priority: 'high', headers: {'X-Priority': 'fg', 'X-Gen': gen}})`.
5. Decode with `createImageBitmap(blob)` (off the main thread) and store in the client cache.
6. When every visible tile has arrived or failed, hand the view to the prefetch manager.

### Prefetch manager (`viz/web/prefetch.js`)

- **Ring:** the 8 view-sized rectangles NW, N, NE, W, E, SW, S, SE around the committed view at level k, converted to lattice tiles. Minus visible tiles, tiles already cached and tiles outside the DEM.
- **Order:** tiles in the direction of the last pan velocity first, then cardinals before corners, then nearer before farther.
- **In flight:** at most 2 background requests at a time. Browsers allow 6 HTTP/1.1 connections per origin, so this always leaves 4 for the foreground. Option: serve background tiles from a second origin (`127.0.0.1` vs `localhost`) for a separate connection pool.
- **Recentre:** when the camera centre moves more than 25% of W or H from the committed view's centre, rebuild the ring, at most once per 100 ms. Ring requests no longer in the new ring are aborted; in-flight ones still in it continue. A sudden pan reversal is handled by this same rule.
- **Bitmap cache:** `Map` from tile key to `{bitmap, bytes, level, lastUsed, origin: 'fg' | 'bg', firstDrawnAt}`. LRU at 256 MiB, evicting other levels first and calling `bitmap.close()` to free GPU memory. `firstDrawnAt` gives E6 the prefetch hit rate.
- **Switched off when:** mode is exact; `document.hidden`; the client sees foreground p95 above 100 ms over the last 20 tiles (backs off for 2 s).

### Module layout

| File | Responsibility |
| --- | --- |
| `policy.json` | Debounce, hysteresis, in-flight caps, cache budgets, DPR cap; also read by E6 |
| `camera.js` | Camera state, screen ↔ UTM transforms, level choice |
| `gestures.js` | Wheel, pointer and keyboard handling; debounce timer |
| `api.js` | Tile URLs, headers, `AbortController` per generation |
| `tileCache.js` | Bitmap LRU, byte accounting, `close()` |
| `tileLayer.js` | Frame loop, fallback chain, overview base layer |
| `prefetch.js` | Ring construction, ordering, recentring, pruning |

The breadcrumb, op, mode and CPU/GPU switches stay. Box drag becomes a modifier gesture (Shift + drag) that animates the camera to the box and commits.

## Benchmark integration (E6)

`bench/experiments/e6_view.py` gains a scripted virtual client, five trace families and a per-request log; the existing nested-box sequences stay as one family. The headline gates: prefetch must not raise foreground p95 by more than 10%, and debouncing must cut server tiles per zoom gesture while keeping time to first frame under 100 ms after the debounce delay.

### Driver

- **Virtual client** (`bench/vclient.py`): a Python port of the same policy, reading `viz/web/policy.json`, so the browser and the benchmark cannot drift apart. It replays traces against the live server with `httpx.AsyncClient`. Aborts are task cancellations that close the stream, which the server sees as a disconnect, as with `AbortController`.
- **Frame clock:** 60 Hz simulated. Each frame computes the visible tiles from the camera and checks which are already in the client cache.
- **Browser check:** 3 traces end to end in Chrome via Playwright, with `performance.mark` at commit and first draw, to confirm the virtual client's numbers.
- **Server side:** timings from `Server-Timing`, cache counters from `GET /stats`, RSS and per-thread CPU sampled every 50 ms with `psutil` in a sidecar thread.

### Traces (seeded, stored in `bench/traces/*.json`)

| Trace | Shape | Parameters |
| --- | --- | --- |
| `pan-line` | Constant-velocity pan | 0.5, 1 and 2 view widths per second; 5 s |
| `pan-reverse` | Pan, then sudden reversal | As `pan-line`, reversal at 2.5 s |
| `pan-walk` | Random walk | Seeded heading changes every 0.3–1 s |
| `zoom-burst` | Wheel ticks at 60 Hz | 0.3, 1 and 2 s bursts; in and out; up to ±3 levels |
| `zoom-pan` | Alternating bursts and pans | 10 s |
| `box` | Existing random nested boxes | Whole map to full resolution |

### Metrics

| Metric | Definition | Source |
| --- | --- | --- |
| Client hit rate | Share of tiles that are already in the bitmap cache when they first enter the view | Virtual client frames |
| Server tier mix | Share of tiles served by result cache, warm blocks, or cold decode | `Server-Timing` |
| Blank area-time | Share of visible area × frame time drawn from a fallback instead of the level-k tile | Virtual client frames |
| Time to first frame (TTFF) | Last wheel event → first level-k tile drawn | Virtual client; Playwright marks |
| Time to complete view | Last wheel event → every visible tile drawn | Same |
| Server tiles per gesture | Tiles computed per zoom gesture, split into used, cancelled mid-run, and superseded | Request log |
| Prefetch precision | Prefetched tiles later drawn ÷ prefetched tiles | Client cache `firstDrawnAt` |
| Prefetch recall | Pan misses that a ring would have covered ÷ pan misses | Request log |
| Foreground interference | Foreground tile latency p50 / p95 with prefetch on vs off | Request log |
| Memory | Server RSS and bytes per cache tier over time; client bitmap bytes | `psutil`, `/stats`, client |
| CPU allocation | CPU-seconds per pool; utilisation per core class (P, E, low-power E) | Per-thread `psutil` times grouped by affinity |

TTFF with debouncing includes the debounce delay by design. So E6 reports it next to server tiles per gesture: the trade is a fixed \~200 ms delay against fewer wasted tiles and an uncontended commit.

### Variables

One factor at a time around the defaults, since the full factorial is too large:

- debounce: off (commit every tick), 100, 150, 200, 250 ms;
- prefetch: off, on; ring order: fixed vs velocity-first;
- background placement: efficiency cores pinned vs shared performance cores with yielding;
- workers: foreground 4 / 6 / 8, background 0 / 2 / 3 / 4;
- block cache 0 / 256 / 1024 MiB; result cache on / off;
- op: slope, hillshade, three products; mode: auto, precomputed (exact for `box` only);
- data: Chamoli 2 m, tile-571 8 m; OS cache cold (flushed with `bench/cache.py`) vs warm.

### Recording

- `results/e6_requests.csv`: one row per tile request: run id, trace, session, gen, priority, level, tx, ty, cache tier, queue / read / decode / kernel / colormap / encode ms, cancelled at stage, bytes.
- `results/e6_frames.csv`: one row per simulated frame: visible tiles, cache hits, blank area share.
- `results/runs.csv`: one summary row per trace run, as the harness does today, with the metrics above in `extra`.
- Protocol unchanged: 1 warm-up and 5 measured runs per configuration, median and IQR, run conditions in `results/env/`.
- New standard plots: hit rate against pan speed; TTFF and server tiles against debounce; foreground p95 by prefetch configuration; memory timeline for `zoom-pan`.

The Core Ultra 9 185H has 6 performance cores (12 threads), 8 efficiency cores and 2 low-power cores. E6 verifies the pinning by checking that background-pool CPU time lands on efficiency cores only. GPU runs are recorded but background work never uses the GPU.

## Risks and bottlenecks

In auto mode memory per view is bounded by screen size, not zoom depth: one level cell ≈ one pixel, so every level reads about the same number of cells. The risks that do bite are exact mode, high-density screens, client bitmaps and contention.

### Memory thrashing

| Case | Why it grows | Mitigation |
| --- | --- | --- |
| Exact mode | Reads 4^k times the view's cells: 8 neighbours at 32 m from 2 m would read 256× each, at up to 2.9 s per tile (E5) | No prefetch in exact mode; foreground exact work limited to the visible tiles |
| HiDPI and 4K screens | `devicePixelRatio` 2 picks a level one finer: 4× tiles per view, a ring of \~400 tiles | `dprCap` (default 1) for level choice; ring shrinks to cardinals when it exceeds 150 tiles |
| Client bitmaps | `ImageBitmap`s hold GPU memory until `close()` | Byte-accounted LRU at 256 MiB; `close()` on every eviction |
| Server caches beside the browser, QGIS and Windows | 16 GB total | Byte-accounted budgets (\~2.2 GB server); background pauses below 2.5 GB free |
| Fast panning | Ring rebuilt on every move refills the queue | 25% hysteresis, at most one rebuild per 100 ms, queue cap 256 tiles |
| Zoomed out past the coarsest level | — | k clamped to the coarsest level; most of the ring falls outside the DEM and is skipped |

### Contention and correctness

| Risk | Effect | Mitigation | Seen in E6 as |
| --- | --- | --- | --- |
| Kernels compiled without `nogil` | Tile-level parallelism collapses to one core | Check before step 3; recompile with `nogil=True` | Foreground throughput flat with more workers |
| Thread oversubscription (Numba, GDAL, pools) | Same slowdown E3 saw with 22 threads | 1 Numba and 1 GDAL thread per tile; fixed pools | CPU-seconds > wall × cores |
| HTTP connection pool (6 per origin) | Prefetches delay foreground tiles | Background in-flight cap of 2; optional second origin | Foreground queue time on the client side |
| Cancellation cannot interrupt a GDAL read | Some work finishes after its abort | Checks between stages; worst case one block decode | `cancelled at stage` in the request log |
| Debounce too long or too short | Laggy feel, or wasted tiles | Bilinear preview hides the delay; E6 sweep picks the default | TTFF and server tiles per gesture |
| Level flips at a boundary | Two commits for one gesture | ±10% hysteresis on pixel size | Repeated level changes per gesture |
| Stale tiles after the DEM changes | Old results served | Dataset version in every key and URL | — |
| Scope against the 3-week plan | Pan-zoom not done for the demo | Steps 1–5 below also speed up box zoom; keep box zoom as the fallback demo | — |

### DEM boundary and halo rules

1. Each level's lattice comes from that level's own geotransform and size, not 2^k × the fine cell size.
2. Tiles fully outside the DEM are never requested; the client clips with the extent from `/info`, and the server answers 204 if one arrives.
3. Partial tiles read only the intersection and fill the rest with nodata. They stay 512² and draw that part transparent, so the lattice stays regular.
4. Halo cells beyond the raster edge are nodata, so edge cells are nodata, matching the current engine and gdaldem without `-compute_edges`. If edge computation is added later, it replicates edge cells, as gdaldem does.
5. Interior nodata follows the engine's existing rule. All-nodata blocks are cached as a 0-byte sentinel and are never decoded twice.
6. Ring neighbours outside the DEM are dropped and left out of hit-rate denominators. E6 counts them separately.
7. Past level 0, k stays 0 and level-0 tiles are drawn magnified, so the ring costs fewer cells per screen.
8. The halo between two lattice tiles comes from neighbouring blocks through the block cache. That is where the ring pays off twice: its tiles are ready, and their halo blocks are already decoded.

## Implementation sequence

Ten steps, each testable alone; steps 1–5 are backend-only and also speed up today's box zoom, so they are worth doing even if the pan-zoom client slips.

1. **Lattice and tile renderer** (`demlab/view.py`, `demlab/pyramid.py`). `render_tile(level, tx, ty, op, params, mode)` with per-stage timings; partial-tile and edge rules.
   - Done when: tests show tile output equals the same window of the existing view route on every cell, edge and nodata tiles included; level choice matches the rule on all Chamoli and tile-571 levels.
2. **GIL check** (`demlab/kernels/numba_k.py`). Confirm or add `nogil=True`; `set_num_threads(1)` per worker.
   - Done when: 8 threads rendering 64 tiles run at least 5× faster than 1 thread.
3. **Block cache** (`demlab/blockcache.py`), used by the reader before GDAL.
   - Done when: rendering a warm 3 × 3 tile neighbourhood decodes about 1 block per tile instead of up to 9 (counter in `/stats`); outputs unchanged.
4. **Result cache and single-flight** (`demlab/resultcache.py`).
   - Done when: 100 concurrent identical requests compute once; the canonical key is stable across runs and changes with every listed parameter.
5. **Scheduler and pools** (`demlab/sched.py`). Two queues, affinity pinning, cancel tokens, promotion, backpressure, memory guard.
   - Done when: with the background queue saturated, foreground tile p95 is within 10% of an idle server; cancelled jobs stop at the next stage boundary.
6. **API** (`server/app.py`). `GET /tiles`, `POST /session/{sid}/gen`, `POST /prefetch`, `GET /stats`, extended `/info`, `Server-Timing`, disconnect watch. `POST /view` rebuilt on lattice tiles.
   - Done when: aborting a fetch cancels its server job within 50 ms; the QGIS plugin works unchanged.
7. **Tile layer and client cache** (`viz/web/tileLayer.js`, `tileCache.js`, `camera.js`, `api.js`). Frame loop, fallback chain, overview base layer.
   - Done when: pan and zoom draw at 60 fps from cache with the network cut; no visible blank cells.
8. **Gestures, debounce and cancellation** (`viz/web/gestures.js`).
   - Done when: a 2 s wheel burst produces exactly one commit; old-generation requests show as cancelled in the server log.
9. **Prefetch manager** (`viz/web/prefetch.js`).
   - Done when: after a commit the 8 neighbours load in pan-direction order; a reversal aborts the far side within one recentre.
10. **E6 extension and tuning** (`bench/vclient.py`, `bench/experiments/e6_view.py`, `bench/traces/`). Run the sweeps, set `policy.json` defaults from the results, write `docs/PHASE5_RESULTS.md` and update plan §4.
    - Done when: every metric in the E6 section is in `results/`, and the two gates hold (foreground p95 within 10% with prefetch on; fewer server tiles per gesture with the debounce than without).
