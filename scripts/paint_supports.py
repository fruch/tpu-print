#!/usr/bin/env python3
"""Paint support enforcers onto a 3mf, the way the brush in Orca's GUI does.

Orca stores painted supports as a `paint_supports` attribute on each triangle
in the object's .model XML; "4" means the whole triangle is an enforcer.
(Longer strings encode partially-painted triangles, which is what a brush
stroke crossing a triangle produces. We only ever paint whole triangles.)

So the overhang detection that found the regions can also mark them, instead
of asking someone to find the same faces by hand with a mouse.

    python3 scripts/paint_supports.py part.3mf --angle 45 --min-z 1

The project must already be set to a MANUAL support type (`tree(manual)` or
`normal(manual)`), otherwise Orca adds automatic supports as well and the
painting makes no difference.
"""
import argparse
import math
import re
import shutil
import zipfile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out", default=None, help="default: overwrite src")
    ap.add_argument("--angle", type=float, default=45.0,
                    help="paint faces steeper than this many degrees of overhang")
    ap.add_argument("--min-z", type=float, default=1.0,
                    help="ignore faces this close to the BOTTOM of the model "
                         "(the bed-contact face). Measured from the mesh's own "
                         "lowest point, because a 3mf object is stored centred "
                         "on its origin, not sitting on z=0 like an STL.")
    ap.add_argument("--max-z", type=float, default=None)
    ap.add_argument("--x-band", type=float, default=None,
                    help="only paint within this many mm either side of the "
                         "model's X centre -- for a narrow feature like a "
                         "cleft, a thin strip of support beats a broad patch")
    ap.add_argument("--y-band", type=float, default=None,
                    help="same, about the Y centre")
    ap.add_argument("--grow", type=int, default=1,
                    help="also paint N rings of neighbouring faces, so the "
                         "support has a margin to anchor to")
    a = ap.parse_args()
    dst = a.out or a.src

    zin = zipfile.ZipFile(a.src)
    names = zin.namelist()
    target = next(n for n in names if n.endswith(".model") and "Objects" in n)
    doc = zin.read(target).decode("utf-8")

    verts = [(float(x), float(y), float(z)) for x, y, z in
             re.findall(r'<vertex x="([^"]+)" y="([^"]+)" z="([^"]+)"', doc)]
    tri_tags = re.findall(r"<triangle [^>]*?/>", doc)
    tris = [tuple(int(i) for i in re.findall(r'v[123]="(\d+)"', t)) for t in tri_tags]

    # 3mf objects are stored centred on their origin, so "height above the bed"
    # is relative to the mesh's own minimum, not to absolute z.
    z_bottom = min(v[2] for v in verts)
    xc = (min(v[0] for v in verts) + max(v[0] for v in verts)) / 2
    yc = (min(v[1] for v in verts) + max(v[1] for v in verts)) / 2
    lo = z_bottom + a.min_z
    hi = z_bottom + a.max_z if a.max_z is not None else None
    # Overhang angle is measured from VERTICAL: 0 deg is a vertical wall,
    # 90 deg a flat ceiling. A face at angle t has nz = -sin(t), so the
    # threshold is sin, not cos -- with cos, raising --angle painted MORE
    # faces instead of fewer.
    nz_lim = math.sin(math.radians(a.angle))
    paint = set()
    for i, (i1, i2, i3) in enumerate(tris):
        p, q, r = verts[i1], verts[i2], verts[i3]
        ux, uy, uz = q[0]-p[0], q[1]-p[1], q[2]-p[2]
        vx, vy, vz = r[0]-p[0], r[1]-p[1], r[2]-p[2]
        nx, ny, nz = uy*vz-uz*vy, uz*vx-ux*vz, ux*vy-uy*vx
        L = math.sqrt(nx*nx+ny*ny+nz*nz)
        if not L:
            continue
        nz /= L
        zc = (p[2]+q[2]+r[2])/3
        if zc < lo or (hi is not None and zc > hi):
            continue
        if a.x_band is not None and abs((p[0]+q[0]+r[0])/3 - xc) > a.x_band:
            continue
        if a.y_band is not None and abs((p[1]+q[1]+r[1])/3 - yc) > a.y_band:
            continue
        if nz < -nz_lim:                  # downward facing, steeper than the limit
            paint.add(i)

    core = len(paint)
    if a.grow:
        by_vert = {}
        for i, t in enumerate(tris):
            for v in t:
                by_vert.setdefault(v, []).append(i)
        for _ in range(a.grow):
            ring = set()
            for i in paint:
                for v in tris[i]:
                    ring.update(by_vert[v])
            paint |= ring

    # Rewrite the triangle tags in document order.
    it = iter(range(len(tri_tags)))
    def sub(m):
        i = next(it)
        if i in paint and "paint_supports" not in m.group(0):
            return m.group(0)[:-2].rstrip() + ' paint_supports="4"/>'
        return m.group(0)
    doc = re.sub(r"<triangle [^>]*?/>", sub, doc)

    if dst != a.src:
        shutil.copyfile(a.src, dst)
    tmp = dst + ".tmp"
    with zipfile.ZipFile(a.src) as zsrc, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zsrc.infolist():
            data = doc.encode("utf-8") if item.filename == target else zsrc.read(item.filename)
            zout.writestr(item, data)
    shutil.move(tmp, dst)

    print(f"# model bottom at z={z_bottom:.1f} in object space; "
          f"painting {a.min_z:.0f}mm above it upward")
    print(f"# painted {len(paint)} of {len(tris)} triangles "
          f"({core} overhang faces + {len(paint)-core} grown margin)")
    print(f"# wrote {dst}")


if __name__ == "__main__":
    main()
