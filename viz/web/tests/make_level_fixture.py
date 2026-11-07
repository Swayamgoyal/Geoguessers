"""Write tests/levels_fixture.json: real pyramid levels and the server's level choice for many pixel sizes, so the
browser's mirror of the rule (js/levels.js) is checked against demlab/view.py.   python viz/web/tests/make_level_fixture.py
(run from the repo root with PYTHONPATH=.)"""
import json
from pathlib import Path

import numpy as np

from demlab.service import default_datasets
from demlab.view import Pyramid

out = {}
for name, (path, _) in default_datasets().items():
    p = Pyramid(path, name=name)
    info = p.info()
    cases = []
    for s in np.geomspace(p.levels[0].res / 4, p.levels[-1].res * 4, 60):
        for prev in (None, 0, 2, len(p.levels) - 1):
            cases.append([float(s), prev, p.choose_level(float(s), prev=prev)])
    out[name] = {"levels": info["levels"], "cases": cases}
Path(__file__).with_name("levels_fixture.json").write_text(json.dumps(out))
print({k: len(v["cases"]) for k, v in out.items()})
