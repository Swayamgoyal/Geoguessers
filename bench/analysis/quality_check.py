"""Quality check of a sweep: spread between repeats and background ('foreign') disk reads per dataset.

foreign disk = bytes read from the physical disks during a run minus bytes the measured process read
itself; a large value means another process was using the disk while we measured.

    python -m bench.analysis.quality_check [results/runs.csv]
"""
import sys

import pandas as pd


def report(path):
    d = pd.read_csv(path)
    d = d[d.ok & (d.rep >= 1)].copy()
    d["method"] = d.method.fillna("")
    d["variant"] = d.variant.fillna("")
    d["foreign_mb"] = (d.disk_read_mb - d.proc_read_mb).clip(lower=0)
    g = d.groupby(["experiment", "dataset", "variant", "op", "method", "cache_state"])
    s = (100 * (g.t_total.max() - g.t_total.min()) / g.t_total.median()).rename("spread")
    out = s.reset_index().groupby(["experiment", "dataset"]).spread.agg(
        median="median", max="max", over10=lambda x: int((x > 10).sum()), configs="count")
    out["runs foreign>200MB"] = d.groupby(["experiment", "dataset"]).foreign_mb.agg(lambda x: int((x > 200).sum()))
    out["median t s"] = d.groupby(["experiment", "dataset"]).t_total.median()
    return out.round(1)


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    print(report(sys.argv[1] if len(sys.argv) > 1 else "results/runs.csv").to_string())
