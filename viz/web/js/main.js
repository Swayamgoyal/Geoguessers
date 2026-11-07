// Page wiring: load policy and server info, build the controls, start the viewer, keep the status panel current.

import { Api } from "./api.js";
import { attachGestures } from "./gestures.js";
import { Viewer } from "./viewer.js";

const $ = (id) => document.getElementById(id);
const METHODS = {
  slope: ["Horn", "ZevenbergenThorne"], aspect: ["Horn", "ZevenbergenThorne"], hillshade: ["Horn", "ZevenbergenThorne"],
  TRI: ["Riley", "Wilson"], TPI: [], roughness: [],
};
const OP_LABEL = { slope: "Slope", aspect: "Aspect", hillshade: "Hillshade", TRI: "Ruggedness (TRI)",
                   TPI: "Topographic position (TPI)", roughness: "Roughness" };
const UNIT = { slope: "°", aspect: "°", hillshade: "", TRI: " m", TPI: " m", roughness: " m" };

const params = new URLSearchParams(location.search);

async function main() {
  const policy = await (await fetch("policy.json")).json();
  if (params.has("debounce")) policy.debounceMs = Number(params.get("debounce"));
  const api = new Api("");
  const info = await api.info();
  const v = new Viewer($("map"), policy, api);
  v.bgColour = getComputedStyle(document.documentElement).getPropertyValue("--map-bg").trim();
  window.viewer = v;   // for the E6 browser check and debugging
  attachGestures($("map"), v, policy);

  // controls
  const names = Object.keys(info.datasets);
  $("dataset").innerHTML = names.map((n) => `<option value="${n}">${n.replace("_", " ")}</option>`).join("");
  $("op").innerHTML = info.ops.map((o) => `<option value="${o}">${OP_LABEL[o] || o}</option>`).join("");
  $("op").value = "hillshade";

  const syncControls = () => {
    const op = $("op").value;
    const ms = METHODS[op] || [];
    $("method-row").hidden = ms.length === 0;
    if (ms.length && !ms.includes($("method").value)) {
      $("method").innerHTML = ms.map((m) => `<option value="${m}">${m === "ZevenbergenThorne" ? "Zevenbergen–Thorne" : m}</option>`).join("");
    }
    $("sun-row").hidden = op !== "hillshade";
    const preOk = info.datasets[$("dataset").value].precomputed && op === "slope" && $("method").value === "Horn";
    $("mode").querySelector('option[value="precomputed"]').disabled = !preOk;
    if (!preOk && $("mode").value === "precomputed") $("mode").value = "auto";
  };
  const currentParams = () => {
    const op = $("op").value;
    const p = { op, mode: $("mode").value, method: (METHODS[op] || []).length ? $("method").value : "" };
    if (op === "hillshade") p.azimuth = Number($("azimuth").value);
    return p;
  };
  const apply = async () => {
    syncControls();
    renderLegend(info, $("op").value);
    await v.setParams(currentParams());
  };
  syncControls();
  renderLegend(info, $("op").value);
  v.params = currentParams();
  await v.load(info, names[0]);

  $("dataset").addEventListener("change", async () => { syncControls(); await v.setDataset($("dataset").value); });
  for (const id of ["op", "method", "mode"]) $(id).addEventListener("change", apply);
  let sunTimer = null;
  $("azimuth").addEventListener("input", () => {
    $("sun-val").textContent = `${$("azimuth").value}°`;
    clearTimeout(sunTimer);
    sunTimer = setTimeout(apply, 150);
  });
  $("prefetch").addEventListener("change", () => {
    v.prefetch.enabled = $("prefetch").checked;
    if (!v.prefetch.enabled) v.prefetch.abortAll();
    else v.prefetch.rebuild();
  });
  $("back").addEventListener("click", () => v.back());
  $("home").addEventListener("click", () => {
    const [l, b, r, t] = v.pyr.bounds;
    v.history.push(v.camera.state());
    const target = { cx: (l + r) / 2, cy: (b + t) / 2,
                     mpp: 1.05 * Math.max((r - l) / v.camera.width, (t - b) / v.camera.height) };
    v.animateTo(target);
  });

  // status
  const fmt = (x, d = 1) => (x === null || x === undefined || Number.isNaN(x) ? "–" : Number(x).toFixed(d));
  const update = () => {
    $("back").disabled = v.history.length === 0;
    if (v.level === null) return;
    const lv = v.levels[v.level];
    $("s-level").textContent = `${v.level} of ${v.levels.length - 1}`;
    $("s-cell").textContent = `${fmt(lv.res, lv.res < 10 ? 1 : 0)} m (screen ${fmt(v.camera.mpp, 2)} m/px)`;
    const mode = v.params.mode;
    $("s-error").textContent = mode !== "auto" || v.level === 0 ? "0° (full resolution)"
      : lv.expected_rmse ? `≈ ${fmt(lv.expected_rmse)}° RMSE, ${fmt(lv.expected_bias)}° bias` : "not measured";
    const fs = v.frameStats;
    $("s-tiles").textContent = `${fs.exact} / ${fs.visible}${fs.fallback ? ` (+${fs.fallback} preview)` : ""}`;
    const lt = v.metrics.lastTile;
    $("s-last").textContent = lt ? `${fmt(lt.ms, 0)} ms (${lt.tier || "–"}, ${lt.priority})` : "–";
    $("s-complete").textContent = v.metrics.completeMs !== null ? `${fmt(v.metrics.completeMs, 0)} ms` : "loading…";
    $("s-client").textContent = `${v.cache.map.size} tiles, ${fmt(v.cache.bytes / 2 ** 20, 0)} MiB`;
    const st = v.cache.stats;
    $("s-prefetch").textContent = st.prefetched ? `${st.prefetchedDrawn} / ${st.prefetched}` : "–";
  };
  v.onChange(update);
  setInterval(update, 300);
  const cursor = () => {
    if (!v.cursor) return;
    const [x, y] = v.camera.toWorld(v.cursor[0], v.cursor[1]);
    $("cursor").textContent = `E ${x.toFixed(0)}  N ${y.toFixed(0)}  (UTM 44N)`;
  };
  v.emitCursor = cursor;
  if (params.get("selftest")) {
    const { runSelfTest } = await import("./selftest.js");
    runSelfTest(v);
  }
  if (params.get("trace")) {                  // E6 browser check: replay a bench trace (bench/e6_browser.py)
    const { runTrace } = await import("./tracerun.js");
    runTrace(v, params.get("trace"));
  }
  setInterval(async () => {
    try {
      const s = await api.stats();
      const b = s.blocks, r = s.results, q = s.scheduler;
      $("s-blocks").textContent = `${b.entries} · ${fmt(100 * b.hit_rate, 0)}% hits · ${b.decoded} decoded`;
      $("s-results").textContent = `${r.entries} · ${fmt(100 * r.hit_rate, 0)}% hits`;
      $("s-queues").textContent = `fg ${q.queued.fg}+${q.running.fg} · bg ${q.queued.bg}+${q.running.bg}`;
    } catch (e) { /* server busy or gone */ }
    cursor();
  }, 2000);
}

function renderLegend(info, op) {
  const stops = info.legends[op];
  const cm = info.colormaps[op];
  const grad = stops.map(([, c], i) => `${c} ${(100 * i) / (stops.length - 1)}%`).join(", ");
  const unit = UNIT[op] || "";
  const ticks = op === "aspect" ? ["N", "E", "S", "W", "N"]
    : [cm.vmin, (cm.vmin + cm.vmax) / 2, cm.vmax].map((x) => `${Math.round(x)}${unit}`);
  $("legend").innerHTML = `<div class="title">${OP_LABEL[op]}</div><div class="bar" style="background:linear-gradient(to right, ${grad})"></div>` +
    `<div class="ticks">${ticks.map((t) => `<span>${t}</span>`).join("")}</div>`;
}

main().catch((e) => {
  document.body.insertAdjacentHTML("beforeend", `<p style="position:fixed;top:8px;left:8px;background:#b2182b;color:#fff;padding:8px">Viewer failed to start: ${e}</p>`);
  console.error(e);
});
