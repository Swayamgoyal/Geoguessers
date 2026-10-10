"""Reference 3x3 terrain operators, vectorised with array slicing (NumPy, or CuPy when xp=cupy).

Input: a window `z` with a 1-cell halo on every side, shape (H+2, W+2). Output: shape (H, W).
Conventions follow gdaldem so results can be compared directly:
  slope in degrees; aspect in degrees clockwise from north, -9999 where flat; hillshade 1..255 (byte),
  0 = nodata; TRI (Riley / Wilson), TPI, roughness as in gdaldem.
  A cell whose 3x3 window contains nodata gets nodata (gdaldem without -compute_edges).

Window labels (row-major, north up):
    a b c        z[:-2, :-2]  z[:-2, 1:-1]  z[:-2, 2:]
    d e f   =    z[1:-1, :-2] z[1:-1, 1:-1] z[1:-1, 2:]
    g h i        z[2:, :-2]   z[2:, 1:-1]   z[2:, 2:]
"""
import numpy as np

NODATA = -9999.0


def _window(z):
    return (z[:-2, :-2], z[:-2, 1:-1], z[:-2, 2:],
            z[1:-1, :-2], z[1:-1, 1:-1], z[1:-1, 2:],
            z[2:, :-2], z[2:, 1:-1], z[2:, 2:])


def invalid_mask(z, nodata, xp=np):
    """True where the 3x3 window around a cell touches nodata (or NaN)."""
    bad = xp.isnan(z) if nodata is None else (z == nodata) | xp.isnan(z)
    out = xp.zeros((z.shape[0] - 2, z.shape[1] - 2), dtype=bool)
    for w in _window(bad):
        out |= w
    return out


def gradients(z, res, method="Horn", gdal_rounding=False):
    """dz/dx (east) and dz/dy (north) in height units per metre.
    gdal_rounding: add the Horn neighbour terms in float32 like GDAL's C code (for exact parity tests only;
    float64, the default, is more accurate)."""
    a, b, c, d, e, f, g, h, i = _window(z)
    if method == "Horn" and gdal_rounding:
        a, b, c, d, f, g, h, i = (v.astype("float32") for v in (a, b, c, d, f, g, h, i))
        dzdx = ((c + f + f + i) - (a + d + d + g)).astype("float64") / (8 * res)
        dzdy = ((a + b + b + c) - (g + h + h + i)).astype("float64") / (8 * res)
    elif method == "Horn":
        dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8 * res)
        dzdy = ((a + 2 * b + c) - (g + 2 * h + i)) / (8 * res)
    elif method == "ZevenbergenThorne":
        dzdx = (f - d) / (2 * res)
        dzdy = (b - h) / (2 * res)
    else:
        raise ValueError(method)
    return dzdx, dzdy


def slope(z, res, method="Horn", nodata=NODATA, xp=np, gdal_rounding=False):
    dzdx, dzdy = gradients(z, res, method, gdal_rounding)
    out = xp.degrees(xp.arctan(xp.sqrt(dzdx * dzdx + dzdy * dzdy)))
    return xp.where(invalid_mask(z, nodata, xp), NODATA, out).astype(xp.float32)


def aspect(z, res, method="Horn", nodata=NODATA, xp=np, gdal_rounding=False):
    """Direction the slope faces, degrees clockwise from north; -9999 where flat (gdaldem default)."""
    dzdx, dzdy = gradients(z, res, method, gdal_rounding)
    # downslope direction = -gradient; azimuth measured from north towards east
    out = xp.degrees(xp.arctan2(-dzdx, -dzdy)) % 360.0
    flat = (dzdx == 0) & (dzdy == 0)
    out = xp.where(flat, NODATA, out)
    return xp.where(invalid_mask(z, nodata, xp), NODATA, out).astype(xp.float32)


def hillshade(z, res, method="Horn", nodata=NODATA, azimuth=315.0, altitude=45.0, zfactor=1.0, xp=np,
              gdal_rounding=False):
    """Lambertian hillshade, gdaldem scaling: 1 + 254 * cos(angle to sun), clipped at 1; 0 = nodata."""
    dzdx, dzdy = gradients(z, res, method, gdal_rounding)
    dzdx, dzdy = dzdx * zfactor, dzdy * zfactor
    az, alt = np.radians(azimuth), np.radians(altitude)
    # surface normal (-dzdx, -dzdy, 1) dotted with the sun direction, divided by |normal|
    sun = (np.sin(az) * np.cos(alt), np.cos(az) * np.cos(alt), np.sin(alt))
    cang = (-dzdx * sun[0] - dzdy * sun[1] + sun[2]) / xp.sqrt(1 + dzdx * dzdx + dzdy * dzdy)
    out = xp.where(cang <= 0, 1.0, 1.0 + 254.0 * cang)
    out = xp.where(invalid_mask(z, nodata, xp), 0, out)
    return xp.floor(out + 0.5).clip(0, 255).astype(xp.uint8)


def tri(z, method="Riley", nodata=NODATA, xp=np):
    a, b, c, d, e, f, g, h, i = _window(z)
    nb = (a, b, c, d, f, g, h, i)
    if method == "Riley":
        out = xp.sqrt(sum((n - e) ** 2 for n in nb))
    elif method == "Wilson":
        out = sum(xp.abs(n - e) for n in nb) / 8.0
    else:
        raise ValueError(method)
    return xp.where(invalid_mask(z, nodata, xp), NODATA, out).astype(xp.float32)


def tpi(z, nodata=NODATA, xp=np):
    a, b, c, d, e, f, g, h, i = _window(z)
    out = e - (a + b + c + d + f + g + h + i) / 8.0
    return xp.where(invalid_mask(z, nodata, xp), NODATA, out).astype(xp.float32)


def roughness(z, nodata=NODATA, xp=np):
    w = _window(z)
    hi, lo = w[0], w[0]
    for v in w[1:]:
        hi, lo = xp.maximum(hi, v), xp.minimum(lo, v)
    out = hi - lo
    return xp.where(invalid_mask(z, nodata, xp), NODATA, out).astype(xp.float32)


def compute(op, z, res, method="", nodata=NODATA, xp=np, gdal_rounding=False):
    """Dispatch by gdaldem operator name. z is float64 with a 1-cell halo."""
    if op == "slope":
        return slope(z, res, method or "Horn", nodata, xp, gdal_rounding)
    if op == "aspect":
        return aspect(z, res, method or "Horn", nodata, xp, gdal_rounding)
    if op == "hillshade":
        return hillshade(z, res, method or "Horn", nodata, xp=xp, gdal_rounding=gdal_rounding)
    if op == "TRI":
        return tri(z, method or "Riley", nodata, xp)
    if op == "TPI":
        return tpi(z, nodata, xp)
    if op == "roughness":
        return roughness(z, nodata, xp)
    raise ValueError(op)
