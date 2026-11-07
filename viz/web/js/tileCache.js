// Client tile cache: decoded ImageBitmaps (GPU-backed) per tile key, byte-accounted LRU. Bitmaps hold GPU memory
// until close(), so every eviction closes the bitmap. Empty tiles (outside the DEM / all nodata) are cached as EMPTY
// so they are never requested again. Tiles of levels other than the current one are evicted first.

export const EMPTY = "empty";

export class TileCache {
  constructor(budgetMiB = 256) {
    this.budget = budgetMiB * 1024 * 1024;
    this.map = new Map();   // key -> {bitmap, bytes, level, lastUsed, origin, firstDrawnAt, fetchedAt}
    this.bytes = 0;
    this.currentLevel = 0;
    this.stats = { hits: 0, misses: 0, evictions: 0, prefetchedDrawn: 0, prefetched: 0 };
  }

  get(key) {
    const e = this.map.get(key);
    if (!e) return null;
    e.lastUsed = performance.now();
    return e;
  }

  has(key) {
    return this.map.has(key);
  }

  put(key, bitmap, level, origin) {
    if (this.map.has(key)) return;
    const bytes = bitmap === EMPTY ? 0 : bitmap.width * bitmap.height * 4;
    this.map.set(key, { bitmap, bytes, level, origin, lastUsed: performance.now(), fetchedAt: performance.now(),
                        firstDrawnAt: null });
    this.bytes += bytes;
    if (origin === "bg") this.stats.prefetched++;
    this.evict();
  }

  markDrawn(e) {
    if (e.firstDrawnAt === null) {
      e.firstDrawnAt = performance.now();
      if (e.origin === "bg") this.stats.prefetchedDrawn++;
    }
  }

  evict() {
    if (this.bytes <= this.budget) return;
    const entries = [...this.map.entries()].sort((p, q) => {
      const po = p[1].level === this.currentLevel ? 1 : 0, qo = q[1].level === this.currentLevel ? 1 : 0;
      return po - qo || p[1].lastUsed - q[1].lastUsed;     // other levels first, then least recently used
    });
    for (const [key, e] of entries) {
      if (this.bytes <= this.budget * 0.9) break;
      this.remove(key, e);
    }
  }

  remove(key, e = this.map.get(key)) {
    if (!e) return;
    if (e.bitmap !== EMPTY && e.bitmap.close) e.bitmap.close();
    this.bytes -= e.bytes;
    this.map.delete(key);
    this.stats.evictions++;
  }

  clear() {
    for (const [key, e] of [...this.map.entries()]) this.remove(key, e);
  }
}
