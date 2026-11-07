"""Virtual client for E6: a Python port of the web viewer's policy (viz/web/js), replaying a trace against the live
tile server in real time and logging every request, frame and gesture.

It reads viz/web/policy.json, the same file as the browser, so the two cannot drift apart. It mirrors these browser
modules:
    levels.js   choose_level, tile_rect, tiles_for_bbox, tile_at, centre_out
    camera.js   Camera
    tileCache.js Cache (byte-budget LRU, other levels evicted first)
    prefetch.js ring_tiles, Prefetcher (velocity-first ring, max in flight, recentre, back-off)
    viewer.js   commit, request_visible, the frame loop, gestures (trailing debounce, generations, aborts)
Aborts cancel the request task, which closes the connection; the server sees the disconnect, as with
AbortController in the browser. HTTP/1.1 with at most 6 connections, like a browser per origin. Frames run at
60 Hz. Bitmap decoding is not simulated: a tile counts as drawn on the first frame after its response arrives.

    trace = json.load(open("bench/traces/pan-line-1.json"))
    out = run(run_trace("http://127.0.0.1:8765", info, "chamoli_2m", {"op": "hillshade"}, trace))
    out["requests"], out["frames"], out["gestures"], out["summary"]
"""
import asyncio
import ctypes
import json
import math
import sys
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
POLICY = REPO / "viz" / "web" / "policy.json"
TILE = 512
FPS = 60
TILE_BYTES = TILE * TILE * 4            # decoded RGBA bitmap, as in the browser cache
PARAM_KEYS = ("op", "method", "mode", "cmap", "vmin", "vmax", "azimuth", "altitude", "zfactor")
DIRS = [(0, 1, "N"), (0, -1, "S"), (-1, 0, "W"), (1, 0, "E"), (-1, 1, "NW"), (1, 1, "NE"), (-1, -1, "SW"),
        (1, -1, "SE")]


class PreciseLoop(asyncio.SelectorEventLoop if sys.platform != "win32" else asyncio.ProactorEventLoop):
    """Event loop on the high-resolution clock. On Windows with Python 3.12 the default loop clock is
    GetTickCount64 (15.6 ms steps) and the loop runs timers up to one step early, so a 200 ms debounce could fire
    after 185 ms. Here timers use perf_counter and 1 ms resolution (with timeBeginPeriod(1) the waits are ~1 ms)."""

    def __init__(self):
        super().__init__()
        self._clock_resolution = 1e-3

    def time(self):
        return time.perf_counter()


def run(coro):
    """asyncio.run on the precise loop; use this to run run_trace()."""
    return asyncio.run(coro, loop_factory=PreciseLoop)


def load_policy(overrides=None):
    """policy.json with nested overrides applied, e.g. {"debounceMs": 0, "prefetch": {"enabled": False}}."""
    p = json.loads(POLICY.read_text())
    for k, v in (overrides or {}).items():
        if isinstance(v, dict):
            p[k] = {**p.get(k, {}), **v}
        else:
            p[k] = v
    return p


# ---------------------------------------------------------------- levels.js
def choose_level(levels, s, prev=None, hysteresis=0.1):
    def pick(v):
        k = 0
        for lv in levels:
            if lv["res"] <= v:
                k = lv["k"]
        return k
    if prev is not None and pick(s / (1 + hysteresis)) <= prev <= pick(s * (1 + hysteresis)):
        return prev
    return pick(s)


def tile_rect(lv, tx, ty):
    a, _, c, _, e, f = lv["transform"]
    x0 = c + a * TILE * tx
    ytop = f + e * TILE * ty
    return x0, ytop + e * TILE, x0 + a * TILE, ytop          # x0, y0, x1, y1


def tiles_for_bbox(lv, bbox):
    a, _, c, _, e, f = lv["transform"]
    tw, th = a * TILE, -e * TILE
    x0, y0, x1, y1 = bbox
    tx0 = max(0, math.floor((x0 - c) / tw))
    tx1 = min(lv["ntx"] - 1, math.floor((x1 - c) / tw - 1e-9))
    ty0 = max(0, math.floor((f - y1) / th))
    ty1 = min(lv["nty"] - 1, math.floor((f - y0) / th - 1e-9))
    return [(tx, ty) for ty in range(ty0, ty1 + 1) for tx in range(tx0, tx1 + 1)]


def tile_at(lv, x, y):
    a, _, c, _, e, f = lv["transform"]
    tx = math.floor((x - c) / (a * TILE))
    ty = math.floor((f - y) / (-e * TILE))
    if tx < 0 or ty < 0 or tx >= lv["ntx"] or ty >= lv["nty"]:
        return None
    return tx, ty


def centre_out(lv, tiles, cx, cy):
    def d(t):
        x0, y0, x1, y1 = tile_rect(lv, *t)
        return ((x0 + x1) / 2 - cx) ** 2 + ((y0 + y1) / 2 - cy) ** 2
    return sorted(tiles, key=d)


def overlap(r, bbox):
    w = min(r[2], bbox[2]) - max(r[0], bbox[0])
    h = min(r[3], bbox[3]) - max(r[1], bbox[1])
    return max(w, 0.0) * max(h, 0.0)


# ---------------------------------------------------------------- camera.js
class Camera:
    def __init__(self, width, height):
        self.cx = self.cy = 0.0
        self.mpp = 1.0
        self.width, self.height = width, height
        self.min_mpp, self.max_mpp = 0.0, math.inf

    def pixel_size(self, dpr=1, dpr_cap=1):
        return self.mpp / min(dpr, dpr_cap)

    def bbox(self):
        hw, hh = self.width / 2 * self.mpp, self.height / 2 * self.mpp
        return self.cx - hw, self.cy - hh, self.cx + hw, self.cy + hh

    def to_world(self, sx, sy):
        return self.cx + (sx - self.width / 2) * self.mpp, self.cy - (sy - self.height / 2) * self.mpp

    def clamp(self, m):
        return min(self.max_mpp, max(self.min_mpp, m))

    def zoom_at(self, factor, sx, sy):
        wx, wy = self.to_world(sx, sy)
        self.mpp = self.clamp(self.mpp * factor)
        self.cx = wx - (sx - self.width / 2) * self.mpp
        self.cy = wy + (sy - self.height / 2) * self.mpp

    def pan_by(self, dsx, dsy):
        self.cx -= dsx * self.mpp
        self.cy += dsy * self.mpp

    def fit(self, b, margin=1.0):
        self.cx, self.cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        self.mpp = self.clamp(margin * max((b[2] - b[0]) / self.width, (b[3] - b[1]) / self.height))

    def state(self):
        return self.cx, self.cy, self.mpp

    def set(self, s):
        self.cx, self.cy = s[0], s[1]
        self.mpp = self.clamp(s[2])


# ---------------------------------------------------------------- tileCache.js
class Cache:
    def __init__(self, budget_mib, clock):
        self.budget = budget_mib * 2**20
        self.map = {}       # key -> dict(level, bytes, origin, last, drawn, fetched, empty)
        self.bytes = 0
        self.current_level = 0
        self.clock = clock
        self.stats = {"evictions": 0, "prefetched": 0, "prefetched_drawn": 0}

    def has(self, key):
        return key in self.map

    def get(self, key):
        e = self.map.get(key)
        if e is not None:
            e["last"] = self.clock()
        return e

    def put(self, key, level, origin, empty):
        if key in self.map:
            return
        b = 0 if empty else TILE_BYTES
        now = self.clock()
        self.map[key] = {"level": level, "bytes": b, "origin": origin, "last": now, "fetched": now, "drawn": None,
                         "empty": empty}
        self.bytes += b
        if origin == "bg":
            self.stats["prefetched"] += 1
        self.evict()

    def mark_drawn(self, e):
        if e["drawn"] is None:
            e["drawn"] = self.clock()
            if e["origin"] == "bg":
                self.stats["prefetched_drawn"] += 1

    def evict(self):
        if self.bytes <= self.budget:
            return
        order = sorted(self.map.items(), key=lambda kv: (kv[1]["level"] == self.current_level, kv[1]["last"]))
        for key, e in order:
            if self.bytes <= self.budget * 0.9:
                break
            self.bytes -= e["bytes"]
            del self.map[key]
            self.stats["evictions"] += 1


# ---------------------------------------------------------------- prefetch.js
def ring_tiles(lv, bbox, velocity=(0.0, 0.0), skip=lambda tx, ty: False, max_tiles=150, order="velocity-first"):
    x0, y0, x1, y1 = bbox
    w, h = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    vis = set(tiles_for_bbox(lv, bbox))
    seen = set()
    vn = math.hypot(*velocity)
    scored = []
    for dx, dy, _ in DIRS:
        cardinal = dx == 0 or dy == 0
        rect = (x0 + dx * w, y0 + dy * h, x1 + dx * w, y1 + dy * h)
        along = (dx * velocity[0] + dy * velocity[1]) / (vn * math.hypot(dx, dy)) if vn > 0 else 0.0
        for t in tiles_for_bbox(lv, rect):
            if t in vis or t in seen or skip(*t):
                continue
            seen.add(t)
            r = tile_rect(lv, *t)
            dist = math.hypot((r[0] + r[2]) / 2 - cx, (r[1] + r[3]) / 2 - cy)
            scored.append((t, along, cardinal, dist))
    if order == "velocity-first":
        scored.sort(key=lambda s: (-s[1], -s[2], s[3]))
    else:
        scored.sort(key=lambda s: (-s[2], s[3]))
    if len(scored) > max_tiles:
        scored = [s for s in scored if s[2]]
    return [s[0] for s in scored[:max_tiles]]


class Prefetcher:
    def __init__(self, viewer, policy):
        self.v, self.p = viewer, policy
        self.queue = []
        self.inflight = {}          # key -> task
        self.committed = None       # (bbox, level, cx, cy)
        self.last_recentre = -1e9
        self.backoff_until = 0.0
        self.enabled = policy["enabled"]
        self.pending = False
        self.ring = set()           # keys of the latest ring, kept even with prefetch off (for recall)
        self.backoffs = 0

    def active(self):
        return (self.enabled and self.p["enabled"] and self.v.params.get("mode") != "exact"
                and self.v.now() >= self.backoff_until)

    def start(self, bbox, level):
        self.committed = (bbox, level, (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
        self.rebuild()

    def _ring(self):
        bbox, level = self.committed[0], self.committed[1]
        lv = self.v.levels[level]
        return [(level, t) for t in ring_tiles(lv, bbox, self.v.velocity,
                                               lambda tx, ty: self.v.cache.has(self.v.key(level, tx, ty))
                                               or self.v.key(level, tx, ty) in self.v.fg_inflight,
                                               self.p["ringMaxTiles"], self.p["order"])]

    def rebuild(self):
        if self.committed is None:
            return self.abort_all()
        ring = self._ring()
        self.ring = {self.v.key(level, *t) for level, t in ring}
        if not self.active():
            self.abort_all()
            self.pending = True
            return
        self.pending = False
        for key in list(self.inflight):
            if key not in self.ring:
                self.inflight.pop(key).cancel()
        self.queue = [(level, t) for level, t in ring if self.v.key(level, *t) not in self.inflight]
        self.pump()

    def on_frame(self):
        if self.committed is None:
            return
        cam = self.v.camera
        if self.pending and self.active() and self.v.settled_level_valid():
            self.rebuild()
        fx = abs(cam.cx - self.committed[2]) / (cam.width * cam.mpp)
        fy = abs(cam.cy - self.committed[3]) / (cam.height * cam.mpp)
        now = self.v.now()
        if ((fx > self.p["recentreFraction"] or fy > self.p["recentreFraction"])
                and (now - self.last_recentre) * 1000 > self.p["recentreMinMs"] and self.v.settled_level_valid()):
            self.last_recentre = now
            self.committed = (cam.bbox(), self.committed[1], cam.cx, cam.cy)
            self.rebuild()

    def pump(self):
        while self.active() and len(self.inflight) < self.p["maxInFlight"] and self.queue:
            level, (tx, ty) = self.queue.pop(0)
            key = self.v.key(level, tx, ty)
            if self.v.cache.has(key) or key in self.inflight:
                continue
            self.inflight[key] = asyncio.ensure_future(self._one(key, level, tx, ty))

    async def _one(self, key, level, tx, ty):
        try:
            status = await asyncio.wait_for(self.v.fetch_tile(level, tx, ty, "bg"),
                                            self.p.get("requestTimeoutMs", 10000) / 1000)
            if status == "busy":
                self.backoff_until = self.v.now() + self.p["backoffMs"] / 1000
                self.backoffs += 1
                self.abort_all(keep=key)
                self.pending = True
        except asyncio.TimeoutError:
            pass
        finally:
            if self.inflight.get(key) is asyncio.current_task():
                del self.inflight[key]
            self.pump()

    def note_foreground(self, samples):
        if len(samples) < self.p["backoffWindow"]:
            return
        s = sorted(samples)
        if s[int(0.95 * (len(s) - 1))] > self.p["backoffP95Ms"]:
            self.backoff_until = self.v.now() + self.p["backoffMs"] / 1000
            self.backoffs += 1
            self.abort_all()

    def abort_all(self, keep=None):
        for key, task in list(self.inflight.items()):
            if key != keep:
                task.cancel()
        self.inflight = {k: t for k, t in self.inflight.items() if k == keep}
        self.queue = []

    def idle(self):
        return not self.inflight and not self.queue


# ---------------------------------------------------------------- viewer.js
class VirtualViewer:
    def __init__(self, http, base, info, dataset, params, policy, view=(1600, 900), session="v"):
        self.http, self.base, self.info, self.dataset = http, base.rstrip("/"), info, dataset
        self.params = {k: v for k, v in params.items() if v not in (None, "")}
        self.policy = policy
        self.session = session
        self.camera = Camera(*view)
        self.t0 = time.perf_counter()
        self.cache = Cache(policy["clientCacheMiB"], self.now)
        self.prefetch = Prefetcher(self, policy["prefetch"])
        self.level = None
        self.gen = 0
        self.fg_inflight = {}       # key -> task
        self.velocity = (0.0, 0.0)
        self.fg_samples = []
        self.gesture_active = False
        self.timer = None
        self.gesture_start = 0.0
        self.commits = 0
        self.last_commit_at = None
        self.complete_at = None
        self._pending_visible = None
        self._last_cam = None
        self._last_t = None
        self._prev_visible = (None, set())
        self.phase = "init"
        self.gesture = -1           # index of the trace gesture the client is in (-1 = none yet)
        self.requests, self.frames, self.gestures = [], [], []
        self.qs = "&".join(f"{k}={self.params[k]}" for k in PARAM_KEYS if k in self.params)
        ds = info["datasets"][dataset]
        self.version = ds["version"]
        l, b, r, t = ds["bounds"]
        self.camera.min_mpp = ds["levels"][0]["res"] / policy["maxMagnification"]
        self.camera.max_mpp = 4 * max((r - l) / self.camera.width, (t - b) / self.camera.height)
        self.camera.fit((l, b, r, t), 1.05)
        self.counts = {"pan_new": 0, "pan_hits": 0, "pan_misses": 0, "pan_misses_in_ring": 0}

    @property
    def levels(self):
        return self.info["datasets"][self.dataset]["levels"]

    def now(self):
        return time.perf_counter() - self.t0

    def key(self, level, tx, ty):
        return (level, tx, ty)

    # -------------------------------------------------- gestures
    def zoom_at(self, factor, sx, sy):
        self.camera.zoom_at(factor, sx, sy)
        self.schedule_commit()

    def pan_by(self, dx, dy):
        self.camera.pan_by(dx, dy)

    def begin_gesture(self):
        if self.gesture_active:
            return
        self.gesture_active = True
        self.gesture_start = self.now()
        self.prefetch.abort_all()
        self.post_gen(cancel_bg=True)

    def schedule_commit(self):
        self.begin_gesture()
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        d = self.policy["debounceMs"]
        mx = self.policy.get("maxWaitMs") or 0
        if d <= 0 or (mx and (self.now() - self.gesture_start) * 1000 >= mx):
            return self.commit()
        self.timer = asyncio.get_running_loop().call_later(d / 1000, self.commit)

    def post_gen(self, cancel_bg=False):
        async def go(gen):
            try:
                await self.http.post(f"{self.base}/session/{self.session}/gen", json={"gen": gen, "cancel_bg": cancel_bg})
            except httpx.HTTPError:
                pass
        asyncio.ensure_future(go(self.gen))

    # -------------------------------------------------- commit and requests
    def commit(self):
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        self.gesture_active = False
        cam = self.camera
        k = choose_level(self.levels, cam.pixel_size(1, self.policy["dprCap"]), self.level, self.policy["hysteresis"])
        self.gen += 1
        self.level = k
        self.cache.current_level = k
        self.commits += 1
        self.last_commit_at = self.now()
        self.complete_at = None
        bbox = cam.bbox()
        visible = centre_out(self.levels[k], tiles_for_bbox(self.levels[k], bbox), cam.cx, cam.cy)
        keys = {self.key(k, *t) for t in visible}
        for key in [kk for kk in self.fg_inflight if kk not in keys]:
            self.fg_inflight.pop(key).cancel()
        self.request_visible(visible, from_commit=True)

    def request_visible(self, visible, from_commit=False):
        k = self.level
        waits = []
        for i, (tx, ty) in enumerate(visible):
            key = self.key(k, tx, ty)
            if self.cache.has(key):
                continue
            task = self.fg_inflight.get(key)
            if task is None:
                task = asyncio.ensure_future(self.fetch_tile(k, tx, ty, "fg", i))
                self.fg_inflight[key] = task
            waits.append(task)
        if from_commit:
            gen, bbox = self.gen, self.camera.bbox()
            self._pending_visible = gen

            async def when_done():
                if waits:
                    await asyncio.wait(waits)
                if self._pending_visible != gen or self.gen != gen:
                    return
                self.complete_at = self.now()
                self.prefetch.start(bbox, k)
            asyncio.ensure_future(when_done())

    async def fetch_tile(self, level, tx, ty, priority, order=0):
        key = self.key(level, tx, ty)
        url = (f"{self.base}/tiles/{self.dataset}/{level}/{tx}/{ty}.png?{self.qs}&v={self.version}")
        rec = {"phase": self.phase, "gesture": self.gesture, "gen": self.gen, "priority": priority, "level": level,
               "tx": tx, "ty": ty, "t_start": self.now(), "status": "", "tier": "", "bytes": 0, "cancel_stage": ""}
        self.requests.append(rec)
        try:
            r = await self.http.get(url, headers={"X-Session": self.session, "X-Gen": str(self.gen),
                                                  "X-Priority": priority, "X-Order": str(order)})
        except asyncio.CancelledError:
            rec.update(status="aborted", t_end=self.now())
            if priority == "fg" and self.fg_inflight.get(key) is asyncio.current_task():
                del self.fg_inflight[key]
            raise
        except httpx.HTTPError as e:
            rec.update(status="error", t_end=self.now(), error=type(e).__name__)
            if priority == "fg":
                self.fg_inflight.pop(key, None)
            return "error"
        rec["t_end"] = self.now()
        rec["ms"] = (rec["t_end"] - rec["t_start"]) * 1000
        if priority == "fg" and self.fg_inflight.get(key) is asyncio.current_task():
            del self.fg_inflight[key]
        for part in r.headers.get("server-timing", "").split(","):
            name, *rest = part.strip().split(";")
            for kv in rest:
                kk, _, vv = kv.partition("=")
                if kk == "dur":
                    rec[name] = float(vv)
                elif kk == "desc":
                    rec["tier"] = vv.strip('"')
        if r.status_code in (200, 204):
            rec["status"] = "ok" if r.status_code == 200 else "empty"
            rec["bytes"] = len(r.content)
            self.cache.put(key, level, priority, r.status_code == 204)
            if priority == "fg":
                self.fg_samples.append(rec["ms"])
                if len(self.fg_samples) > self.policy["prefetch"]["backoffWindow"]:
                    self.fg_samples.pop(0)
                self.prefetch.note_foreground(self.fg_samples)
            return rec["status"]
        if r.status_code in (409, 499):
            rec.update(status="superseded" if r.status_code == 409 else "gone",
                       cancel_stage=r.headers.get("x-cancelled", ""))
            return "cancelled"
        if r.status_code == 503:
            rec["status"] = "busy"
            return "busy"
        rec["status"] = f"http{r.status_code}"
        return "error"

    def settled_level_valid(self):
        if self.level is None or self.gesture_active:
            return False
        s = self.camera.pixel_size(1, self.policy["dprCap"])
        return choose_level(self.levels, s, self.level, self.policy["hysteresis"]) == self.level

    # -------------------------------------------------- frame loop
    def frame(self):
        cam = self.camera
        t = self.now()
        moved = False
        if self._last_cam is not None:
            dt = max(t - self._last_t, 1e-3)
            vx, vy = (cam.cx - self._last_cam[0]) / dt, (cam.cy - self._last_cam[1]) / dt
            self.velocity = (0.8 * self.velocity[0] + 0.2 * vx, 0.8 * self.velocity[1] + 0.2 * vy)
            moved = cam.state() != self._last_cam
            if moved and not self.gesture_active and self.level is not None:
                lv = self.levels[self.level]
                self.request_visible(centre_out(lv, tiles_for_bbox(lv, cam.bbox()), cam.cx, cam.cy))
        self._last_cam, self._last_t = cam.state(), t
        self.prefetch.on_frame()
        return self.draw(t, moved)

    def draw(self, t, moved):
        """What the browser would draw (tileLayer.js), measured against the level the camera needs now."""
        cam, levels = self.camera, self.levels
        bbox = cam.bbox()
        area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
        k = self.level
        ideal = choose_level(levels, cam.pixel_size(1, self.policy["dprCap"]), k, self.policy["hysteresis"])
        row = {"t": t, "level": k, "ideal": ideal, "gesture_active": int(self.gesture_active)}
        # committed level: drawn tiles (marks prefetch use) and pan hit rate
        exact = vis_n = 0
        if k is not None:
            lv = levels[k]
            vis = tiles_for_bbox(lv, bbox)
            vis_n = len(vis)
            keys = {self.key(k, *tt) for tt in vis}
            prev_level, prev = self._prev_visible
            settled = not self.gesture_active and ideal == k and prev_level == k and moved
            for key in keys:
                e = self.cache.get(key)
                if e is not None:
                    exact += 1
                    self.cache.mark_drawn(e)
                if settled and key not in prev:
                    self.counts["pan_new"] += 1
                    if e is not None:
                        self.counts["pan_hits"] += 1
                    else:
                        self.counts["pan_misses"] += 1
                        if key in self.prefetch.ring:
                            self.counts["pan_misses_in_ring"] += 1
            self._prev_visible = (k, keys)
        row.update(visible=vis_n, exact=exact)
        # area shares at the ideal level: exact tile / fallback from another cached level / overview only
        lvi = levels[ideal]
        a_exact = a_fall = a_over = 0.0
        for tt in tiles_for_bbox(lvi, bbox):
            r = tile_rect(lvi, *tt)
            a = overlap(r, bbox)
            if a <= 0:
                continue
            if self.cache.has(self.key(ideal, *tt)):
                a_exact += a
            elif self._fallback(ideal, r):
                a_fall += a
            else:
                a_over += a
        tot = a_exact + a_fall + a_over
        row.update(exact_share=a_exact / tot if tot else 1.0, fallback_share=a_fall / tot if tot else 0.0,
                   overview_share=a_over / tot if tot else 0.0, data_share=tot / area if area else 0.0,
                   fg_inflight=len(self.fg_inflight), bg_inflight=len(self.prefetch.inflight),
                   cache_mib=self.cache.bytes / 2**20)
        return row

    def _fallback(self, k, cell):
        levels = self.levels
        mx, my = (cell[0] + cell[2]) / 2, (cell[1] + cell[3]) / 2
        for j in range(k + 1, len(levels)):
            t = tile_at(levels[j], mx, my)
            if t is None:
                break
            if self.cache.has(self.key(j, *t)):
                return True
        if k > 0:
            return any(self.cache.has(self.key(k - 1, *t)) for t in tiles_for_bbox(levels[k - 1], cell))
        return False


# ---------------------------------------------------------------- trace replay
def place(viewer, start):
    """Initial camera from a trace's start: {"fit": true} or {"u", "v", "level"} (offset from the data centre in
    view widths at that level; the pixel size sits in the middle of the level, res·√2)."""
    cam = viewer.camera
    ds = viewer.info["datasets"][viewer.dataset]
    l, b, r, t = ds["bounds"]
    if start.get("fit"):
        cam.fit((l, b, r, t), 1.05)
        return
    lv = ds["levels"][min(int(start["level"]), len(ds["levels"]) - 1)]
    cam.mpp = cam.clamp(lv["res"] * math.sqrt(2))
    w = cam.width * cam.mpp
    cam.cx = (l + r) / 2 + start.get("u", 0) * w
    cam.cy = (b + t) / 2 + start.get("v", 0) * w


async def _settle(v, timeout):
    t0 = v.now()
    while v.now() - t0 < timeout:
        if v.complete_at is not None and not v.gesture_active and v.prefetch.idle():
            return True
        await asyncio.sleep(0.02)
    return False


async def _animate(v, target, ms=350):
    """viewer.animateTo: ease-in-out over `ms`, one commit at the end, no debounce timer."""
    a = v.camera.state()
    if v.timer is not None:
        v.timer.cancel()
        v.timer = None
    v.begin_gesture()
    t0 = v.now()
    while True:
        u = min(1.0, (v.now() - t0) * 1000 / ms)
        e = 2 * u * u if u < 0.5 else 1 - (-2 * u + 2) ** 2 / 2
        v.camera.set((a[0] + (target[0] - a[0]) * e, a[1] + (target[1] - a[1]) * e,
                      math.exp(math.log(a[2]) + (math.log(target[2]) - math.log(a[2])) * e)))
        if u >= 1:
            break
        await asyncio.sleep(1 / FPS)
    v.commit()


def _box_target(v, x0, y0, x1, y1):
    cam = v.camera
    wx0, wy0 = cam.to_world(min(x0, x1), max(y0, y1))
    wx1, wy1 = cam.to_world(max(x0, x1), min(y0, y1))
    m = cam.clamp(max((wx1 - wx0) / cam.width, (wy1 - wy0) / cam.height))
    return (wx0 + wx1) / 2, (wy0 + wy1) / 2, m


async def run_trace(base, info, dataset, params, trace, policy=None, settle_s=8.0, tail_s=4.0, on_ready=None):
    """Replay `trace` and return {"requests", "frames", "gestures", "summary"}. `on_ready()` (optional, awaited) runs
    after the initial view and its prefetch ring have loaded, just before the trace clock starts (E6 snapshots
    server counters there)."""
    policy = policy or load_policy()
    if sys.platform == "win32":
        ctypes.windll.winmm.timeBeginPeriod(1)     # 1 ms timers for the 60 Hz clock (as browsers do)
    try:
        return await _run(base, info, dataset, params, trace, policy, settle_s, tail_s, on_ready)
    finally:
        if sys.platform == "win32":
            ctypes.windll.winmm.timeEndPeriod(1)


async def _run(base, info, dataset, params, trace, policy, settle_s, tail_s, on_ready):
    limits = httpx.Limits(max_connections=6, max_keepalive_connections=6)
    async with httpx.AsyncClient(limits=limits, timeout=httpx.Timeout(30.0, pool=60.0), trust_env=False) as http:
        v = VirtualViewer(http, base, info, dataset, params, policy, tuple(trace.get("view", (1600, 900))),
                          session=f"e6{int(time.time() * 1000) % 10**8}")
        try:                                  # the browser loads the overview image before the first commit
            await http.get(f"{v.base}/overview/{dataset}.png?{v.qs}")
        except httpx.HTTPError:
            pass
        place(v, trace["start"])
        v.commit()
        frames_task = asyncio.ensure_future(_frames(v))
        ready = await _settle(v, settle_s)
        if on_ready is not None:
            await on_ready()
        v.phase = "trace"
        base_t = v.now()
        v.counts = {k: 0 for k in v.counts}
        pf0 = dict(v.cache.stats)
        n_req0 = len(v.requests)
        v.frames.clear()
        gest = {}
        for ev in trace["events"]:
            t_ev = base_t + ev[0]
            while v.now() < t_ev:
                await asyncio.sleep(max(0.0, min(t_ev - v.now(), 1 / FPS)))
            kind = ev[1]
            if kind == "pan":
                if not v.gesture_active:
                    v.gesture = -1          # requests from here on belong to the pan, not to the last zoom
                v.pan_by(ev[2], ev[3])
            elif kind == "wheel":
                g = ev[5]
                if g not in gest:
                    v.gesture = g
                    gest[g] = {"gesture": g, "kind": "wheel", "t_first": v.now() - base_t, "ticks": 0,
                               "level_before": v.level, "mpp_before": v.camera.mpp}
                gest[g]["ticks"] += 1
                gest[g]["commits_before_last"] = v.commits
                gest[g]["t_last"] = v.now() - base_t
                v.zoom_at(ev[2], ev[3], ev[4])
            elif kind == "box":
                g = ev[6]
                v.gesture = g
                gest[g] = {"gesture": g, "kind": "box", "t_first": v.now() - base_t, "ticks": 1,
                           "level_before": v.level, "mpp_before": v.camera.mpp, "commits_before_last": v.commits}
                await _animate(v, _box_target(v, *ev[2:6]))
                gest[g]["t_last"] = v.now() - base_t
        t_end_events = v.now()
        while v.now() - t_end_events < tail_s:
            if v.complete_at is not None and not v.gesture_active and v.prefetch.idle() \
                    and v.now() - t_end_events > 0.3:
                break
            await asyncio.sleep(0.05)
        frames_task.cancel()
        for task in list(v.fg_inflight.values()) + list(v.prefetch.inflight.values()):
            task.cancel()
        await asyncio.sleep(0.05)

    frames = v.frames
    for f in frames:
        f["t"] -= base_t
    gestures = _gesture_metrics(v, gest, frames, base_t)
    reqs = []
    drawn = {k: e["drawn"] for k, e in v.cache.map.items()}
    for r in v.requests:
        r = dict(r)
        r["t_start"] -= base_t
        if "t_end" in r:
            r["t_end"] -= base_t
        d = drawn.get((r["level"], r["tx"], r["ty"]))
        r["drawn"] = int(r["status"] in ("ok", "empty") and d is not None)
        reqs.append(r)
    summary = _summary(v, reqs[n_req0:], frames, gestures, pf0, ready, trace)
    return {"requests": reqs, "frames": frames, "gestures": gestures, "summary": summary}


async def _frames(v):
    nxt = v.now()
    while True:
        row = v.frame()
        if v.phase == "trace":
            v.frames.append(row)
        nxt += 1 / FPS
        await asyncio.sleep(max(0.0, nxt - v.now()))


def _gesture_metrics(v, gest, frames, base_t):
    """Per trace gesture: time to first frame and to the complete view after its last tick, tiles requested."""
    out = []
    order = sorted(gest.values(), key=lambda g: g["t_first"])
    for i, g in enumerate(order):
        t_last = g["t_last"]
        t_next = order[i + 1]["t_first"] if i + 1 < len(order) else math.inf
        ttff = complete = None
        commit_t = None
        for f in frames:
            if f["t"] < t_last or f["t"] >= t_next:
                continue
            if f["gesture_active"]:
                continue
            if commit_t is None:
                commit_t = f["t"]
            if ttff is None and f["exact"] > 0:
                ttff = f["t"] - t_last
            if f["visible"] and f["exact"] == f["visible"] and f["level"] == f["ideal"]:
                complete = f["t"] - t_last
                break
        rq = [r for r in v.requests if r["phase"] == "trace" and r["gesture"] == g["gesture"] and r["priority"] == "fg"]
        st = [r["status"] for r in rq]
        out.append({**{k: g.get(k) for k in ("gesture", "kind", "t_first", "t_last", "ticks", "level_before")},
                    "duration": t_last - g["t_first"], "ttff_ms": None if ttff is None else 1000 * ttff,
                    "complete_ms": None if complete is None else 1000 * complete,
                    "fg_requested": len(rq), "fg_ok": st.count("ok") + st.count("empty"),
                    "fg_aborted": st.count("aborted"), "fg_superseded": st.count("superseded") + st.count("gone")})
    return out


def _pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    i = (len(xs) - 1) * q
    lo, hi = math.floor(i), math.ceil(i)
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


def _summary(v, reqs, frames, gestures, pf0, ready, trace):
    fg = [r for r in reqs if r["priority"] == "fg"]
    bg = [r for r in reqs if r["priority"] == "bg"]
    fg_ok = [r for r in fg if r["status"] in ("ok", "empty")]
    tiers = {}
    for r in fg_ok + [r for r in bg if r["status"] in ("ok", "empty")]:
        tiers[r["tier"] or "none"] = tiers.get(r["tier"] or "none", 0) + 1
    n = len(frames) or 1
    c = v.counts
    pf = v.cache.stats          # whole run: tiles prefetched for the first view may be drawn during the trace
    bg_used = [r for r in bg if r["status"] in ("ok", "empty")]
    wheel = [g for g in gestures if g["kind"] == "wheel"]
    return {
        "ready": ready, "frames": len(frames), "duration_s": frames[-1]["t"] if frames else 0,
        "fg_requests": len(fg), "fg_ok": len(fg_ok), "fg_aborted": sum(r["status"] == "aborted" for r in fg),
        "fg_superseded": sum(r["status"] in ("superseded", "gone") for r in fg),
        "fg_wasted": sum(r["status"] in ("ok", "empty") and not r["drawn"] for r in fg),
        "fg_p50_ms": _pct([r["ms"] for r in fg_ok], 0.5), "fg_p95_ms": _pct([r["ms"] for r in fg_ok], 0.95),
        "fg_server_p95_ms": _pct([sum(r.get(s, 0) for s in ("queue", "read", "decode", "kernel", "colormap",
                                                                "encode")) for r in fg_ok], 0.95),
        "bg_requests": len(bg), "bg_ok": len(bg_used), "bg_busy": sum(r["status"] == "busy" for r in bg),
        "bg_aborted": sum(r["status"] == "aborted" for r in bg),
        "tiers": tiers,
        "blank_area_time": 1 - sum(f["exact_share"] for f in frames) / n,
        "overview_area_time": sum(f["overview_share"] for f in frames) / n,
        "pan_new_tiles": c["pan_new"], "pan_hit_rate": c["pan_hits"] / c["pan_new"] if c["pan_new"] else None,
        "pan_misses": c["pan_misses"],
        "prefetch_recall": c["pan_misses_in_ring"] / c["pan_misses"] if c["pan_misses"] else None,
        "prefetched": pf["prefetched"], "prefetched_drawn": pf["prefetched_drawn"],
        "prefetch_precision": pf["prefetched_drawn"] / pf["prefetched"] if pf["prefetched"] else None,
        "prefetch_backoffs": v.prefetch.backoffs,
        "commits": v.commits, "gestures": len(gestures),
        "ttff_ms_median": _pct([g["ttff_ms"] for g in gestures], 0.5),
        "complete_ms_median": _pct([g["complete_ms"] for g in gestures], 0.5),
        "fg_per_wheel_gesture": (sum(g["fg_requested"] for g in wheel) / len(wheel)) if wheel else None,
        "client_cache_mib_max": max((f["cache_mib"] for f in frames), default=0),
    }


def demo():  # pragma: no cover - manual smoke run
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
    trace = json.loads(Path(sys.argv[2]).read_text())
    info = httpx.get(base + "/info", trust_env=False).json()
    out = run(run_trace(base, info, sys.argv[3] if len(sys.argv) > 3 else "chamoli_2m",
                                {"op": "hillshade", "method": "Horn", "mode": "auto"}, trace))
    print(json.dumps(out["summary"], indent=1))
    for g in out["gestures"]:
        print(g)


if __name__ == "__main__":
    demo()
