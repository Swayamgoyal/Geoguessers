"""GeoGuessers tile server (Phase 5): FastAPI over demlab.service.TileService, one process, one worker.

Endpoints
  GET  /info                                   datasets, levels (cell size, lattice, expected E5 error), legends
  GET  /overview/{dataset}.png                 coarsest level as one image (the client's base layer); X-Bounds
  GET  /tiles/{dataset}/{level}/{tx}/{ty}.png  one 512² lattice tile; query: op, method, mode, cmap, vmin, vmax,
                                               azimuth, altitude, zfactor, v (dataset version, for immutable URLs);
                                               headers: X-Session, X-Gen, X-Priority (fg|bg), X-Order
                                               -> 200 PNG | 204 empty | 409 superseded | 499 client gone
  POST /session/{sid}/gen      {"gen": n, "cancel_bg": bool}   cancel the session's older work (and its prefetch)
  POST /prefetch               {"dataset", "session", "gen", "level", "tiles": [[tx, ty], ...], op, ...} -> 202
  POST /view                   {"dataset", "bbox": [xmin, ymin, xmax, ymax], "width", op, mode, ..., "format":
                                "png"|"tif"} -> box assembled from lattice tiles (PNG + X-Geotransform, or GeoTIFF)
  GET  /stats                  cache tiers, queues, pools, memory
  GET  /viewer/                the web viewer (viz/web)

Run:  python -m server            (http://127.0.0.1:8765/viewer/)
Settings: DEMLAB_BLOCK_CACHE_MB, DEMLAB_RESULT_CACHE_MB, DEMLAB_FG_WORKERS, DEMLAB_BG_WORKERS, DEMLAB_BG_SHARED,
DEMLAB_BG_MIN_FREE_GB (pause prefetch below this much free RAM; default 2.5), DEMLAB_BG_YIELD (1: prefetch
waits while any foreground tile is queued or running; default 1).
"""
import asyncio
import io
import json
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from demlab import colormap
from demlab.cancel import Cancelled
from demlab.service import TileService
from demlab.view import TileSpec, expected_error, render_box

WEB = Path(__file__).resolve().parents[1] / "viz" / "web"
TILE_PARAMS = ("op", "method", "mode", "cmap", "vmin", "vmax", "azimuth", "altitude", "zfactor")
FLOATS = ("vmin", "vmax", "azimuth", "altitude", "zfactor")


def tile_kwargs(src):
    """TileSpec keyword arguments from query parameters / JSON."""
    kw = {}
    for k in TILE_PARAMS:
        v = src.get(k)
        if v in (None, ""):
            continue
        kw[k] = float(v) if k in FLOATS else str(v)
    return kw


def server_timing(out):
    parts = [f"{k};dur={v:.2f}" for k, v in out.timings.items()]
    parts.append(f'tier;desc="{out.tier}"')
    return ", ".join(parts)


def create_app(service=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.svc = service or TileService.from_env()
        yield
        app.state.svc.close()

    app = FastAPI(title="GeoGuessers tile server", lifespan=lifespan)

    def svc(request):
        return request.app.state.svc

    @app.get("/")
    async def root():
        return RedirectResponse("/viewer/")

    @app.get("/info")
    async def info(request: Request):
        return JSONResponse(svc(request).info())

    @app.get("/stats")
    async def stats(request: Request):
        return JSONResponse(svc(request).stats())

    @app.get("/overview/{dataset}.png")
    async def overview(dataset: str, request: Request):
        s = svc(request)
        if dataset not in s.pyramids:
            raise HTTPException(404, f"unknown dataset {dataset}")
        try:
            png, bounds, k = await asyncio.to_thread(s.overview, dataset, **tile_kwargs(request.query_params))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return Response(png, media_type="image/png",
                        headers={"X-Bounds": json.dumps(bounds), "X-Level": str(k),
                                 "Cache-Control": "private, max-age=86400",
                                 "Access-Control-Expose-Headers": "X-Bounds, X-Level"})

    @app.get("/tiles/{dataset}/{level}/{tx}/{ty}.png")
    async def tile(dataset: str, level: int, tx: int, ty: int, request: Request):
        s = svc(request)
        try:
            pyr, spec = s.spec(dataset, level, tx, ty, **tile_kwargs(request.query_params))
        except KeyError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))
        if not pyr.in_lattice(level, tx, ty):
            return Response(status_code=204)
        out = s.cached(pyr, spec)
        if out is None:
            h = request.headers
            ticket = s.submit(pyr, spec, session=h.get("x-session", ""), gen=int(h.get("x-gen", 0) or 0),
                              priority="bg" if h.get("x-priority") == "bg" else "fg",
                              order=float(h.get("x-order", 0) or 0))
            fut = asyncio.wrap_future(ticket.future)
            fut.add_done_callback(lambda f: f.cancelled() or f.exception())  # never "exception not retrieved"
            gone = asyncio.create_task(_disconnected(request))  # event-driven: fires when the client goes away
            done, _ = await asyncio.wait({fut, gone}, return_when=asyncio.FIRST_COMPLETED)
            if fut not in done:
                s.sched.release(ticket)
                return Response(status_code=499)
            gone.cancel()
            try:
                out = fut.result()
            except Cancelled as e:
                return Response(status_code=409, headers={"X-Cancelled": str(e)})
            except ValueError as e:
                raise HTTPException(400, str(e))
        ee = expected_error(pyr.name, level, spec.mode)
        headers = {"Server-Timing": server_timing(out), "X-Cache-Tier": out.tier,
                   "X-Level-Cell": f"{out.level_cell:.3f}", "ETag": f'"{s.key(pyr, spec)}"',
                   "Cache-Control": "private, max-age=86400",
                   "Access-Control-Expose-Headers": "Server-Timing, X-Cache-Tier, X-Level-Cell, X-Expected-Error"}
        if ee:
            headers["X-Expected-Error"] = f"{ee[0]:.2f}"
        if out.png is None:
            return Response(status_code=204, headers=headers)
        return Response(out.png, media_type="image/png", headers=headers)

    @app.post("/session/{sid}/gen")
    async def new_generation(sid: str, request: Request):
        body = await request.json()
        s = svc(request)
        n = s.sched.supersede(sid, int(body.get("gen", 0)))
        if body.get("cancel_bg"):
            n += s.sched.cancel_priority(sid, "bg")
        return JSONResponse({"cancelled": n}, status_code=200)

    @app.post("/prefetch")
    async def prefetch(request: Request):
        body = await request.json()
        s = svc(request)
        kw = tile_kwargs(body)
        n_new = 0
        for i, (tx, ty) in enumerate(body.get("tiles", [])):
            try:
                pyr, spec = s.spec(body["dataset"], body["level"], tx, ty, **kw)
            except (KeyError, ValueError) as e:
                raise HTTPException(400, str(e))
            if spec.mode == "exact" or not pyr.in_lattice(spec.level, tx, ty) or s.cached(pyr, spec) is not None:
                continue
            s.submit(pyr, spec, session=body.get("session", ""), gen=int(body.get("gen", 0)), priority="bg",
                     order=float(i))
            n_new += 1
        return JSONResponse({"queued": n_new}, status_code=202)

    @app.post("/view")
    async def view(request: Request):
        body = await request.json()
        s = svc(request)
        name = body.get("dataset")
        if name not in s.pyramids:
            raise HTTPException(404, f"unknown dataset {name}")
        pyr = s.pyramids[name]
        kw = tile_kwargs(body)
        bbox = [float(v) for v in body["bbox"]]
        width = int(body.get("width", 1024))
        level = body.get("level")
        try:
            vals, gt, k = await asyncio.to_thread(render_box, pyr, bbox, width, kw, s.blocks,
                                                  level=None if level is None else int(level))
        except ValueError as e:
            raise HTTPException(400, str(e))
        if vals is None:
            return Response(status_code=204)
        spec = TileSpec(level=k, tx=0, ty=0, **kw)
        ee = expected_error(name, k, spec.mode)
        headers = {"X-Level": str(k), "X-Level-Cell": f"{pyr.levels[k].res:.3f}", "X-Geotransform": json.dumps(gt),
                   "X-CRS": pyr.crs, "X-Size": json.dumps([vals.shape[1], vals.shape[0]]),
                   "Access-Control-Expose-Headers": "X-Level, X-Level-Cell, X-Geotransform, X-CRS, X-Size"}
        if ee:
            headers["X-Expected-Error"] = f"{ee[0]:.2f}"
        if body.get("format", "png") == "tif":
            data = await asyncio.to_thread(_geotiff, vals, gt, pyr.crs, spec.op)
            return Response(data, media_type="image/tiff", headers=headers)
        cmap = spec.colormap()
        png = colormap.encode_png(colormap.quantise(spec.op, vals, cmap), colormap.palette(cmap["name"]))
        return Response(png, media_type="image/png", headers=headers)

    if WEB.exists():
        app.mount("/viewer", StaticFiles(directory=WEB, html=True), name="viewer")
    return app


async def _disconnected(request):
    """Return when the client disconnects (a GET has no body, so the next ASGI message is the disconnect)."""
    while True:
        msg = await request.receive()
        if msg["type"] == "http.disconnect":
            return


def _geotiff(vals, gt, crs, op):
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.transform import Affine
    nod = 0 if op == "hillshade" else -9999.0
    with MemoryFile() as mem:
        with mem.open(driver="GTiff", width=vals.shape[1], height=vals.shape[0], count=1, dtype=vals.dtype.name,
                      crs=crs or None, transform=Affine.from_gdal(*gt), nodata=nod, compress="deflate") as ds:
            ds.write(np.ascontiguousarray(vals), 1)
        return mem.read()


app = create_app()
