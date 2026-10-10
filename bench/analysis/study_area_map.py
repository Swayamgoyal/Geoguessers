"""Study-area map for the reports: shaded relief of HMA tile-571 (8 m, read from a small pyramid level)
with the Chamoli 2 m sub-area outlined. Writes report/figures/study_area.png.

    python -m bench.analysis.study_area_map
"""
from pathlib import Path

import matplotlib
import numpy as np
import rasterio
from rasterio.enums import Resampling

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

DATA = Path(r"D:\geoguessers_data\prepared")
OUT = Path(__file__).resolve().parents[2] / "report" / "figures" / "study_area.png"
INK, INK2, SURF, ACCENT = "#0b0b0b", "#52514e", "#fcfcfb", "#eb6834"

with rasterio.open(DATA / "tile571_8m.tif") as ds:
    f = 16  # 8 m -> 128 m: ~820 x 800 px
    z = ds.read(1, out_shape=(ds.height // f, ds.width // f), resampling=Resampling.average, masked=True)
    b = ds.bounds
    res = (b.right - b.left) / z.shape[1]
with rasterio.open(DATA / "chamoli_2m.tif") as c:
    cb = c.bounds

# Horn-style hillshade, light from the north-west, 45 deg altitude
zf = z.filled(np.nan)
gy, gx = np.gradient(zf, res)
slope = np.arctan(np.hypot(gx, gy))
aspect = np.arctan2(-gx, gy)
az, alt = np.radians(315), np.radians(45)
hs = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
hs = np.ma.masked_invalid(hs)

plt.rcParams.update({"font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 9})
fig, ax = plt.subplots(figsize=(5.2, 5.2), facecolor=SURF)
km = 1000
ext = [b.left / km, b.right / km, b.bottom / km, b.top / km]
ax.imshow(hs, cmap="gray", extent=ext, vmin=-0.2, vmax=1.0, interpolation="bilinear")
ax.add_patch(Rectangle((cb.left / km, cb.bottom / km), (cb.right - cb.left) / km, (cb.top - cb.bottom) / km,
                       fill=False, ec=ACCENT, lw=2))
ax.annotate("Chamoli 2 m sub-area\n(30 x 35 km)", (cb.right / km, cb.top / km), xytext=(8, 6),
            textcoords="offset points", color=INK, fontsize=9,
            bbox=dict(boxstyle="round,pad=0.25", fc=SURF, ec="none", alpha=0.85))
ax.set_xlabel("UTM 44N easting (km)", color=INK2)
ax.set_ylabel("UTM 44N northing (km)", color=INK2)
ax.set_title("Study area: HMA tile-571, Uttarakhand (8 m, ~105 x 103 km)", loc="left", fontsize=10,
             fontweight="bold", color=INK)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
ax.tick_params(colors="#898781")
OUT.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(OUT, dpi=170, bbox_inches="tight", facecolor=SURF)
print("wrote", OUT)
