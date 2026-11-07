"""Shared fixtures: a small COG pyramid with data gaps and partial edge tiles (Phase 5 viewer tests)."""
import subprocess

import pytest

from demlab.view import Pyramid
from tests.fixtures import DATA

SRC = DATA / "prepared" / "tile571_8m.tif"


@pytest.fixture(scope="session")
def cog(tmp_path_factory):
    """1300 x 1100-cell COG with overviews from the 8 m tile's gappy south-east part: 3 x 3 tiles at level 0
    (partial at the right and bottom), nodata gaps, two overview levels; plus a gdaldem slope pyramid of it."""
    d = tmp_path_factory.mktemp("view")
    out = d / "fixture_cog.tif"
    subprocess.run(["gdal_translate", "-q", "-srcwin", "11500", "10500", "1300", "1100", "-of", "COG",
                    "-co", "BLOCKSIZE=512", "-co", "COMPRESS=ZSTD", "-co", "PREDICTOR=3",
                    "-co", "OVERVIEW_RESAMPLING=AVERAGE", str(SRC), str(out)], check=True)
    slope = d / "fixture_slope.tif"
    tmp = d / "slope_raw.tif"
    subprocess.run(["gdaldem", "slope", "-q", str(out), str(tmp)], check=True)
    subprocess.run(["gdal_translate", "-q", "-of", "COG", "-co", "BLOCKSIZE=512", "-co", "COMPRESS=ZSTD",
                    "-co", "OVERVIEW_RESAMPLING=AVERAGE", str(tmp), str(slope)], check=True)
    return out, slope


@pytest.fixture(scope="session")
def pyr(cog):
    return Pyramid(cog[0], name="fixture", precomputed=cog[1])
