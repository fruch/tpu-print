"""Chamfer the flat cut faces of a scanned solid, in FreeCAD.

Blender's edge bevel cannot do this on a dense triangulated scan: the boundary
is thousands of sub-millimetre edges whose offsets overlap, so the result
either collapses to nothing (clamped) or throws spikes outside the model.

CAD does it properly. Chamfering an "edge" is meaningless on a solid made of
21000 planar facets, so instead of chamfering, this builds the chamfer:

  1. section the solid a distance d in front of the cut plane
  2. offset that outline inward by d, and slide it back onto the plane
  3. loft between the two -- that loft IS the chamfer surface
  4. keep the solid behind the section, and glue the loft on

Works on any orientation: the solid is rotated so the target plane faces
straight down, the horizontal case above is run, and it is rotated back.
Large flat faces are found automatically by grouping facets on (normal,
offset), so it does not matter how the model was cut.

    CF_IN=in.stl CF_OUT=out.stl CF_WIDTH=5 [CF_MIN_AREA=20] [CF_PLANES=2] \
        FreeCAD --console scripts/chamfer_freecad.py
"""
import os
import sys
import time
from collections import defaultdict

# --console keeps an interactive prompt open after the script ends, so the
# process has to exit explicitly or it just sits there until something kills
# it -- which looks exactly like a hang.
sys.stdout.reconfigure(line_buffering=True)

import Mesh
import Part
from FreeCAD import Base

src = os.environ["CF_IN"]
dst = os.environ["CF_OUT"]
d = float(os.environ.get("CF_WIDTH", "5"))
min_area = float(os.environ.get("CF_MIN_AREA", "20"))     # cm^2
max_planes = int(os.environ.get("CF_PLANES", "2"))

DOWN = Base.Vector(0, 0, -1)


def load(path):
    mesh = Mesh.Mesh(path)
    shape = Part.Shape()
    shape.makeShapeFromMesh(mesh.Topology, 0.05)
    return Part.makeSolid(shape)


def find_planes(solid):
    """Large flat regions, as (normal, area) sorted by area."""
    groups = defaultdict(float)
    for f in solid.Faces:
        try:
            n = f.normalAt(0, 0)
        except Exception:
            continue
        if n.Length < 1e-9:
            continue
        n.normalize()
        key = (round(n.x, 1), round(n.y, 1), round(n.z, 1),
               round(n.dot(f.CenterOfMass), 0))
        groups[key] += f.Area
    out = [(Base.Vector(k[0], k[1], k[2]), a / 100.0)
           for k, a in sorted(groups.items(), key=lambda kv: -kv[1])]
    return [(n, a) for n, a in out if a >= min_area]


def chamfer_bottom(solid, d):
    """Chamfer the large face pointing straight down.

    Locate the plane by finding it, not by assuming it sits at the bounding
    box minimum: once an arbitrary plane has been rotated to face downward,
    some other part of the model usually hangs lower, and sectioning at
    ZMin+d then cuts through the middle of the part.
    """
    best_z, best_area = None, 0.0
    for f in solid.Faces:
        try:
            n = f.normalAt(0, 0)
        except Exception:
            continue
        if n.Length < 1e-9:
            continue
        n.normalize()
        if n.z < -0.98 and f.Area > best_area:
            best_area, best_z = f.Area, f.CenterOfMass.z
    if best_z is None:
        raise RuntimeError("no downward-facing plane after rotation")
    zcut = best_z + d

    wires = sorted(solid.slice(Base.Vector(0, 0, 1), zcut), key=lambda w: -w.Length)
    if not wires:
        raise RuntimeError("no section at the cut height")
    outer = wires[0]

    # join=0 (arcs). join=2 (intersection) returns a null shape wherever the
    # outline has tight concave curvature -- a cleft, a crease -- because the
    # inward offset self-intersects there and intersection joins cannot
    # resolve it, while arcs can.
    inner = outer.makeOffset2D(-d, join=0, openResult=False, intersection=False)
    inner.translate(Base.Vector(0, 0, -d))

    loft = Part.makeLoft([inner, outer], True, True)
    box = Part.makeBox(1e4, 1e4, 1e4, Base.Vector(-5e3, -5e3, zcut))
    before = solid.Volume
    out = solid.common(box).fuse(loft).removeSplitter()
    # report what was actually cut away, not the loft's own volume -- most of
    # the loft overlaps material that was already there
    return out, (before - out.Volume) / 1000.0


def chamfer_plane(solid, normal, d):
    """Rotate the plane to face down, chamfer, rotate back."""
    normal = Base.Vector(normal).normalize()
    rot = Base.Rotation(normal, DOWN)          # maps this normal onto -Z
    centre = solid.BoundBox.Center

    work = solid.copy()
    work.rotate(centre, rot.Axis, rot.Angle * 180 / 3.141592653589793)
    work, vol = chamfer_bottom(work, d)
    work.rotate(centre, rot.Axis, -rot.Angle * 180 / 3.141592653589793)
    return work, vol


t0 = time.time()
solid = load(src)
print(f"CF solid: {len(solid.Faces)} faces, {solid.Volume/1000:.1f} cm3, "
      f"valid={solid.isValid()}, {time.time()-t0:.0f}s")

planes = find_planes(solid)[:max_planes]
print(f"CF planes: {len(planes)}")
for n, a in planes:
    print(f"CF   area {a:7.1f} cm2  normal ({n.x:+.2f},{n.y:+.2f},{n.z:+.2f})")

for i, (n, a) in enumerate(planes, 1):
    try:
        solid, vol = chamfer_plane(solid, n, d)
        print(f"CF chamfered plane {i} ({a:.0f} cm2): cut {vol:.2f} cm3, "
              f"valid={solid.isValid()}")
    except Exception as exc:
        print(f"CF plane {i} FAILED: {exc}")

print(f"CF result {solid.Volume/1000:.1f} cm3 valid={solid.isValid()}")
out = Mesh.Mesh()
out.addFacets(solid.tessellate(0.05))
out.write(dst)
print(f"CF_OK {out.CountFacets} facets -> {dst}  ({time.time()-t0:.0f}s total)")

sys.exit(0)
