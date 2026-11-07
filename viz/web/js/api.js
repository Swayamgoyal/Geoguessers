// Server API: tile URLs (immutable: dataset version in the URL), headers (session, generation, priority, order),
// one AbortController per request, Server-Timing parsing. Aborting a fetch closes the connection; the server sees the
// disconnect and cancels the job if no other request still needs it.

export function sessionId() {
  return Math.random().toString(36).slice(2, 10);
}

export function paramsQuery(p) {
  const q = new URLSearchParams();
  for (const k of ["op", "method", "mode", "cmap", "vmin", "vmax", "azimuth", "altitude", "zfactor"]) {
    if (p[k] !== undefined && p[k] !== null && p[k] !== "") q.set(k, p[k]);
  }
  return q.toString();
}

export function paramsKey(p) {
  return paramsQuery(p);
}

export function parseServerTiming(h) {
  const out = {};
  if (!h) return out;
  for (const part of h.split(",")) {
    const [name, ...rest] = part.trim().split(";");
    for (const r of rest) {
      const [k, v] = r.split("=");
      if (k === "dur") out[name] = parseFloat(v);
      if (k === "desc") out[name] = v.replace(/"/g, "");
    }
  }
  return out;
}

export class Api {
  constructor(base = "") {
    this.base = base;
    this.session = sessionId();
  }

  async info() {
    return (await fetch(`${this.base}/info`)).json();
  }

  async overview(dataset, params) {
    const r = await fetch(`${this.base}/overview/${dataset}.png?${paramsQuery(params)}`);
    const bounds = JSON.parse(r.headers.get("X-Bounds"));
    const bitmap = await createImageBitmap(await r.blob());
    return { bitmap, bounds: { x0: bounds[0], y0: bounds[1], x1: bounds[2], y1: bounds[3] } };
  }

  tileUrl(dataset, version, level, tx, ty, params) {
    return `${this.base}/tiles/${dataset}/${level}/${tx}/${ty}.png?${paramsQuery(params)}&v=${encodeURIComponent(version)}`;
  }

  // -> {status: "ok"|"empty"|"cancelled"|"error", bitmap?, timing, ms}
  async tile(url, { priority = "fg", gen = 0, order = 0, signal } = {}) {
    const t0 = performance.now();
    let r;
    try {
      r = await fetch(url, {
        signal,
        priority: priority === "fg" ? "high" : "low",
        headers: { "X-Session": this.session, "X-Gen": String(gen), "X-Priority": priority, "X-Order": String(order) },
      });
    } catch (e) {
      return { status: e.name === "AbortError" ? "cancelled" : "error", ms: performance.now() - t0 };
    }
    const timing = parseServerTiming(r.headers.get("Server-Timing"));
    timing.expectedError = r.headers.get("X-Expected-Error");
    if (r.status === 204) return { status: "empty", timing, ms: performance.now() - t0 };
    if (r.status === 409 || r.status === 499) return { status: "cancelled", ms: performance.now() - t0 };
    if (r.status === 503) return { status: "busy", ms: performance.now() - t0 };   // server paused prefetch
    if (!r.ok) return { status: "error", ms: performance.now() - t0 };
    try {
      const bitmap = await createImageBitmap(await r.blob());   // decoded off the main thread
      return { status: "ok", bitmap, timing, ms: performance.now() - t0 };
    } catch (e) {
      return { status: e.name === "AbortError" ? "cancelled" : "error", ms: performance.now() - t0 };
    }
  }

  // supersede this session's older work on the server; cancelBg also drops its queued prefetch
  postGen(gen, cancelBg = false) {
    return fetch(`${this.base}/session/${this.session}/gen`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ gen, cancel_bg: cancelBg }), keepalive: true,
    }).catch(() => {});
  }

  async view(body) {
    return fetch(`${this.base}/view`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
  }

  async stats() {
    return (await fetch(`${this.base}/stats`)).json();
  }
}
