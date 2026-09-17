#!/usr/bin/env python3
"""Write the calibrated profile back into a 3mf's project settings.

Saving a project from Orca's GUI applies whichever presets are currently
selected in the GUI, silently replacing whatever the project was exported
with. Rotating a model and hitting save is enough to lose every calibrated
value -- nozzle temperature, flow ratio, retraction, support, and the
`G92 E0` the Ender needs in layer_change_gcode -- while the support painting
and the rotation survive.

This puts the settings back without touching the mesh, the painting, or the
build transform (hand-editing that transform makes Orca segfault or reject
the plate).

    python3 scripts/apply_profile_to_3mf.py a.3mf b.3mf
"""
import json
import re
import shutil
import sys
import zipfile

# Everything measured on the Ender 3 Pro with CC3D TPU 98A, plus the
# soft-part profile and the painted-support setup.
SETTINGS = {
    "nozzle_temperature":               ["205"],
    "nozzle_temperature_initial_layer": ["205"],
    "filament_flow_ratio":              ["1.1"],
    "filament_retraction_length":       ["4"],
    "filament_max_volumetric_speed":    ["5.5"],
    "filament_z_hop":                   ["0.3"],
    "filament_wipe":                    ["0"],
    "hot_plate_temp":                   ["50"],
    "hot_plate_temp_initial_layer":     ["50"],

    "wall_loops":                    "2",
    "sparse_infill_density":         "4%",
    "sparse_infill_pattern":         "gyroid",
    "gyroid_optimized":              "1",
    "top_shell_layers":              "3",
    "bottom_shell_layers":           "3",
    "travel_speed":                  "150",
    "extra_perimeters_on_overhangs": "1",

    "enable_support":                  "1",
    "support_type":                    "tree(manual)",
    "support_style":                   "tree_slim",
    "support_top_z_distance":          "0.3",
    "support_object_xy_distance":      "0.6",
    "independent_support_layer_height": "0",

    # The Creality preset chain never sets use_relative_e_distances, so Orca
    # falls back to relative E; without this it refuses to slice.
    "layer_change_gcode": "G92 E0\n",
}


def patch(path):
    z = zipfile.ZipFile(path)
    name = "Metadata/project_settings.config"
    cfg = json.loads(z.read(name).decode("utf-8"))
    changed = []
    for k, v in SETTINGS.items():
        old = cfg.get(k)
        if old != v:
            changed.append((k, old, v))
        cfg[k] = v
    blob = json.dumps(cfg, indent=4, ensure_ascii=False).encode("utf-8")

    tmp = path + ".tmp"
    with zipfile.ZipFile(path) as zs, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for it in zs.infolist():
            zo.writestr(it, blob if it.filename == name else zs.read(it.filename))
    shutil.move(tmp, path)

    painted = 0
    with zipfile.ZipFile(path) as zz:
        for n in zz.namelist():
            if n.endswith(".model") and "Objects" in n:
                painted += len(re.findall(r"paint_supports=", zz.read(n).decode("utf-8", "replace")))
    print(f"  {path}: restored {len(changed)} settings, {painted} painted triangles intact")
    for k, o, v in changed:
        print(f"      {k:<34} {str(o)[:18]:<20} -> {v}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        patch(p)
