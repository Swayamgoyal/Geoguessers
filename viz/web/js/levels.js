// Pyramid levels and the 512² tile lattice, mirrored from the server (demlab/view.py). Pure functions, no DOM.
//
// A level from GET /info: {k, width, height, transform: [a, b, c, d, e, f], res, ntx, nty}; world (UTM) coordinates
// x = c + a·col, y = f + e·row (e < 0). Tile (tx, ty) covers level cells [512·tx, +512) × [512·ty, +512).

export const TILE = 512;

// Level for a screen pixel of `s` metres: the coarsest level whose cell is no larger than a pixel,
// k = max{j : res_j <= s} (0 when s < res_0). With `prev`, keep it while it stays valid within ±hysteresis.
export function chooseLevel(levels, s, prev = null, hysteresis = 0.1) {
  const pick = (v) => {
    let k = 0;
    for (const lv of levels) if (lv.res <= v) k = lv.k;
    return k;
  };
  if (prev !== null && pick(s / (1 + hysteresis)) <= prev && prev <= pick(s * (1 + hysteresis))) return prev;
  return pick(s);
}

// World rectangle {x0, y0, x1, y1} (y0 < y1) of the full 512² tile, padding included.
export function tileRect(level, tx, ty) {
  const [a, , c, , e, f] = level.transform;
  const x0 = c + a * TILE * tx;
  const yTop = f + e * TILE * ty;
  return { x0, x1: x0 + a * TILE, y1: yTop, y0: yTop + e * TILE };
}

// Tiles (inside the lattice) intersecting a world bbox {x0, y0, x1, y1}.
export function tilesForBBox(level, bbox) {
  const [a, , c, , e, f] = level.transform;
  const tw = a * TILE, th = -e * TILE;
  const tx0 = Math.max(0, Math.floor((bbox.x0 - c) / tw));
  const tx1 = Math.min(level.ntx - 1, Math.floor((bbox.x1 - c) / tw - 1e-9));
  const ty0 = Math.max(0, Math.floor((f - bbox.y1) / th));
  const ty1 = Math.min(level.nty - 1, Math.floor((f - bbox.y0) / th - 1e-9));
  const out = [];
  for (let ty = ty0; ty <= ty1; ty++) for (let tx = tx0; tx <= tx1; tx++) out.push([tx, ty]);
  return out;
}

// Tile of `level` containing world point (x, y), or null outside the lattice.
export function tileAt(level, x, y) {
  const [a, , c, , e, f] = level.transform;
  const tx = Math.floor((x - c) / (a * TILE));
  const ty = Math.floor((f - y) / (-e * TILE));
  if (tx < 0 || ty < 0 || tx >= level.ntx || ty >= level.nty) return null;
  return [tx, ty];
}

// Sort tiles centre-out (distance of the tile centre from world point cx, cy).
export function centreOut(level, tiles, cx, cy) {
  return tiles
    .map((t) => {
      const r = tileRect(level, t[0], t[1]);
      const dx = (r.x0 + r.x1) / 2 - cx, dy = (r.y0 + r.y1) / 2 - cy;
      return { t, d: dx * dx + dy * dy };
    })
    .sort((p, q) => p.d - q.d)
    .map((p) => p.t);
}
