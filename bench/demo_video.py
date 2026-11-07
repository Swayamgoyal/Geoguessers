"""Record the demo video (fallback for the live demo): report/demo/geoguessers_demo.mp4.

1. A fresh tile server; the web viewer in real headless Chrome (1600 x 900, dark theme), driven by a scripted
   sequence of real viewer actions (wheel zoom, pan, product switch, sun direction, Shift + drag box zoom, whole map)
   with captions overlaid in the page. Frames come from the Chrome DevTools screencast (only changed frames, each
   with its timestamp) and are re-timed to a constant 30 fps.
2. QGIS plugin footage rendered by bench/demo_qgis.py with QGIS's own Python (stills, 4.5 s each).
3. ffmpeg joins both parts (H.264, silent).

    python -m bench.demo_video [--keep-frames]
"""
import argparse
import asyncio
import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
import websockets

from bench.e6_browser import CDP_PORT, CHROME
from bench.experiments.e6_view import BASE, start_server, stop_server

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "report" / "demo"
QGIS_PY = r"C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
W, H = 1600, 900

OVERLAY = r"""
(() => {
  const el = document.createElement('div');
  el.id = 'demo-caption';
  el.style.cssText = 'position:fixed;left:24px;bottom:24px;width:1228px;box-sizing:border-box;padding:14px 20px;' +
    'background:rgba(15,17,21,0.84);color:#fff;border-radius:10px;font:600 22px "Segoe UI",sans-serif;' +
    'z-index:10;transition:opacity .25s;opacity:0';
  document.body.appendChild(el);
  window.demoCaption = (title, sub) => {
    el.innerHTML = title + (sub ? '<div style="font-weight:400;font-size:17px;color:#d0d4da;margin-top:4px">' +
      sub + '</div>' : '');
    el.style.opacity = 1;
  };
  return true;
})()
"""

SCRIPT = r"""
(async () => {
  const v = window.viewer, $ = (id) => document.getElementById(id);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const cap = window.demoCaption;
  const settle = async (max = 8000) => {
    const t0 = performance.now();
    while (performance.now() - t0 < max) {
      if (v.metrics.completeMs !== null && !v.gestureActive) return;
      await sleep(50);
    }
  };
  const set = async (id, value, ev = 'change') => { $(id).value = value; $(id).dispatchEvent(new Event(ev)); };
  const W = v.camera.width, H = v.camera.height;

  cap('GeoGuessers: terrain computed on demand, only for what is in view',
      'Chamoli 2 m DEM (264 million cells) on one laptop &middot; hillshade &middot; the whole map comes from a coarse pyramid level');
  await settle(); await sleep(4000);

  cap('Zoom with the mouse wheel',
      'Cached coarser tiles stand in while you scroll; the viewer commits once, 150 ms after the last tick');
  for (let i = 0; i < 90; i++) { v.zoomAt(Math.pow(2, -3 / 90), W * 0.52, H * 0.48); await sleep(1000 / 60); }
  await settle(); await sleep(2200);

  cap('Pan',
      'The 8 neighbouring views were prefetched on the efficiency cores, so the new tiles are already there');
  for (let i = 0; i < 240; i++) { v.panBy(-W / 60 * 0.35, -H / 60 * 0.15); await sleep(1000 / 60); }
  await sleep(1500);

  cap('Switch the product: slope', 'Computed on demand from the same pyramid level; nothing was precomputed');
  await set('op', 'slope'); await settle(); await sleep(3200);
  cap('Aspect', 'Any derivative, any parameter: each is just another on-demand tile');
  await set('op', 'aspect'); await settle(); await sleep(3000);

  cap('Hillshade with any sun direction', 'Moving the sun re-computes the visible tiles in a fraction of a second');
  await set('op', 'hillshade'); await settle(); await sleep(800);
  for (let a = 315; a >= 135; a -= 6) { $('azimuth').value = a; $('azimuth').dispatchEvent(new Event('input')); await sleep(60); }
  await sleep(400); await settle(); await sleep(2200);

  cap('Shift + drag: zoom to a box', 'The camera flies to the box and commits once');
  const b0 = { x0: W * 0.40, y0: H * 0.38 };
  for (let i = 1; i <= 30; i++) {
    v.box = { x0: b0.x0, y0: b0.y0, x1: b0.x0 + W * 0.22 * i / 30, y1: b0.y0 + H * 0.22 * i / 30 }; v.dirty = true;
    await sleep(1000 / 60);
  }
  await sleep(400);
  const box = v.box; v.box = null; v.dirty = true;
  await v.boxZoom(box); await settle(); await sleep(1500);
  cap('Full resolution: 2 m cells',
      'The panel shows the pyramid level, the cell size and the expected slope error of the level (measured in E5)');
  await sleep(3800);

  cap('Back to the whole map', '');
  $('home').click(); await sleep(500); await settle(); await sleep(2200);

  cap('Measured with 1,068 scripted runs (E6)',
      'Pans: 98&ndash;100% of tiles already cached &middot; zoom: 3.3&times; fewer server tiles with the debounce &middot; prefetch never slows the visible tiles');
  await sleep(5000);
  return 'done';
})()
"""


async def cdp(ws, method, params=None, _id=[0]):
    _id[0] += 1
    await ws.send(json.dumps({"id": _id[0], "method": method, "params": params or {}}))
    return _id[0]


async def record(url, frames_dir):
    for _ in range(100):
        try:
            pages = httpx.get(f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=1, trust_env=False).json()
            page = next(p for p in pages if p.get("type") == "page")
            break
        except (httpx.HTTPError, StopIteration, ValueError):
            await asyncio.sleep(0.2)
    frames = []
    results = {}
    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
        async def reader():
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("method") == "Page.screencastFrame":
                    p = msg["params"]
                    f = frames_dir / f"f{len(frames):05d}.jpg"
                    f.write_bytes(base64.b64decode(p["data"]))
                    frames.append((p["metadata"]["timestamp"], f))
                    await cdp(ws, "Page.screencastFrameAck", {"sessionId": p["sessionId"]})
                elif "id" in msg:
                    results[msg["id"]] = msg

        task = asyncio.ensure_future(reader())

        async def call(method, params=None, timeout=300):
            i = await cdp(ws, method, params)
            t0 = time.time()
            while i not in results:
                if time.time() - t0 > timeout:
                    raise TimeoutError(method)
                await asyncio.sleep(0.02)
            return results.pop(i)

        await call("Emulation.setDeviceMetricsOverride", {"width": W, "height": H, "deviceScaleFactor": 1,
                                                          "mobile": False})
        await call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": "dark"}]})
        await call("Page.enable")
        await call("Page.navigate", {"url": url})
        for _ in range(300):
            r = await call("Runtime.evaluate", {"expression": "!!(window.viewer && window.viewer.metrics."
                                                              "completeMs !== null)", "returnByValue": True})
            if r.get("result", {}).get("result", {}).get("value"):
                break
            await asyncio.sleep(0.1)
        await asyncio.sleep(1.5)
        await call("Runtime.evaluate", {"expression": OVERLAY, "returnByValue": True})
        await call("Page.startScreencast", {"format": "jpeg", "quality": 88, "maxWidth": W, "maxHeight": H,
                                            "everyNthFrame": 1})
        r = await call("Runtime.evaluate", {"expression": SCRIPT, "awaitPromise": True, "returnByValue": True},
                       timeout=600)
        await call("Page.stopScreencast")
        t_end = time.time()
        task.cancel()
    print("script:", r.get("result", {}).get("result", {}).get("value"), "frames:", len(frames))
    return frames, t_end


def encode_browser(frames, t_end, work):
    lines = []
    for i, (ts, f) in enumerate(frames):
        nxt = frames[i + 1][0] if i + 1 < len(frames) else min(ts + 1.0, t_end)
        lines.append(f"file '{f.as_posix()}'\nduration {max(nxt - ts, 1 / 120):.4f}")
    lines.append(f"file '{frames[-1][1].as_posix()}'")
    lst = work / "browser.txt"
    lst.write_text("\n".join(lines))
    out = work / "browser.mp4"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-vf", f"fps=30,scale={W}:{H},format=yuv420p", "-c:v", "libx264", "-preset", "medium",
                    "-crf", "23", str(out)], check=True)
    return out


def caption_qgis(qdir):
    """Draw the captions (qdir/captions.json) on the QGIS frames with Pillow: Qt's offscreen platform has no fonts."""
    from PIL import Image, ImageDraw, ImageFont
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    bold, reg = ImageFont.truetype(str(fonts / "segoeuib.ttf"), 26), ImageFont.truetype(str(fonts / "segoeui.ttf"), 20)
    tagf = ImageFont.truetype(str(fonts / "segoeuib.ttf"), 17)
    caps = json.loads((qdir / "captions.json").read_text(encoding="utf-8"))
    for name, (title, sub) in caps.items():
        im = Image.open(qdir / name).convert("RGBA")
        ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        d.rounded_rectangle([24, H - 120, W - 24, H - 24], 10, fill=(15, 17, 21, 215))
        d.rounded_rectangle([24, 24, 174, 58], 6, fill=(42, 120, 214, 255))
        im = Image.alpha_composite(im, ov)
        d = ImageDraw.Draw(im)
        d.text((44, H - 112), title, font=bold, fill="#ffffff")
        d.text((44, H - 70), sub, font=reg, fill="#d0d4da")
        d.text((99, 41), "QGIS plugin", font=tagf, fill="#ffffff", anchor="mm")
        im.convert("RGB").save(qdir / name)


def encode_qgis(qdir, work, seconds=4.5):
    caption_qgis(qdir)
    parts = []
    for i, png in enumerate(sorted(qdir.glob("q*.png"))):
        out = work / f"qgis{i}.mp4"
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-loop", "1", "-t", str(seconds), "-i", str(png),
                        "-vf", f"fps=30,scale={W}:{H},format=yuv420p", "-c:v", "libx264", "-preset", "medium",
                        "-crf", "23", str(out)], check=True)
        parts.append(out)
    return parts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-frames", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="gg_demo_"))
    frames_dir = work / "frames"
    frames_dir.mkdir()
    exe = next(c for c in CHROME if os.path.exists(c))
    srv = start_server({})
    try:
        with tempfile.TemporaryDirectory(prefix="demo_chrome_", ignore_cleanup_errors=True) as prof:
            ch = subprocess.Popen([exe, "--headless=new", f"--remote-debugging-port={CDP_PORT}",
                                   f"--user-data-dir={prof}", f"--window-size={W},{H}", "--no-first-run",
                                   "--disable-extensions", "--hide-scrollbars", "about:blank"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                frames, t_end = asyncio.run(record(f"{BASE}/viewer/", frames_dir))
            finally:
                ch.kill()
                ch.wait(timeout=30)
        qdir = work / "qgis"
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
        subprocess.run([QGIS_PY, str(REPO / "bench" / "demo_qgis.py"), BASE, str(qdir)], env=env,
                       check=True, cwd=REPO)
    finally:
        stop_server(srv)
    parts = [encode_browser(frames, t_end, work)] + encode_qgis(qdir, work)
    lst = work / "all.txt"
    lst.write_text("\n".join(f"file '{p.as_posix()}'" for p in parts))
    final = OUT / "geoguessers_demo.mp4"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                    str(final)], check=True)
    for png in sorted(qdir.glob("q*.png")):
        shutil.copy(png, OUT / f"qgis_{png.name}")
    print("wrote", final, f"{final.stat().st_size / 1e6:.1f} MB")
    if not a.keep_frames:
        shutil.rmtree(work, ignore_errors=True)
    else:
        print("frames kept in", work)


if __name__ == "__main__":
    main()
