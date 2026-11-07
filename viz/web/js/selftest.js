// In-browser self-test (open /viewer/?selftest=1): scripted gestures that check the Phase 3 behaviour in a real
// browser and write the results as JSON into <pre id="selftest"> (read by headless Chrome --dump-dom).
//   1. a 2 s wheel burst (60 Hz ticks) -> exactly one commit after the debounce
//   2. a pan at the settled level -> new tiles requested, no commit
//   3. after a commit, the prefetch ring loads at low priority
//   4. Shift + drag box zoom -> camera animates to the box, one commit

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitComplete(v, timeout = 8000) {
  const t0 = performance.now();
  while (performance.now() - t0 < timeout) {
    if (v.metrics.completeMs !== null && !v.gestureActive) return true;
    await sleep(50);
  }
  return false;
}

export async function runSelfTest(v) {
  const out = { ok: true, checks: {} };
  const check = (name, pass, detail) => {
    out.checks[name] = { pass, ...detail };
    if (!pass) out.ok = false;
  };
  // headless Chrome runs on virtual time, which inflates measured latencies: no latency back-off here
  v.policy.prefetch.backoffP95Ms = 1e9;
  await waitComplete(v);
  const cam = v.camera;

  // 1. wheel burst: 120 ticks over 2 s, zooming in about the centre
  let c0 = v.metrics.commits;
  const l0 = v.level;
  for (let i = 0; i < 120; i++) {
    v.zoomAt(Math.exp(-6 * 0.0015), cam.width / 2, cam.height / 2);
    await sleep(1000 / 60);
  }
  const duringBurst = v.metrics.commits - c0;
  await sleep(v.policy.debounceMs + 50);
  await waitComplete(v);
  check("wheel_burst_one_commit", duringBurst === 0 && v.metrics.commits - c0 === 1,
        { commits_during_burst: duringBurst, commits_after: v.metrics.commits - c0, level_before: l0,
          level_after: v.level, complete_ms: v.metrics.completeMs, first_frame_ms: v.metrics.firstFrameMs });

  // 3. prefetch ring after the commit
  await sleep(1500);
  const st = v.cache.stats;
  check("prefetch_ring_loaded", st.prefetched > 0, { prefetched: st.prefetched, bg_tiles: v.metrics.tilesBg });

  // 2. pan by half a view in small steps at the settled level
  c0 = v.metrics.commits;
  const fg0 = v.metrics.requestedFg, drawn0 = st.prefetchedDrawn;
  for (let i = 0; i < 30; i++) {
    v.panBy(-cam.width / 60, 0);
    await sleep(1000 / 60);
  }
  await sleep(800);
  const panServed = (v.metrics.requestedFg - fg0) + (v.cache.stats.prefetchedDrawn - drawn0);
  check("pan_no_commit_tiles_arrive", v.metrics.commits === c0 && panServed > 0,
        { commits: v.metrics.commits - c0, new_fg_requests: v.metrics.requestedFg - fg0,
          prefetched_tiles_used_by_pan: v.cache.stats.prefetchedDrawn - drawn0 });

  // 4. box zoom on the central quarter
  c0 = v.metrics.commits;
  const before = cam.mpp;
  await v.boxZoom({ x0: cam.width * 0.375, y0: cam.height * 0.375, x1: cam.width * 0.625, y1: cam.height * 0.625 });
  await waitComplete(v);
  check("box_zoom_one_commit", v.metrics.commits - c0 === 1 && cam.mpp < before * 0.5,
        { commits: v.metrics.commits - c0, zoom_factor: before / cam.mpp, level: v.level });

  out.metrics = { ...v.metrics, cache_tiles: v.cache.map.size, cache_mib: v.cache.bytes / 2 ** 20,
                  frame: v.frameStats };
  const pre = document.createElement("pre");
  pre.id = "selftest";
  pre.textContent = JSON.stringify(out);
  pre.style.display = "none";
  document.body.appendChild(pre);
  document.title = out.ok ? "SELFTEST PASS" : "SELFTEST FAIL";
  return out;
}
