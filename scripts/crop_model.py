"""Boolean-crop an STL to a box, using Blender in background mode.

A 12-hour print is a hopeless iteration loop. This cuts a small test piece out
of the real model -- real geometry, real overhangs, real settings -- so a
support or overhang experiment costs an hour instead of a day.

Boolean rather than triangle-clipping because the result has to be watertight:
an open mesh slices into open contours and the test would be meaningless.

    blender --background --python scripts/crop_model.py -- \
        in.stl out.stl  XMIN XMAX  YMIN YMAX  ZMIN ZMAX
"""
import sys
import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]
x0, x1, y0, y1, z0, z1 = (float(v) for v in argv[2:8])

bpy.ops.wm.read_factory_settings(use_empty=True)

# Blender 4.x+ renamed the STL operators; try the new names first.
try:
    bpy.ops.wm.stl_import(filepath=src)
except AttributeError:
    bpy.ops.import_mesh.stl(filepath=src)
obj = bpy.context.selected_objects[0]
bpy.context.view_layer.objects.active = obj

bpy.ops.mesh.primitive_cube_add(size=1)
box = bpy.context.active_object
box.scale = (x1 - x0, y1 - y0, z1 - z0)
box.location = ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)

m = obj.modifiers.new("crop", "BOOLEAN")
m.operation = "INTERSECT"
m.object = box
m.solver = "EXACT"
bpy.context.view_layer.objects.active = obj
bpy.ops.object.modifier_apply(modifier="crop")

bpy.data.objects.remove(box, do_unlink=True)

bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
try:
    bpy.ops.wm.stl_export(filepath=dst, export_selected_objects=True)
except AttributeError:
    bpy.ops.export_mesh.stl(filepath=dst, use_selection=True)

print(f"CROP_OK {len(obj.data.polygons)} faces -> {dst}")
