// Frame drawing: the overview base layer, then for every visible lattice cell its best available bitmap:
//   1. the level-k tile; 2. the nearest coarser cached level, cropped and upscaled; 3. finer cached tiles,
//   downscaled; 4. the overview (always loaded), so no cell is ever blank.
// During a zoom gesture the camera scale changes but the settled level does not: existing bitmaps are simply drawn at
// the new scale (bilinear preview). Everything is drawn in device pixels with rounded edges (no seams).

import { EMPTY } from "./tileCache.js";
import { tileAt, tileRect, tilesForBBox } from "./levels.js";

export function drawFrame(ctx, v) {
  const cam = v.camera, dpr = v.dpr;
  const W = ctx.canvas.width, H = ctx.canvas.height;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = v.bgColour || "#16181d";
  ctx.fillRect(0, 0, W, H);
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "low";

  const toDev = (x, y) => {
    const [sx, sy] = cam.toScreen(x, y);
    return [sx * dpr, sy * dpr];
  };
  const drawRect = (bitmap, rect, src = null) => {
    const [x0, y0] = toDev(rect.x0, rect.y1);
    const [x1, y1] = toDev(rect.x1, rect.y0);
    const dx = Math.floor(x0), dy = Math.floor(y0);
    const dw = Math.ceil(x1) - dx, dh = Math.ceil(y1) - dy;
    if (dx > W || dy > H || dx + dw < 0 || dy + dh < 0) return;
    if (src) ctx.drawImage(bitmap, src[0], src[1], src[2], src[3], dx, dy, dw, dh);
    else ctx.drawImage(bitmap, dx, dy, dw, dh);
  };

  if (v.overview) drawRect(v.overview.bitmap, v.overview.bounds);
  if (v.level === null) return { visible: 0, exact: 0, fallback: 0 };

  const levels = v.levels;
  const k = v.level;
  const lv = levels[k];
  const bbox = cam.bbox();
  const visible = tilesForBBox(lv, bbox);
  const top = [];
  let exact = 0, fallback = 0;
  for (const [tx, ty] of visible) {
    const e = v.cache.get(v.key(k, tx, ty));
    if (e) {
      exact++;
      if (e.bitmap !== EMPTY) top.push([e, tileRect(lv, tx, ty)]);
      v.cache.markDrawn(e);
      continue;
    }
    const cell = tileRect(lv, tx, ty);
    let filled = false;
    // 2. nearest coarser cached level: crop the part of its tile that covers this cell
    for (let j = k + 1; j < levels.length && !filled; j++) {
      const lj = levels[j];
      const t = tileAt(lj, (cell.x0 + cell.x1) / 2, (cell.y0 + cell.y1) / 2);
      if (!t) break;
      const ce = v.cache.get(v.key(j, t[0], t[1]));
      if (!ce) continue;
      filled = true;
      if (ce.bitmap === EMPTY) break;
      const r = tileRect(lj, t[0], t[1]);
      const sx = ((cell.x0 - r.x0) / (r.x1 - r.x0)) * 512, sw = ((cell.x1 - cell.x0) / (r.x1 - r.x0)) * 512;
      const sy = ((r.y1 - cell.y1) / (r.y1 - r.y0)) * 512, sh = ((cell.y1 - cell.y0) / (r.y1 - r.y0)) * 512;
      drawRect(ce.bitmap, cell, [sx, sy, sw, sh]);
    }
    // 3. finer cached tiles (one level down), downscaled
    if (!filled && k > 0) {
      for (const [fx, fy] of tilesForBBox(levels[k - 1], cell)) {
        const fe = v.cache.get(v.key(k - 1, fx, fy));
        if (fe && fe.bitmap !== EMPTY) {
          drawRect(fe.bitmap, tileRect(levels[k - 1], fx, fy));
          filled = true;
        }
      }
    }
    if (filled) fallback++;
  }
  for (const [e, rect] of top) drawRect(e.bitmap, rect);

  // box-zoom rubber band
  if (v.box) {
    const { x0, y0, x1, y1 } = v.box;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.strokeStyle = "#ffd166";
    ctx.lineWidth = 1.5;
    ctx.setLineDash([6, 4]);
    ctx.strokeRect(Math.min(x0, x1), Math.min(y0, y1), Math.abs(x1 - x0), Math.abs(y1 - y0));
    ctx.setLineDash([]);
    ctx.fillStyle = "rgba(255, 209, 102, 0.12)";
    ctx.fillRect(Math.min(x0, x1), Math.min(y0, y1), Math.abs(x1 - x0), Math.abs(y1 - y0));
  }
  return { visible: visible.length, exact, fallback };
}
