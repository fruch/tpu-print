#!/usr/bin/env python3
"""Test bodies for the calibration sweeps.

    pillars  two towers with a gap -- strings show in the gap (retraction)
    plate    flat slab with a solid top -- over/under extrusion shows on the
             top surface (flow ratio) and under-extrusion shows when the
             volumetric cap is raised too far (max flowrate)

Geometry is deliberately trivial so it is always manifold and always slices.
"""
import argparse
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("shape", choices=["pillars", "plate"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--height", type=float, default=None)
    a = ap.parse_args()

    if a.shape == "pillars":
        tris, dims = pillars(height=a.height if a.height else 25.0)
    else:
        tris, dims = plate(z=a.height if a.height else 2.4)

    write_stl(a.out, tris)
    print(f"# {a.shape}: {dims[0]:.0f} x {dims[1]:.0f} x {dims[2]:.1f} mm -> {a.out}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
