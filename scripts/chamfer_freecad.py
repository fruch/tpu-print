"""Chamfer the flat cut faces of a scanned solid, in FreeCAD.

Blender's edge bevel cannot do this on a dense triangulated scan: the boundary
is thousands of sub-millimetre edges whose offsets overlap, so the result
either collapses to nothing (clamped) or throws spikes outside the model.

CAD does it properly. Rather than chamfering an edge -- meaningless on a solid
made of 21000 planar facets -- this builds the chamfer as geometry:

  1. section the solid at height d to get the outline there
  2. offset that outline inward by d, and drop it to z = 0
  3. loft between the two -- that loft IS the chamfer surface
  4. keep the solid above d, and glue the loft underneath

    CF_IN=in.stl CF_OUT=out.stl CF_WIDTH=5 \
        FreeCAD --console scripts/chamfer_freecad.py
"""
import sys
import time

# --console keeps an interactive prompt open after the script ends, so the
# process has to exit explicitly or it just sits there until something kills
# it -- which looks exactly like a hang.
sys.stdout.reconfigure(line_buffering=True)

import Mesh
import Part
from FreeCAD import Base

# Arguments come through the environment: FreeCAD treats trailing argv as
# documents to open, so passing paths on the command line makes it try to
# load the output file as a project and run the script twice.
import os
src = os.environ["CF_IN"]
dst = os.environ["CF_OUT"]
d = float(os.environ.get("CF_WIDTH", "5"))

t0 = time.time()
mesh = Mesh.Mesh(src)
shape = Part.Shape()
shape.makeShapeFromMesh(mesh.Topology, 0.05)
solid = Part.makeSolid(shape)
print(f"CF solid: {len(solid.Faces)} faces, {solid.Volume/1000:.1f} cm3, "
      f"valid={solid.isValid()}, {time.time()-t0:.0f}s")

zmin = solid.BoundBox.ZMin
zcut = zmin + d

# 1. the outline at height d
wires = solid.slice(Base.Vector(0, 0, 1), zcut)
wires = sorted(wires, key=lambda w: -w.Length)
if not wires:
    raise SystemExit("CF ERROR no section at the cut height")
outer = wires[0]
print(f"CF section at z={zcut:.1f}: {len(wires)} wire(s), outer length {outer.Length:.0f} mm")

# 2. same outline pulled inward by d, sitting on the bed
# join=0 (arcs). join=2 (intersection) returns a null shape on this outline:
# an inward offset at the cleft's tight concave curvature self-intersects and
# the intersection join cannot resolve it, while arcs can.
inner = outer.makeOffset2D(-d, join=0, openResult=False, intersection=False)
inner.translate(Base.Vector(0, 0, -d))
print(f"CF inward offset ok, length {inner.Length:.0f} mm")

# 3. the chamfer band
loft = Part.makeLoft([inner, outer], True, True)
print(f"CF loft volume {loft.Volume/1000:.2f} cm3")

# 4. body above the cut, plus the band
box = Part.makeBox(1e4, 1e4, 1e4, Base.Vector(-5e3, -5e3, zcut))
upper = solid.common(box)
result = upper.fuse(loft).removeSplitter()
print(f"CF result {result.Volume/1000:.1f} cm3 valid={result.isValid()}")

Part.show(result)
mesh_out = Mesh.Mesh()
mesh_out.addFacets(result.tessellate(0.05))
mesh_out.write(dst)
print(f"CF_OK {mesh_out.CountFacets} facets -> {dst}  ({time.time()-t0:.0f}s total)")

sys.exit(0)
