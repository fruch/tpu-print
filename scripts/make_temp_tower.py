#!/usr/bin/env python3
"""Generate a banded calibration tower: STL plus the matching layer-change G-code.

The point is that the geometry and the temperature changes come from the same
numbers, so a band can never be labelled one temperature and printed at
another -- the mistake that makes a hand-set-up tower worthless.

Shape: two square pillars on a shared base slab. The nozzle travels between
the pillars on every layer, so stringing (TPU's dominant failure) shows up in
the gap. Hottest band at the bottom, cooling upward, so the well-adhered end
is the hot one.

    python3 scripts/make_temp_tower.py --start 235 --end 200 --step 5

Writes the STL and prints the layer-change G-code on stdout.
"""
import argparse
import struct
import sys

# (x, y, z) corners -> 12 triangles, outward normals
def box(x0, y0, z0, x1, y1, z1):
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    faces = [
        (0, 2, 1), (0, 3, 2),      # bottom
        (4, 5, 6), (4, 6, 7),      # top
        (0, 1, 5), (0, 5, 4),      # -y
        (1, 2, 6), (1, 6, 5),      # +x
        (2, 3, 7), (2, 7, 6),      # +y
        (3, 0, 4), (3, 4, 7),      # -x
    ]
    return [(v[a], v[b], v[c]) for a, b, c in faces]


def write_stl(path, tris):
    # Drop zero-area triangles. Shapes built by offsetting a sphere (rbox)
    # collapse their seams to lines; those carry no surface, and leaving them
    # in makes every manifold check report the mesh as non-watertight.
    def degenerate(t):
        k = [tuple(round(c, 5) for c in v) for v in t]
        return k[0] == k[1] or k[1] == k[2] or k[2] == k[0]

    tris = [t for t in tris if not degenerate(t)]
    with open(path, "wb") as fh:
        fh.write(b"\0" * 80)
        fh.write(struct.pack("<I", len(tris)))
        for a, b, c in tris:
            # normal left at 0,0,0 -- every slicer recomputes from winding
            fh.write(struct.pack("<3f", 0.0, 0.0, 0.0))
            for p in (a, b, c):
                fh.write(struct.pack("<3f", *p))
            fh.write(struct.pack("<H", 0))


def temps(start, end, step):
    step = abs(step)
    if start >= end:
        seq = list(range(start, end - 1, -step))
    else:
        seq = list(range(start, end + 1, step))
    if seq[-1] != end:
        seq.append(end)
    return seq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=235, help="bottom band temp")
    ap.add_argument("--end", type=int, default=200, help="top band temp")
    ap.add_argument("--step", type=int, default=5)
    ap.add_argument("--band-height", type=float, default=6.0)
    ap.add_argument("--pillar", type=float, default=10.0, help="pillar XY size")
    ap.add_argument("--gap", type=float, default=15.0, help="clear gap between pillars")
    ap.add_argument("--base-height", type=float, default=1.2)
    ap.add_argument("--mode", default="temp", choices=["temp", "flow", "speed"],
                    help="temp: M104 nozzle temp | flow: M221 extrusion %% | "
                         "speed: M220 feedrate %%")
    ap.add_argument("--shape", default="pillars", choices=["pillars", "block"],
                    help="pillars: a gap to judge stringing | block: a solid "
                         "top surface to judge extrusion")
    ap.add_argument("--out", default="calibration/temp_tower.stl")
    ap.add_argument("--gcode-out", default=None)
    a = ap.parse_args()

    seq = temps(a.start, a.end, a.step)
    height = len(seq) * a.band_height
    width = a.pillar * 2 + a.gap
    depth = a.pillar

    # Three overlapping closed boxes; every slicer unions them. The base is
    # made strictly LARGER than the pillar footprints in both X and Y so no
    # edge is shared between solids -- otherwise those coincident edges belong
    # to four faces each and every mesh checker calls the result non-manifold.
    o = 2.0
    tris = []
    tris += box(-o, -o, 0, width + o, depth + o, a.base_height)           # base slab
    if a.shape == "pillars":
        tris += box(0, 0, 0, a.pillar, depth, a.base_height + height)     # pillar A
        tris += box(a.pillar + a.gap, 0, 0, width, depth, a.base_height + height)  # pillar B
    else:
        # One solid block: flow and speed are judged on the top/side surface,
        # not on strings, so a gap would only waste filament.
        tris += box(0, 0, 0, width, depth, a.base_height + height)
    write_stl(a.out, tris)

    # Band i spans [base + i*bh, base + (i+1)*bh). Conditions are evaluated in
    # order, so a simple ascending chain of upper bounds is unambiguous.
    #
    # M104 sets nozzle temperature, M221 the extrusion multiplier and M220 the
    # feedrate multiplier -- all three are plain Marlin and are applied by the
    # firmware at print time, which is what lets one print sweep a value that
    # the slicer bakes in and cannot change.
    cmd = {"temp": "M104 S", "flow": "M221 S", "speed": "M220 S"}[a.mode]
    clauses = []
    for i, t in enumerate(seq):
        top = a.base_height + (i + 1) * a.band_height
        kw = "if" if i == 0 else "elsif"
        clauses.append(f"{{{kw} layer_z < {top:.2f}}}{cmd}{t}")
    gcode = "".join(clauses) + f"{{else}}{cmd}{seq[-1]}{{endif}}\nG92 E0\n"

    print(f"# tower: {width:.0f} x {depth:.0f} x {a.base_height + height:.0f} mm, "
          f"{len(seq)} bands of {a.band_height:.0f} mm", file=sys.stderr)
    unit = {"temp": "C", "flow": "% flow", "speed": "% speed"}[a.mode]
    print(f"# bands bottom->top ({unit}): {' '.join(str(t) for t in seq)}", file=sys.stderr)
    print(f"# wrote {a.out}", file=sys.stderr)
    if a.gcode_out:
        open(a.gcode_out, "w").write(gcode)
        print(f"# wrote {a.gcode_out}", file=sys.stderr)
    sys.stdout.write(gcode)


if __name__ == "__main__":
    main()
