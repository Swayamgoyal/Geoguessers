// Unit tests for the viewer's pure logic (no browser):  cd viz/web && node --test tests/viewer.test.js
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { Camera } from "../js/camera.js";
import { centreOut, chooseLevel, tileAt, tileRect, tilesForBBox, TILE } from "../js/levels.js";
import { ringTiles } from "../js/prefetch.js";

const fixture = JSON.parse(readFileSync(new URL("./levels_fixture.json", import.meta.url)));

test("level choice matches the server on every real level and pixel size", () => {
  for (const [name, d] of Object.entries(fixture)) {
    for (const [s, prev, expected] of d.cases) {
      assert.equal(chooseLevel(d.levels, s, prev, 0.1), expected, `${name} s=${s} prev=${prev}`);
    }
  }
});

const lv = fixture.chamoli_2m.levels[2]; // 3780 x 4365 cells of 8 m

test("tile geometry: lattice covers the level, tiles are 512 cells", () => {
  const r = tileRect(lv, 0, 0);
  const [a, , c, , e, f] = lv.transform;
  assert.equal(r.x0, c);
  assert.equal(r.y1, f);
  assert.ok(Math.abs(r.x1 - r.x0 - a * TILE) < 1e-6 && Math.abs(r.y1 - r.y0 + e * TILE) < 1e-6);
  const all = tilesForBBox(lv, { x0: c, y0: f + e * lv.height, x1: c + a * lv.width, y1: f });
  assert.equal(all.length, lv.ntx * lv.nty);
  assert.deepEqual(tileAt(lv, r.x0 + 1, r.y1 - 1), [0, 0]);
  assert.equal(tileAt(lv, c - 1, f - 1), null);
  assert.deepEqual(tilesForBBox(lv, { x0: c - 1e6, y0: f + 10, x1: c - 1e5, y1: f + 1e5 }), []);
});

test("centre-out ordering puts the tile under the view centre first", () => {
  const r = tileRect(lv, 3, 4);
  const tiles = tilesForBBox(lv, { x0: r.x0 - 4000, x1: r.x1 + 4000, y0: r.y0 - 4000, y1: r.y1 + 4000 });
  assert.deepEqual(centreOut(lv, tiles, (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)[0], [3, 4]);
});

test("camera: zoom keeps the point under the cursor fixed; fit; clamp", () => {
  const cam = new Camera(1000, 2000, 2);
  cam.setSize(800, 600);
  const before = cam.toWorld(100, 50);
  cam.zoomAt(0.5, 100, 50);
  const after = cam.toWorld(100, 50);
  assert.ok(Math.abs(before[0] - after[0]) < 1e-9 && Math.abs(before[1] - after[1]) < 1e-9);
  assert.equal(cam.mpp, 1);
  cam.minMpp = 0.5;
  cam.zoomAt(0.01, 400, 300);
  assert.equal(cam.mpp, 0.5);
  cam.maxMpp = 100;
  cam.fit({ x0: 0, x1: 8000, y0: 0, y1: 3000 });
  assert.equal(cam.cx, 4000);
  assert.equal(cam.mpp, 10);
  const [sx, sy] = cam.toScreen(4000, 1500);
  assert.equal(sx, 400);
  assert.equal(sy, 300);
});

test("prefetch ring: 8 neighbours, no visible tiles, pan direction first, cardinals before corners", () => {
  const r = tileRect(lv, 3, 4);
  const view = { x0: r.x0, x1: r.x1, y0: r.y0, y1: r.y1 };   // exactly one tile visible
  const ring = ringTiles(lv, view);
  assert.equal(ring.length, 8);
  assert.ok(!ring.some(([x, y]) => x === 3 && y === 4));
  const first4 = ring.slice(0, 4).map((t) => t.join(","));
  assert.deepEqual(new Set(first4), new Set(["3,3", "3,5", "2,4", "4,4"]));     // N, S, W, E
  const east = ringTiles(lv, view, [500, 0]);
  assert.deepEqual(east[0], [4, 4]);                                             // moving east: E first
  const skip = ringTiles(lv, view, [0, 0], (tx, ty) => tx === 3 && ty === 3);
  assert.equal(skip.length, 7);
});

test("prefetch ring is clipped to the lattice and shrinks to cardinals when too large", () => {
  const r = tileRect(lv, 0, 0);
  const ring = ringTiles(lv, { x0: r.x0, x1: r.x1, y0: r.y0, y1: r.y1 });
  assert.equal(ring.length, 3);                                                 // corner tile: E, S, SE only
  const big = { x0: r.x0, x1: r.x0 + 6 * (r.x1 - r.x0), y0: r.y0 - 5 * (r.y1 - r.y0), y1: r.y1 };
  const capped = ringTiles(lv, big, [0, 0], () => false, 20);
  assert.ok(capped.length <= 20);
});
