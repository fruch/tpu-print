"""Bevel the flat cut faces of a model, using Blender in background mode.

A scanned body form has two machine-made planes on it -- the flat bottom it
stands on and the plane it was cut from -- and their sharp edges look and feel
wrong on a soft part. This finds the large planar regions automatically,
takes the boundary loop around each, and bevels it.

Planes are found by grouping faces on (normal, plane offset), so it does not
matter which way the model is oriented or how it was cut.

    blender --background --python scripts/bevel_model.py -- \
        in.stl out.stl WIDTH SEGMENTS [MIN_AREA_CM2]
"""
import sys
from collections import defaultdict

import bmesh
import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]
width = float(argv[2]) if len(argv) > 2 else 5.0
segments = int(argv[3]) if len(argv) > 3 else 4
min_area = float(argv[4]) if len(argv) > 4 else 20.0      # cm^2
# clamp_overlap limits the bevel to what neighbouring geometry allows. On a
# dense triangulated scan the boundary edges are tiny, so clamping collapses
# the bevel to nothing -- the mesh gains faces and loses no material at all.
CLAMP = bool(int(argv[5])) if len(argv) > 5 else False

bpy.ops.wm.read_factory_settings(use_empty=True)
try:
    bpy.ops.wm.stl_import(filepath=src)
except AttributeError:
    bpy.ops.import_mesh.stl(filepath=src)
obj = bpy.context.selected_objects[0]
bpy.context.view_layer.objects.active = obj

bm = bmesh.new()
bm.from_mesh(obj.data)
bm.faces.ensure_lookup_table()

# Group coplanar faces: same normal (to 0.05) and same distance from origin
# along it (to 0.5mm). Big groups are the cut planes.
groups = defaultdict(list)
for f in bm.faces:
    n = f.normal
    if n.length < 1e-9:
        continue
    key = (round(n.x, 1), round(n.y, 1), round(n.z, 1),
           round(n.dot(f.calc_center_median()), 0))
    groups[key].append(f)

planes = sorted(groups.items(), key=lambda kv: -sum(f.calc_area() for f in kv[1]))
chosen = [(k, fs) for k, fs in planes if sum(f.calc_area() for f in fs) / 100.0 >= min_area]

print(f"BEVEL_PLANES {len(chosen)}")

# Merge each flat region into ONE n-gon before beveling. On a triangulated
# scan the plane is hundreds of little triangles, so its boundary is hundreds
# of short edges; beveling those makes the offsets overlap each other at every
# corner and throws spikes outside the model. Dissolved to a single face, the
# boundary is one clean loop and the bevel behaves.
for key, faces in chosen:
    area = sum(f.calc_area() for f in faces) / 100.0
    print(f"BEVEL_PLANE area={area:.1f}cm2 normal=({key[0]},{key[1]},{key[2]}) faces={len(faces)}")
    bmesh.ops.dissolve_faces(bm, faces=[f for f in faces if f.is_valid], use_verts=False)

bm.faces.ensure_lookup_table()

# Re-find the dissolved planes: they are now the few faces with a huge area.
big = sorted(bm.faces, key=lambda f: -f.calc_area())[:len(chosen)]
edges = set()
for f in big:
    print(f"BEVEL_LOOP area={f.calc_area()/100:.1f}cm2 edges={len(f.edges)}")
    edges.update(f.edges)

if edges:
    bmesh.ops.bevel(bm, geom=list(edges), offset=width, segments=segments,
                    affect="EDGES", offset_type="OFFSET", profile=0.5,
                    clamp_overlap=CLAMP, loop_slide=True)

# STL needs triangles. BEAUTY, not the default ear-clip: a dissolved plane is
# one n-gon with hundreds of edges, and ear-clipping fans it into long thin
# slivers across the whole face, which is what makes the result look wrecked
# even though it is geometrically fine.
bmesh.ops.triangulate(bm, faces=bm.faces[:],
                      quad_method="BEAUTY", ngon_method="BEAUTY")

bm.to_mesh(obj.data)
bm.free()

bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
try:
    bpy.ops.wm.stl_export(filepath=dst, export_selected_objects=True)
except AttributeError:
    bpy.ops.export_mesh.stl(filepath=dst, use_selection=True)
print(f"BEVEL_OK {len(obj.data.polygons)} faces -> {dst}")
