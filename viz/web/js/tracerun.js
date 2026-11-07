// Replays an E6 trace (bench/traces/<name>.json, served at /traces/) in the real viewer, exactly as the virtual
// client (bench/vclient.py) does, and writes what happened as JSON into <pre id="tracerun">. Open
// /viewer/?trace=<name>; bench/e6_browser.py drives this in headless Chrome over the DevTools protocol (real time,
// no virtual clock) to check the virtual client's numbers against a real browser.

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function prefetchIdle(v) {
  return v.prefetch.inflight.size === 0 && v.prefetch.queue.length === 0;
}

async function settle(v, timeout) {
  const t0 = performance.now();
  while (performance.now() - t0 < timeout) {
    if (v.metrics.completeMs !== null && !v.gestureActive && prefetchIdle(v)) return true;
    await sleep(20);
  }
  return false;
}

export async function runTrace(v, name) {
  const trace = await (await fetch(`/traces/${name}.json`)).json();
  const cam = v.camera;
  const [W, H] = trace.view;
  cam.setSize(W, H);                         // same view as the virtual client, whatever the window size
  const ds = v.pyr;
  const [l, b, r, t] = ds.bounds;
  cam.maxMpp = 4 * Math.max((r - l) / W, (t - b) / H);
  const st = trace.start;
  if (st.fit) {
    cam.fit({ x0: l, x1: r, y0: b, y1: t }, 1.05);
  } else {
    const lv = ds.levels[Math.min(st.level, ds.levels.length - 1)];
    cam.mpp = cam.clampMpp(lv.res * Math.SQRT2);
    const w = W * cam.mpp;
    cam.cx = (l + r) / 2 + (st.u || 0) * w;
    cam.cy = (b + t) / 2 + (st.v || 0) * w;
  }
  v.dirty = true;
  v.commit();
  const ready = await settle(v, 8000);

  // per commit: time, and the first-frame / complete times the viewer reports for it
  const t0 = performance.now();
  const commits = [];
  const orig = v.commit.bind(v);
  v.commit = () => { orig(); commits.push({ t: performance.now() - t0, n: v.metrics.commits, first: null, complete: null }); };
  let sampling = true;
  const sample = () => {
    const c = commits.find((x) => x.n === v.metrics.commits);
    if (c) {
      if (c.first === null && v.metrics.firstFrameMs !== null) c.first = v.metrics.firstFrameMs;
      if (c.complete === null && v.metrics.completeMs !== null) c.complete = v.metrics.completeMs;
    }
    if (sampling) requestAnimationFrame(sample);
  };
  requestAnimationFrame(sample);
  const m0 = { ...v.metrics }, pf0 = { ...v.cache.stats };
  const gestures = {};
  for (const ev of trace.events) {
    const target = t0 + ev[0] * 1000;
    while (performance.now() < target) await sleep(Math.max(0, Math.min(target - performance.now(), 16)));
    const now = performance.now() - t0;
    if (ev[1] === "pan") {
      v.panBy(ev[2], ev[3]);
    } else if (ev[1] === "wheel") {
      const g = ev[5];
      gestures[g] = gestures[g] || { gesture: g, kind: "wheel", t_first: now, ticks: 0 };
      gestures[g].ticks++;
      gestures[g].t_last = now;
      v.zoomAt(ev[2], ev[3], ev[4]);
    } else if (ev[1] === "box") {
      const g = ev[6];
      gestures[g] = { gesture: g, kind: "box", t_first: now, ticks: 1 };
      await v.boxZoom({ x0: ev[2], y0: ev[3], x1: ev[4], y1: ev[5] });
      gestures[g].t_last = performance.now() - t0;
    }
  }
  const tEnd = performance.now();
  while (performance.now() - tEnd < 4000) {
    if (performance.now() - tEnd > 300 && v.metrics.completeMs !== null && !v.gestureActive && prefetchIdle(v)) break;
    await sleep(50);
  }
  await sleep(100);
  sampling = false;
  const gs = Object.values(gestures).sort((a, b) => a.t_first - b.t_first).map((g, i, arr) => {
    const next = i + 1 < arr.length ? arr[i + 1].t_first : Infinity;
    const c = commits.find((x) => x.t >= g.t_last - 1 && x.t < next);
    return { ...g, ttff_ms: c && c.first !== null ? c.t + c.first - g.t_last : null,
             complete_ms: c && c.complete !== null ? c.t + c.complete - g.t_last : null };
  });
  const out = {
    trace: name, ready, duration_s: (performance.now() - t0) / 1000, commits: v.metrics.commits - m0.commits,
    fg_requests: v.metrics.requestedFg - m0.requestedFg, fg_tiles: v.metrics.tilesFg - m0.tilesFg,
    bg_tiles: v.metrics.tilesBg - m0.tilesBg, cancelled: v.metrics.cancelled - m0.cancelled,
    prefetched: v.cache.stats.prefetched, prefetched_drawn: v.cache.stats.prefetchedDrawn,
    prefetched_during_trace: v.cache.stats.prefetched - pf0.prefetched, gestures: gs,
  };
  const pre = document.createElement("pre");
  pre.id = "tracerun";
  pre.textContent = JSON.stringify(out);
  pre.style.display = "none";
  document.body.appendChild(pre);
  document.title = `TRACE DONE ${name}`;
  return out;
}
