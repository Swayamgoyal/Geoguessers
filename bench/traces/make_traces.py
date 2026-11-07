"""Write the seeded E6 traces (bench/traces/*.json). Run once; the files are committed so every run replays the same
gestures:
    python -m bench.traces.make_traces

A trace is a list of timed input events for a 1600 x 900 CSS-pixel view (DPR 1):
    [t, "pan", dx, dy]                     drag by (dx, dy) screen pixels (one event per 60 Hz frame)
    [t, "wheel", factor, sx, sy, g]        one wheel tick: zoom by `factor` (< 1 = in) about screen point (sx, sy)
    [t, "box", x0, y0, x1, y1, g]          Shift + drag box zoom (animated 350 ms, one commit)
g numbers the zoom gestures. The start is {"fit": true} (whole map) or {"u", "v", "level"}: the view centre offset
from the data centre in view widths at that pyramid level, pixel size in the middle of the level (res * sqrt 2).
Traces are dataset-independent: pans stay within +-3.5 view widths of the start level (both datasets are at least
7.6 level-0 view widths across), zooms within levels 0-3.

Families (spec "Traces"): pan-line, pan-reverse (0.5 / 1 / 2 view widths per second, 5 s), pan-walk (random
heading changes every 0.3-1 s), zoom-burst (0.3 / 1 / 2 s of 60 Hz wheel ticks, in and out, 1 / 2 / 3 levels),
zoom-pan (alternating bursts and pans, 10 s), box (nested boxes from the whole map to full resolution).
"""
import json
import math
import random
from pathlib import Path

W, H, FPS = 1600, 900, 60
OUT = Path(__file__).resolve().parent


def pan_step(speed, heading):
    """Screen-pixel drag per frame that moves the camera `speed` view widths per second towards `heading`."""
    step = speed * W / FPS
    return -step * math.cos(heading), step * math.sin(heading)


def pan_line(speed, seed, reverse=False):
    rng = random.Random(seed)
    h = math.radians(45 + rng.uniform(-20, 20) + 90 * rng.randrange(4))   # roughly diagonal: longest path in data
    dur = 5.0
    reach = speed * (dur / 2 if reverse else dur)                           # furthest point, in view widths
    start = {"u": -0.5 * reach * math.cos(h), "v": -0.5 * reach * math.sin(h), "level": 0}
    ev = []
    dx, dy = pan_step(speed, h)
    n = int(dur * FPS)
    for i in range(n):
        s = -1 if reverse and i >= n // 2 else 1
        ev.append([round(0.2 + i / FPS, 4), "pan", round(s * dx, 3), round(s * dy, 3)])
    name = f"pan-{'reverse' if reverse else 'line'}-{speed:g}"
    return {"name": name, "family": "pan-reverse" if reverse else "pan-line",
            "params": {"speed_views_per_s": speed, "heading_deg": round(math.degrees(h), 1), "seconds": dur},
            "seed": seed, "start": start, "events": ev}


def pan_walk(seed, speed=1.0, dur=6.0, bound=3.0):
    rng = random.Random(seed)
    h = rng.uniform(0, 2 * math.pi)
    x = y = 0.0
    next_turn = rng.uniform(0.3, 1.0)
    ev = []
    for i in range(int(dur * FPS)):
        t = i / FPS
        if t >= next_turn:
            h += math.radians(rng.uniform(-90, 90))
            next_turn = t + rng.uniform(0.3, 1.0)
        nx, ny = x + speed / FPS * math.cos(h), y + speed / FPS * math.sin(h)
        if abs(nx) > bound:
            h = math.pi - h
        if abs(ny) > bound:
            h = -h
        x, y = x + speed / FPS * math.cos(h), y + speed / FPS * math.sin(h)
        dx, dy = pan_step(speed, h)
        ev.append([round(0.2 + t, 4), "pan", round(dx, 3), round(dy, 3)])
    return {"name": "pan-walk", "family": "pan-walk", "params": {"speed_views_per_s": speed, "seconds": dur},
            "seed": seed, "start": {"u": 0, "v": 0, "level": 0}, "events": ev}


def zoom_burst(direction, seconds, levels, seed):
    rng = random.Random(seed)
    n = max(1, round(seconds * FPS))
    factor = 2 ** ((-levels if direction == "in" else levels) / n)
    sx, sy = W / 2 + rng.uniform(-0.15, 0.15) * W, H / 2 + rng.uniform(-0.15, 0.15) * H
    ev = [[round(0.2 + i / FPS, 4), "wheel", factor, round(sx, 1), round(sy, 1), 0] for i in range(n)]
    return {"name": f"zoom-burst-{direction}-{seconds:g}", "family": "zoom-burst",
            "params": {"direction": direction, "seconds": seconds, "levels": levels, "ticks": n},
            "seed": seed, "start": {"u": 0, "v": 0, "level": 3 if direction == "in" else 0}, "events": ev}


def zoom_pan(seed, dur=10.0, start_level=2, bound=2.5):
    rng = random.Random(seed)
    t, level, g = 0.2, float(start_level), 0
    x = y = 0.0                                        # camera position in level-0 view widths
    ev = []
    while t < dur:
        d = rng.choice([-1, 1])
        if level + d < 0 or level + d > 3:
            d = -d
        sx, sy = W / 2 + rng.uniform(-0.15, 0.15) * W, H / 2 + rng.uniform(-0.15, 0.15) * H
        n = 30                                         # 0.5 s burst, one level
        for i in range(n):
            ev.append([round(t + i / FPS, 4), "wheel", 2 ** (d / n), round(sx, 1), round(sy, 1), g])
        t += n / FPS + 0.4                             # hold: the commit lands before the pan
        level += d
        g += 1
        h = rng.uniform(0, 2 * math.pi)
        for i in range(FPS):                           # 1 s pan at 0.5 view widths per second
            step = 0.5 / FPS * 2 ** level              # in level-0 view widths
            if abs(x + step * math.cos(h)) > bound:
                h = math.pi - h
            if abs(y + step * math.sin(h)) > bound:
                h = -h
            x, y = x + step * math.cos(h), y + step * math.sin(h)
            dx, dy = pan_step(0.5, h)
            ev.append([round(t + i / FPS, 4), "pan", round(dx, 3), round(dy, 3)])
        t += 1.0 + 0.3
    return {"name": "zoom-pan", "family": "zoom-pan", "params": {"seconds": dur, "burst_s": 0.5, "pan_s": 1.0},
            "seed": seed, "start": {"u": 0, "v": 0, "level": start_level}, "events": ev}


def boxes(seed, n=3, gap=1.6):
    rng = random.Random(seed)
    ev, t = [], 0.5
    for g in range(n):
        jx, jy = (0.1, 0.15) if g == 0 else (0.2, 0.2)          # first box stays on the data (whole-map view)
        cx, cy = W / 2 + rng.uniform(-jx, jx) * W, H / 2 + rng.uniform(-jy, jy) * H
        bw, bh = W / 4, H / 4                                    # x4 per box: two pyramid levels
        ev.append([round(t, 3), "box", round(cx - bw / 2, 1), round(cy - bh / 2, 1), round(cx + bw / 2, 1),
                   round(cy + bh / 2, 1), g])
        t += 0.35 + gap
    return {"name": "box", "family": "box", "params": {"boxes": n, "zoom_per_box": 4, "gap_s": gap},
            "seed": seed, "start": {"fit": True}, "events": ev}


def all_traces():
    out = []
    for i, sp in enumerate((0.5, 1, 2)):
        out.append(pan_line(sp, 100 + i))
        out.append(pan_line(sp, 200 + i, reverse=True))
    out.append(pan_walk(300))
    for i, (sec, lv) in enumerate(((0.3, 1), (1, 2), (2, 3))):
        out.append(zoom_burst("in", sec, lv, 400 + i))
        out.append(zoom_burst("out", sec, lv, 500 + i))
    out.append(zoom_pan(600))
    out.append(boxes(700))
    for tr in out:
        tr["view"] = [W, H]
        tr["duration"] = tr["events"][-1][0]
    return out


def main():
    for tr in all_traces():
        (OUT / f"{tr['name']}.json").write_text(json.dumps(tr, separators=(",", ":")))
        print(f"{tr['name']:22s} {len(tr['events']):4d} events, {tr['duration']:.1f} s")


if __name__ == "__main__":
    main()
