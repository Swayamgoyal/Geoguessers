"""Colour maps for terrain products, and 8-bit palette PNG encoding of tiles.

Each tile is quantised to one byte per cell: index 0 = nodata (fully transparent), 1..255 = the value range of the
colour map. A 256-entry palette maps the bytes to colours. Palette PNGs are ~4× smaller than RGBA and fast to encode.
Both steps release the GIL (a compiled nogil quantiser, and zlib compression), so tiles colour and encode in parallel
on the server's worker threads.

    idx = quantise("slope", values, cmap)          # uint8, 0 = nodata
    png = encode_png(idx, palette(cmap["name"]))
"""
import struct
import zlib

import numba as nb
import numpy as np

NODATA = -9999.0
PNG_SIGNATURE = bytes([137, 80, 78, 71, 13, 10, 26, 10])

# default colour map and display range per operator (vmin, vmax in the product's unit)
DEFAULTS = {
    "slope": {"name": "slope", "vmin": 0.0, "vmax": 70.0},          # degrees
    "aspect": {"name": "aspect", "vmin": 0.0, "vmax": 360.0},       # degrees, cyclic
    "hillshade": {"name": "gray", "vmin": 1.0, "vmax": 255.0},      # grey value
    "TRI": {"name": "rugged", "vmin": 0.0, "vmax": 40.0},           # metres
    "TPI": {"name": "diverging", "vmin": -10.0, "vmax": 10.0},      # metres
    "roughness": {"name": "rugged", "vmin": 0.0, "vmax": 60.0},     # metres
    "elevation": {"name": "terrain", "vmin": 500.0, "vmax": 7800.0},  # metres
}

# colour anchors (position 0..1, RGB)
_ANCHORS = {
    "slope": [(0.0, (255, 255, 204)), (0.25, (161, 218, 180)), (0.5, (65, 182, 196)), (0.75, (34, 94, 168)),
              (1.0, (12, 44, 132))],
    "gray": [(0.0, (0, 0, 0)), (1.0, (255, 255, 255))],
    "rugged": [(0.0, (255, 255, 229)), (0.35, (254, 196, 79)), (0.7, (217, 95, 14)), (1.0, (102, 37, 6))],
    "diverging": [(0.0, (33, 102, 172)), (0.5, (247, 247, 247)), (1.0, (178, 24, 43))],
    "terrain": [(0.0, (26, 150, 65)), (0.35, (166, 217, 106)), (0.6, (230, 200, 140)), (0.8, (140, 100, 70)),
                (1.0, (255, 255, 255))],
}


def palette(name):
    """256 × 3 uint8 palette; entry 0 (nodata) is black and made transparent when encoding."""
    pal = np.zeros((256, 3), np.uint8)
    t = np.linspace(0.0, 1.0, 255)
    if name == "aspect":  # cyclic hue wheel: north = red, east = yellow-green, south = cyan, west = blue-magenta
        pal[1:] = (_hue(t) * 220 + 20).astype(np.uint8)
        return pal
    pos = np.array([p for p, _ in _ANCHORS[name]])
    col = np.array([c for _, c in _ANCHORS[name]], np.float64)
    for ch in range(3):
        pal[1:, ch] = np.round(np.interp(t, pos, col[:, ch])).astype(np.uint8)
    return pal


def _hue(t):
    """RGB in 0..1 for hue t in [0, 1)."""
    h = (t % 1.0) * 6.0
    i = np.floor(h).astype(int) % 6
    f = h - np.floor(h)
    q, p = 1 - f, f
    one, zero = np.ones_like(f), np.zeros_like(f)
    r = np.choose(i, [one, q, zero, zero, p, one])
    g = np.choose(i, [p, one, one, q, zero, zero])
    b = np.choose(i, [zero, zero, p, one, one, q])
    return np.stack([r, g, b], 1)


@nb.njit(nogil=True, cache=True)
def _quantise(v, nod, lo, hi, cyclic, out):
    scale = 254.0 / max(hi - lo, 1e-12)
    H, W = v.shape
    for r in range(H):
        for c in range(W):
            x = np.float64(v[r, c])
            if x == nod or x != x:
                out[r, c] = 0
            elif cyclic:
                q = np.floor((x % 360.0) / 360.0 * 255.0)
                out[r, c] = 1 + int(min(max(q, 0.0), 254.0))
            else:
                q = np.floor((x - lo) * scale + 0.5)
                out[r, c] = 1 + int(min(max(q, 0.0), 254.0))


def quantise(op, values, cmap):
    """uint8 indices: 0 = nodata, 1..255 = vmin..vmax (clipped, rounded). Aspect wraps around the circle."""
    v = np.ascontiguousarray(values)
    v2 = v.reshape(1, -1) if v.ndim == 1 else v
    out = np.empty(v2.shape, np.uint8)
    _quantise(v2, float(0 if op == "hillshade" else NODATA), float(cmap["vmin"]), float(cmap["vmax"]),
              op == "aspect", out)
    return out.reshape(v.shape)


def _chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(data, zlib.crc32(kind)))


def encode_png(idx, pal, compress_level=1):
    """8-bit palette PNG (filter type 0 per row) with index 0 fully transparent. zlib releases the GIL.
    Run-length deflate (Z_RLE): 2-3x faster than default deflate for 5-15% larger tiles (measured on Chamoli)."""
    h, w = idx.shape
    raw = np.empty((h, w + 1), np.uint8)
    raw[:, 0] = 0
    raw[:, 1:] = idx
    trns = bytes([0]) + bytes([255]) * 255
    return (PNG_SIGNATURE + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0))
            + _chunk(b"PLTE", np.ascontiguousarray(pal, np.uint8).tobytes()) + _chunk(b"tRNS", trns)
            + _chunk(b"IDAT", _deflate(raw.tobytes(), compress_level)) + _chunk(b"IEND", b""))


def _deflate(data, level):
    z = zlib.compressobj(level, zlib.DEFLATED, 15, 8, zlib.Z_RLE)
    return z.compress(data) + z.flush()


def legend(op, cmap=None, n=8):
    """Colour stops for a UI legend: [(value, '#rrggbb'), ...]."""
    cmap = {**DEFAULTS[op], **(cmap or {})}
    pal = palette(cmap["name"])
    vals = np.linspace(cmap["vmin"], cmap["vmax"], n)
    idx = quantise(op, vals if op != "aspect" else np.linspace(0, 359.9, n), cmap)
    return [(float(v), "#%02x%02x%02x" % tuple(int(c) for c in pal[i])) for v, i in zip(vals, idx)]
