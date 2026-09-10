#!/usr/bin/env python3
"""Test bodies for the calibration sweeps.

    pillars  two towers with a gap -- strings show in the gap (retraction)
    block    a plain full-scale slab, for squeezing
    rbox     a rounded box -- the default squish coupon: flat bottom to print
             on, curved sides for the wall to wrap, and a broad flat-ish top
             you can actually press a thumb into
    dome     a domed coupon for squeezing -- curvature changes how a single
             wall wraps the surface and adds the arch effect a flat block
             cannot show, so it compresses more like a real rounded part
    plate    flat slab with a solid top -- over/under extrusion shows on the
             top surface (flow ratio) and under-extrusion shows when the
             volumetric cap is raised too far (max flowrate)

Geometry is deliberately trivial so it is always manifold and always slices.
"""
import argparse
import os
import sys

from make_temp_tower import box, write_stl


def pillars(size=10.0, gap=15.0, height=25.0, base=1.2, overhang=2.0):
    width = size * 2 + gap
    o = overhang
    tris = []
    tris += box(-o, -o, 0, width + o, size + o, base)
    tris += box(0, 0, 0, size, size, base + height)
    tris += box(size + gap, 0, 0, width, size, base + height)
    return tris, (width + 2 * o, size + 2 * o, base + height)


def plate(x=25.0, y=25.0, z=2.4):
    return box(0, 0, 0, x, y, z), (x, y, z)


def rbox(x=62.0, y=40.0, z=30.0, radius=12.0, n_lat=20, n_lon=40):
    """Box with rounded edges and corners (a box swept by a sphere).

    Built by taking a sphere and pushing each vertex outward by the box's half
    extents according to which octant it sits in. Topology is unchanged, so
    the result stays closed; the seams collapse to zero-area triangles, which
    every slicer drops.

    Flat bottom, so it needs no supports and gives real bed contact. Height is
    the real part's thickness -- that is what squish depends on.
    """
    import math

    radius = min(radius, x / 2 - 0.5, y / 2 - 0.5, z / 2 - 0.5)
    hx, hy, hz = x / 2 - radius, y / 2 - radius, z / 2 - radius

    def place(nx, ny, nz):
        # cos(pi/2) comes back as ~6e-17, not 0, so a vertex that should sit
        # exactly on an axis gets pushed a whole half-extent to one side and
        # the seam lands one vertex off. Snap it first.
        eps = 1e-9
        nx = 0.0 if abs(nx) < eps else nx
        ny = 0.0 if abs(ny) < eps else ny
        nz = 0.0 if abs(nz) < eps else nz
        sx = hx if nx > 0 else (-hx if nx < 0 else 0.0)
        sy = hy if ny > 0 else (-hy if ny < 0 else 0.0)
        sz = hz if nz > 0 else (-hz if nz < 0 else 0.0)
        return (radius * nx + sx, radius * ny + sy, radius * nz + sz + hz + radius)

    rings = []
    for i in range(n_lat + 1):
        theta = math.pi * i / n_lat                       # 0 = north pole
        nz, cr = math.cos(theta), math.sin(theta)
        rings.append([place(cr * math.cos(2 * math.pi * j / n_lon),
                            cr * math.sin(2 * math.pi * j / n_lon), nz)
                      for j in range(n_lon)])

    tris = []
    for i in range(n_lat):
        a, b = rings[i], rings[i + 1]
        for j in range(n_lon):
            k = (j + 1) % n_lon
            tris.append((a[j], b[j], b[k]))
            tris.append((a[j], b[k], a[k]))
    return tris, (x, y, z)


def dome(rx=35.0, ry=28.0, rz=30.0, n_lat=24, n_lon=48):
    """Half-ellipsoid on a flat base, watertight.

    HEIGHT is the thing to keep honest: squish depends on wall thickness
    relative to the part's thickness, so the dome is built at the real part's
    thickness and only its footprint is reduced. Shrinking the height too
    would stiffen it the same way scaling the whole model down does.
    """
    import math

    # rings from the equator (i=0) up to just below the pole
    rings = []
    for i in range(n_lat):
        theta = (i / n_lat) * (math.pi / 2)
        cz, cr = math.sin(theta) * rz, math.cos(theta)
        ring = [(rx * cr * math.cos(2 * math.pi * j / n_lon),
                 ry * cr * math.sin(2 * math.pi * j / n_lon),
                 cz) for j in range(n_lon)]
        rings.append(ring)
    pole = (0.0, 0.0, rz)

    tris = []
    for i in range(n_lat - 1):
        a, b = rings[i], rings[i + 1]
        for j in range(n_lon):
            k = (j + 1) % n_lon
            tris.append((a[j], b[j], b[k]))
            tris.append((a[j], b[k], a[k]))
    for j in range(n_lon):                      # cap to the pole
        k = (j + 1) % n_lon
        tris.append((rings[-1][j], pole, rings[-1][k]))

    centre = (0.0, 0.0, 0.0)                    # flat bottom, wound downward
    for j in range(n_lon):
        k = (j + 1) % n_lon
        tris.append((rings[0][j], rings[0][k], centre))
    return tris, (2 * rx, 2 * ry, rz)


def block(x=50.0, y=50.0, z=30.0):
    """A squish coupon: printed at the real part's wall/infill recipe, at FULL
    scale, so it compresses the way the real part will.

    Scaling the real model down instead would be misleading: wall thickness
    does not scale, so a quarter-size copy has proportionally four times the
    wall and feels far stiffer than the part it is standing in for."""
    return box(0, 0, 0, x, y, z), (x, y, z)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("shape", choices=["pillars", "plate", "block", "rbox", "dome"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--height", type=float, default=None)
    ap.add_argument("--size", type=float, default=50.0, help="coupon XY size")
    ap.add_argument("--radius", type=float, default=12.0, help="rbox corner radius")
    ap.add_argument("--aspect-from", default=None,
                    help="an STL to copy X:Y proportions from, so the coupon "
                         "has the real part's footprint shape")
    a = ap.parse_args()

    if a.shape == "pillars":
        tris, dims = pillars(height=a.height if a.height else 25.0)
    elif a.shape == "block":
        tris, dims = block(x=a.size, y=a.size, z=a.height if a.height else 30.0)
    elif a.shape == "rbox":
        ratio = 1.0
        if a.aspect_from and os.path.exists(a.aspect_from):
            from inspect_models import read_stl, analyse
            bbox, *_ = analyse(read_stl(a.aspect_from)[0])
            if bbox[0] and bbox[1]:
                ratio = bbox[1] / bbox[0]
        tris, dims = rbox(x=a.size, y=a.size * ratio,
                          z=a.height if a.height else 30.0, radius=a.radius)
    elif a.shape == "dome":
        ratio = 1.0
        if a.aspect_from and os.path.exists(a.aspect_from):
            from inspect_models import read_stl, analyse
            bbox, *_ = analyse(read_stl(a.aspect_from)[0])
            if bbox[0] and bbox[1]:
                ratio = bbox[1] / bbox[0]       # depth : width of the real part
        rx = a.size / 2.0
        tris, dims = dome(rx=rx, ry=rx * ratio,
                          rz=a.height if a.height else 30.0)
    else:
        tris, dims = plate(z=a.height if a.height else 2.4)

    write_stl(a.out, tris)
    print(f"# {a.shape}: {dims[0]:.0f} x {dims[1]:.0f} x {dims[2]:.1f} mm -> {a.out}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
