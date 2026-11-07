// Viewer core: a fast transient camera (redrawn every frame from cached bitmaps) and a settled state (level, visible
// tiles, generation) that changes only on commit and is the only thing that talks to the server.
//
// Zoom: every wheel / pinch tick moves the camera at once; the commit (level choice + tile requests) happens once,
// `debounceMs` after the last tick (trailing debounce). The first tick of a gesture aborts prefetch, here and on the
// server. Pan never waits: missing visible tiles of the settled level are requested at once, once per frame.
// Commit: gen + 1; foreground requests for tiles no longer visible are aborted; still-visible ones keep running;
// missing visible tiles are requested centre-out; when all have arrived, the prefetch ring starts.

import { Api, paramsKey } from "./api.js";
import { Camera } from "./camera.js";
import { centreOut, chooseLevel, tilesForBBox } from "./levels.js";
import { Prefetcher } from "./prefetch.js";
import { EMPTY, TileCache } from "./tileCache.js";
import { drawFrame } from "./tileLayer.js";

export class Viewer {
  constructor(canvas, policy, api = new Api()) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d", { alpha: false });
    this.policy = policy;
    this.api = api;
    this.camera = new Camera();
    this.cache = new TileCache(policy.clientCacheMiB);
    this.prefetch = new Prefetcher(this, policy.prefetch);
    this.dpr = window.devicePixelRatio || 1;
    this.info = null;
    this.dataset = null;
    this.params = { op: "hillshade", method: "Horn", mode: "auto" };
    this.level = null;           // settled level
    this.gen = 0;
    this.fgInflight = new Map(); // key -> {ctl, level}
    this.overview = null;
    this.box = null;             // rubber band in CSS px
    this.history = [];
    this.velocity = [0, 0];
    this.fgSamples = [];
    this.gestureActive = false;
    this.timer = null;
    this.gestureStart = 0;
    this.dirty = true;
    this.frameStats = { visible: 0, exact: 0, fallback: 0 };
    this.metrics = { commits: 0, requestedFg: 0, tilesFg: 0, tilesBg: 0, cancelled: 0, empty: 0, lastTile: null,
                     lastCommitAt: 0, firstFrameMs: null, completeMs: null };
    this.listeners = new Set();
    this._lastCam = null;
    this._lastT = performance.now();
    this._pendingVisible = null;
    this.resize();                                   // know the canvas size before fitting the first view
    new ResizeObserver(() => this.resize()).observe(canvas);
    document.addEventListener("visibilitychange", () => document.hidden ? this.prefetch.abortAll() : this.prefetch.rebuild());
    requestAnimationFrame((t) => this.frame(t));
  }

  onChange(fn) { this.listeners.add(fn); }
  emit() { for (const fn of this.listeners) fn(this); }

  async load(info, dataset) {
    this.info = info;
    await this.setDataset(dataset);
  }

  get pyr() { return this.info.datasets[this.dataset]; }
  get levels() { return this.pyr.levels; }
  levelInfo(k) { return this.levels[k]; }

  key(level, tx, ty) {
    return `${this.dataset}|${paramsKey(this.params)}|${level}|${tx}|${ty}`;
  }

  isInflightFg(key) { return this.fgInflight.has(key); }

  async setDataset(name) {
    this.dataset = name;
    this.resize();
    const [l, b, r, t] = this.pyr.bounds;
    const lv = this.levels;
    this.camera.minMpp = lv[0].res / this.policy.maxMagnification;
    this.camera.maxMpp = 4 * Math.max((r - l) / this.camera.width, (t - b) / this.camera.height);
    this.camera.fit({ x0: l, x1: r, y0: b, y1: t }, 1.05);
    this.history = [];
    await this.paramsChanged();
  }

  async setParams(p) {
    Object.assign(this.params, p);
    for (const k of Object.keys(this.params)) if (this.params[k] === "" || this.params[k] === null) delete this.params[k];
    await this.paramsChanged();
  }

  async paramsChanged() {
    this.gen++;
    this.abortFg(() => true);
    this.prefetch.abortAll();
    this.api.postGen(this.gen, true);
    this.level = null;
    this.overview = await this.api.overview(this.dataset, this.params);
    this.commit();
  }

  resize() {
    const r = this.canvas.getBoundingClientRect();
    this.dpr = window.devicePixelRatio || 1;
    this.canvas.width = Math.max(1, Math.round(r.width * this.dpr));
    this.canvas.height = Math.max(1, Math.round(r.height * this.dpr));
    this.camera.setSize(r.width, r.height);
    if (this.info && this.dataset) {
      const [l, b, rr, t] = this.pyr.bounds;
      this.camera.maxMpp = 4 * Math.max((rr - l) / r.width, (t - b) / r.height);
      this.scheduleCommit();
    }
    this.dirty = true;
  }

  // ------------------------------------------------------------ gestures
  zoomAt(factor, sx, sy) {
    this.camera.zoomAt(factor, sx, sy);
    this.dirty = true;
    this.scheduleCommit();
  }

  panBy(dx, dy) {
    this.camera.panBy(dx, dy);
    this.dirty = true;
  }

  // first event of a gesture: the level will probably change, so prefetch is dropped (here and on the server)
  beginGesture() {
    if (this.gestureActive) return;
    this.gestureActive = true;
    this.gestureStart = performance.now();
    this.prefetch.abortAll();
    this.api.postGen(this.gen, true);
  }

  scheduleCommit() {
    const now = performance.now();
    this.beginGesture();
    clearTimeout(this.timer);
    const max = this.policy.maxWaitMs;
    if (max && now - this.gestureStart >= max) return this.commit();
    this.timer = setTimeout(() => this.commit(), this.policy.debounceMs);
  }

  commitNow() {
    if (this.gestureActive) this.commit();
  }

  // ------------------------------------------------------------ commit and requests
  commit() {
    clearTimeout(this.timer);
    this.gestureActive = false;
    if (!this.info) return;
    const cam = this.camera;
    const s = cam.pixelSize(this.dpr, this.policy.dprCap);
    const k = chooseLevel(this.levels, s, this.level, this.policy.hysteresis);
    this.gen++;
    this.level = k;
    this.cache.currentLevel = k;
    this.metrics.commits++;
    this.metrics.lastCommitAt = performance.now();
    this.metrics.firstFrameMs = this.metrics.completeMs = null;
    performance.mark(`commit-${this.metrics.commits}`);
    const bbox = cam.bbox();
    const visible = centreOut(this.levels[k], tilesForBBox(this.levels[k], bbox), cam.cx, cam.cy);
    const keys = new Set(visible.map(([tx, ty]) => this.key(k, tx, ty)));
    this.abortFg((key) => !keys.has(key));
    this.requestVisible(visible, true);
    this.emit();
  }

  // request missing visible tiles at the settled level; `fromCommit`: start prefetch when all have arrived
  requestVisible(visible, fromCommit = false) {
    const k = this.level;
    const waits = [];
    visible.forEach(([tx, ty], i) => {
      const key = this.key(k, tx, ty);
      if (this.cache.has(key)) return;
      const existing = this.fgInflight.get(key);
      if (existing) { waits.push(existing.promise); return; }
      const ctl = new AbortController();
      this.metrics.requestedFg++;
      const p = this.fetchTile(k, tx, ty, "fg", ctl, i);
      this.fgInflight.set(key, { ctl, level: k, promise: p });
      waits.push(p);
    });
    if (fromCommit) {
      const gen = this.gen;
      const bbox = this.camera.bbox();
      this._pendingVisible = gen;
      Promise.allSettled(waits).then(() => {
        if (this._pendingVisible !== gen || this.gen !== gen) return;
        this.metrics.completeMs = performance.now() - this.metrics.lastCommitAt;
        performance.mark(`complete-${this.metrics.commits}`);
        this.prefetch.start(bbox, k);
        this.emit();
      });
    }
  }

  abortFg(pred) {
    for (const [key, f] of [...this.fgInflight.entries()]) {
      if (pred(key)) {
        f.ctl.abort();
        this.fgInflight.delete(key);
        this.metrics.cancelled++;
      }
    }
  }

  async fetchTile(level, tx, ty, priority, ctl, order = 0) {
    const key = this.key(level, tx, ty);
    const url = this.api.tileUrl(this.dataset, this.pyr.version, level, tx, ty, this.params);
    const r = await this.api.tile(url, { priority, gen: this.gen, order, signal: ctl.signal });
    if (priority === "fg") this.fgInflight.delete(key);
    if (r.status === "ok" || r.status === "empty") {
      this.cache.put(key, r.status === "ok" ? r.bitmap : EMPTY, level, priority);
      if (r.status === "empty") this.metrics.empty++;
      if (priority === "fg") {
        this.metrics.tilesFg++;
        this.fgSamples.push(r.ms);
        if (this.fgSamples.length > this.policy.prefetch.backoffWindow) this.fgSamples.shift();
        this.prefetch.noteForeground(this.fgSamples);
      } else {
        this.metrics.tilesBg++;
      }
      this.metrics.lastTile = { ms: r.ms, ...r.timing, priority };
      this.dirty = true;
    } else if (r.status === "cancelled") {
      this.metrics.cancelled++;
    }
    return r.status;
  }

  settledLevelValid() {
    if (this.level === null || this.gestureActive) return false;
    const s = this.camera.pixelSize(this.dpr, this.policy.dprCap);
    return chooseLevel(this.levels, s, this.level, this.policy.hysteresis) === this.level;
  }

  // ------------------------------------------------------------ box zoom, history
  async boxZoom(screenBox) {
    const { x0, y0, x1, y1 } = screenBox;
    if (Math.abs(x1 - x0) < 8 || Math.abs(y1 - y0) < 8) return;
    const [wx0, wy0] = this.camera.toWorld(Math.min(x0, x1), Math.max(y0, y1));
    const [wx1, wy1] = this.camera.toWorld(Math.max(x0, x1), Math.min(y0, y1));
    this.history.push(this.camera.state());
    const target = new Camera();
    Object.assign(target, this.camera);
    target.fit({ x0: wx0, x1: wx1, y0: wy0, y1: wy1 });
    await this.animateTo(target.state());
    this.emit();
  }

  async back() {
    const s = this.history.pop();
    if (s) await this.animateTo(s);
    this.emit();
  }

  animateTo(s, ms = 350) {
    const a = this.camera.state();
    const t0 = performance.now();
    clearTimeout(this.timer);
    this.beginGesture();                     // no debounce timer: the animation commits once, at its end
    return new Promise((resolve) => {
      const step = () => {
        const u = Math.min(1, (performance.now() - t0) / ms);
        const e = u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2;
        this.camera.set({ cx: a.cx + (s.cx - a.cx) * e, cy: a.cy + (s.cy - a.cy) * e,
                          mpp: Math.exp(Math.log(a.mpp) + (Math.log(s.mpp) - Math.log(a.mpp)) * e) });
        this.dirty = true;
        if (u < 1) requestAnimationFrame(step);
        else { this.commit(); resolve(); }
      };
      requestAnimationFrame(step);
    });
  }

  // ------------------------------------------------------------ frame loop
  frame(t) {
    const cam = this.camera;
    const dt = Math.max(1, t - this._lastT) / 1000;
    if (this._lastCam) {
      const vx = (cam.cx - this._lastCam.cx) / dt, vy = (cam.cy - this._lastCam.cy) / dt;
      this.velocity = [0.8 * this.velocity[0] + 0.2 * vx, 0.8 * this.velocity[1] + 0.2 * vy];
      const moved = cam.cx !== this._lastCam.cx || cam.cy !== this._lastCam.cy || cam.mpp !== this._lastCam.mpp;
      if (moved && !this.gestureActive && this.level !== null) {
        // panning at the settled level: request newly visible tiles at once (coalesced per frame)
        this.requestVisible(centreOut(this.levels[this.level], tilesForBBox(this.levels[this.level], cam.bbox()),
                                      cam.cx, cam.cy));
      }
    }
    this._lastCam = cam.state();
    this._lastT = t;
    this.prefetch.onFrame(cam);
    if (this.dirty && this.info) {
      this.dirty = false;
      this.frameStats = drawFrame(this.ctx, this);
      if (this.metrics.firstFrameMs === null && this.frameStats.exact > 0 && this.metrics.lastCommitAt) {
        this.metrics.firstFrameMs = performance.now() - this.metrics.lastCommitAt;
        performance.mark(`first-frame-${this.metrics.commits}`);
      }
    }
    requestAnimationFrame((tt) => this.frame(tt));
  }
}
