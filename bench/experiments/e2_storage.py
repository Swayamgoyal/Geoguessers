"""E2: how much does storage layout / compression matter, compared with the algorithm?

The same grid is written in 7 layouts (strips vs tiles, 256 vs 512 tiles, no compression vs
LZW / DEFLATE / ZSTD with the floating-point predictor). For each layout: the conversion itself
('create', 1 run: measures the write/compress cost), a pure read ('read'), and gdaldem slope Horn.
Datasets: real 8 m (full protocol) and synthetic 2 m (3 cold + 1 warm). Variants are written to
$GEO_DATA/e2/ and kept, so file sizes can be compared afterwards.

    python -m bench.experiments.e2_storage --plan
    python -m bench.experiments.e2_storage
"""
import argparse

from bench.harness import tool
from bench.sweep import CSV, DATA, impl_of, raster_meta, run_jobs

E2_DIR = DATA / "e2"
DATASETS = [
    ("tile571_8m", DATA / "prepared" / "tile571_8m.tif", 8, "real", range(1, 6), range(0, 6)),
    ("tile571_2m_cubic", DATA / "synthetic" / "tile571_2m_cubic.tif", 2, "synthetic", range(1, 4), range(1, 2)),
]
TILED = ["TILED=YES"]
PRED = ["PREDICTOR=3"]  # floating-point predictor: what you would use for a float DEM in practice
VARIANTS = {
    "strip_none": [],  # GDAL's default GTiff: strips, uncompressed
    "tile256_none": TILED + ["BLOCKXSIZE=256", "BLOCKYSIZE=256"],
    "tile512_none": TILED + ["BLOCKXSIZE=512", "BLOCKYSIZE=512"],
    "tile512_lzw": TILED + ["BLOCKXSIZE=512", "BLOCKYSIZE=512", "COMPRESS=LZW"] + PRED,
    "tile512_deflate": TILED + ["BLOCKXSIZE=512", "BLOCKYSIZE=512", "COMPRESS=DEFLATE"] + PRED,
    "tile512_zstd": TILED + ["BLOCKXSIZE=512", "BLOCKYSIZE=512", "COMPRESS=ZSTD"] + PRED,
    "tile256_zstd": TILED + ["BLOCKXSIZE=256", "BLOCKYSIZE=256", "COMPRESS=ZSTD"] + PRED,
}


def variant_path(name, variant):
    return E2_DIR / f"{name}_{variant}.tif"


def jobs_for():
    E2_DIR.mkdir(parents=True, exist_ok=True)
    jobs = []
    for name, src, res, kind, cold_reps, warm_reps in DATASETS:
        cells, _, _ = raster_meta(src)
        for variant, co in VARIANTS.items():
            dst = variant_path(name, variant)
            base = {"experiment": "E2", "dataset": name, "variant": variant, "res_m": res, "cells": cells,
                    "real_or_synthetic": kind, "format": "strips" if variant.startswith("strip") else "tiled",
                    "compression": variant.split("_")[1], "device": "cpu", "threads": 1}
            create = [tool("gdal_translate"), "-q", "-of", "GTiff", str(src), str(dst), "-co", "BIGTIFF=IF_SAFER"]
            for c in co:
                create += ["-co", c]
            # the file is the input of the later runs, so it is written in place (not to bench_out)
            jobs.append({**base, "op": "create", "method": "gdal_translate", "impl": "gdal_translate",
                         "cache_state": "warm", "rep": 1, "_src": src, "_cmd": create})
            for op, method in [("read", "blocks"), ("slope", "Horn")]:
                for cache, reps in (("cold", cold_reps), ("warm", warm_reps)):
                    for rep in reps:
                        jobs.append({**base, "op": op, "method": method, "impl": impl_of(op),
                                     "cache_state": cache, "rep": rep, "_src": dst})
    return jobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true", help="only list the runs")
    ap.add_argument("--csv", default=str(CSV))
    ap.add_argument("--allow-battery", action="store_true")
    a = ap.parse_args()
    run_jobs(jobs_for(), "E2", a.csv, a.plan, a.allow_battery)


if __name__ == "__main__":
    main()
