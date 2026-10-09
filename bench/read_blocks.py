"""Read-only reference: read + decompress every full-resolution block of band 1, nothing else.

Used as the 'read' stage in E1/E2. Prints {"t_internal": seconds spent reading (excludes
Python/GDAL start-up), "blocks": n, "mb": uncompressed MB} as its last line.

    python -m bench.read_blocks <raster>
"""
import json
import sys
import time

from osgeo import gdal

gdal.UseExceptions()


def main(path):
    ds = gdal.Open(path)
    band = ds.GetRasterBand(1)
    bx, by = band.GetBlockSize()
    nx, ny = -(-band.XSize // bx), -(-band.YSize // by)
    buf = bytearray(bx * by * gdal.GetDataTypeSize(band.DataType) // 8)
    t = time.perf_counter()
    for j in range(ny):
        for i in range(nx):
            band.ReadBlock(i, j, buf_obj=buf)  # decompress into a reused buffer; bypasses the block cache
    dt = time.perf_counter() - t
    mb = band.XSize * band.YSize * gdal.GetDataTypeSize(band.DataType) / 8 / 2**20
    print(json.dumps({"t_internal": round(dt, 4), "blocks": nx * ny, "mb": round(mb, 1)}))


if __name__ == "__main__":
    main(sys.argv[1])
