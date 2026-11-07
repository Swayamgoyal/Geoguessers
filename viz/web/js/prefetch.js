// Speculative neighbour prefetch: after a commit, load the 8 view-sized rectangles around the view (NW, N, NE, W, E,
// SW, S, SE) at the committed level, at low priority, at most `maxInFlight` at a time (the browser has 6 connections
// per origin; this always leaves 4 for the foreground). Order: in the direction of the last pan first, then cardinals
// before corners, then nearer before farther. The ring recentres when the camera moves more than 25% of the view off
// the committed centre (at most once per 100 ms); ring requests no longer in the new ring are aborted.

import { tileRect, tilesForBBox } from "./levels.js";

const DIRS = [[0, 1, "N"], [0, -1, "S"], [-1, 0, "W"], [1, 0, "E"], [-1, 1, "NW"], [1, 1, "NE"], [-1, -1, "SW"],
              [1, -1, "SE"]];

// Ring tiles for a committed view (bbox) at `level`, ordered; excludes `skip(tx, ty)` (visible / cached / in flight).
// velocity = [vx, vy] in world units per second (0, 0 if unknown). Pure: used by the browser and by tests.
export function ringTiles(level, bbox, velocity = [0, 0], skip = () => false, maxTiles = 150, order = "velocity-first") {
  const w = bbox.x1 - bbox.x0, h = bbox.y1 - bbox.y0;
  const cx = (bbox.x0 + bbox.x1) / 2, cy = (bbox.y0 + bbox.y1) / 2;
  const vis = new Set(tilesForBBox(level, bbox).map((t) => t.join(",")));
  const seen = new Set();
  const vn = Math.hypot(velocity[0], velocity[1]);
  const scored = [];
  for (const [dx, dy, name] of DIRS) {
    const cardinal = dx === 0 || dy === 0;
    const rect = { x0: bbox.x0 + dx * w, x1: bbox.x1 + dx * w, y0: bbox.y0 + dy * h, y1: bbox.y1 + dy * h };
    const along = vn > 0 ? (dx * velocity[0] + dy * velocity[1]) / (vn * Math.hypot(dx, dy)) : 0;
    for (const t of tilesForBBox(level, rect)) {
      const k = t.join(",");
      if (vis.has(k) || seen.has(k) || skip(t[0], t[1])) continue;
      seen.add(k);
      const r = tileRect(level, t[0], t[1]);
      const dist = Math.hypot((r.x0 + r.x1) / 2 - cx, (r.y0 + r.y1) / 2 - cy);
      scored.push({ t, dir: name, along, cardinal, dist });
    }
  }
  scored.sort((p, q) =>
    (order === "velocity-first" ? q.along - p.along : 0) ||
    (q.cardinal - p.cardinal) || (p.dist - q.dist));
  let out = scored;
  if (out.length > maxTiles) out = out.filter((s) => s.cardinal);   // HiDPI / huge views: cardinals only
  return out.slice(0, maxTiles).map((s) => s.t);
}

export class Prefetcher {
  constructor(viewer, policy) {
    this.v = viewer;
    this.p = policy;
    this.queue = [];
    this.inflight = new Map();      // key -> AbortController
    this.committed = null;          // {bbox, level, cx, cy}
    this.lastRecentre = 0;
    this.backoffUntil = 0;
    this.enabled = policy.enabled;
    this.pending = false;          // a rebuild was skipped and should run when prefetch is allowed again
  }

  active() {
    return this.enabled && this.p.enabled && this.v.params.mode !== "exact" && !document.hidden &&
           performance.now() >= this.backoffUntil;
  }

  // called when every visible tile of a commit has arrived
  start(bbox, level) {
    this.committed = { bbox, level, cx: (bbox.x0 + bbox.x1) / 2, cy: (bbox.y0 + bbox.y1) / 2 };
    this.rebuild();
  }

  rebuild() {
    if (!this.committed) return this.abortAll();
    if (!this.active()) {          // disabled, hidden, exact mode or backing off: retry when allowed again
      this.abortAll();
      this.pending = true;
      return;
    }
    this.pending = false;
    const lvl = this.v.levelInfo(this.committed.level);
    const tiles = ringTiles(lvl, this.committed.bbox, this.v.velocity, (tx, ty) => {
      const key = this.v.key(this.committed.level, tx, ty);
      return this.v.cache.has(key) || this.v.isInflightFg(key);
    }, this.p.ringMaxTiles, this.p.order);
    const keep = new Set(tiles.map((t) => this.v.key(this.committed.level, t[0], t[1])));
    for (const [key, ctl] of this.inflight) if (!keep.has(key)) { ctl.abort(); this.inflight.delete(key); }
    this.queue = tiles.filter((t) => !this.inflight.has(this.v.key(this.committed.level, t[0], t[1])));
    this.pump();
  }

  // every frame: recentre the ring if the camera moved far enough from the committed centre
  onFrame(cam) {
    if (!this.committed) return;
    if (this.pending && this.active() && this.v.settledLevelValid()) this.rebuild();
    const fx = Math.abs(cam.cx - this.committed.cx) / (cam.width * cam.mpp);
    const fy = Math.abs(cam.cy - this.committed.cy) / (cam.height * cam.mpp);
    const now = performance.now();
    if ((fx > this.p.recentreFraction || fy > this.p.recentreFraction) && now - this.lastRecentre > this.p.recentreMinMs &&
        this.v.settledLevelValid()) {
      this.lastRecentre = now;
      const b = cam.bbox();
      this.committed = { ...this.committed, bbox: b, cx: cam.cx, cy: cam.cy };
      this.rebuild();
    }
  }

  pump() {
    while (this.active() && this.inflight.size < this.p.maxInFlight && this.queue.length) {
      const [tx, ty] = this.queue.shift();
      const level = this.committed.level;
      const key = this.v.key(level, tx, ty);
      if (this.v.cache.has(key) || this.inflight.has(key)) continue;
      const ctl = new AbortController();
      this.inflight.set(key, ctl);
      const timeout = setTimeout(() => ctl.abort(), this.p.requestTimeoutMs || 10000);
      this.v.fetchTile(level, tx, ty, "bg", ctl).then((status) => {
        if (status === "busy") {         // server paused prefetch (low free memory): back off, retry later
          this.backoffUntil = performance.now() + this.p.backoffMs;
          this.abortAll();
          this.pending = true;
        }
      }).finally(() => {
        clearTimeout(timeout);
        this.inflight.delete(key);
        this.pump();
      });
    }
  }

  // foreground latency feedback: back off when the foreground is slow
  noteForeground(samples) {
    if (samples.length < this.p.backoffWindow) return;
    const s = [...samples].sort((a, b) => a - b);
    const p95 = s[Math.floor(0.95 * (s.length - 1))];
    if (p95 > this.p.backoffP95Ms) {
      this.backoffUntil = performance.now() + this.p.backoffMs;
      this.abortAll();
    }
  }

  abortAll() {
    for (const ctl of this.inflight.values()) ctl.abort();
    this.inflight.clear();
    this.queue = [];
  }
}
