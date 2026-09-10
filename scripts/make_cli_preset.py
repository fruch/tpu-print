#!/usr/bin/env python3
"""Turn a GUI-authored filament preset into one Bambu Studio's CLI will accept.

Bambu Studio's GUI writes per-extruder-variant arrays padded with the string
"nil" for variants you never touched, and omits the "type" key. Its own CLI
then rejects both:
    operator(): unknown config type ...
    nozzle_temperature: 215,nil,nil not in range [0.000000,1500.000000]
So we emit a CLI-only sibling: "type" added, every "nil" replaced with the
first real value in its array. The GUI preset is never modified.

(OrcaSlicer's CLI handles "nil" fine — this is only needed for Bambu Studio.)
"""
import json
import os
import sys

# Per-filament, not per-variant: these must stay single-element.
SCALAR_KEYS = {"filament_density", "filament_cost", "filament_settings_id"}


def denil(value):
    if not isinstance(value, list):
        return value
    real = [v for v in value if v != "nil"]
    if not real:
        return value
    fill = real[0]
    return [fill if v == "nil" else v for v in value]


def main(argv):
    if len(argv) != 2:
        print("usage: make_cli_preset.py <src.json> <dst.json>", file=sys.stderr)
        return 2
    src, dst = argv
    d = json.load(open(src))

    d.setdefault("type", "filament")
    for k, v in list(d.items()):
        if k in SCALAR_KEYS:
            continue
        d[k] = denil(v)

    # Density drives "filament used [g]". Neither CC3D nor the BBL Generic TPU
    # chain gives a figure we trust, so pin the same one the Orca presets use;
    # otherwise an Orca-vs-Bambu gram comparison measures the density guess.
    d.setdefault("filament_density", ["1.21"])
    d.setdefault("filament_cost", ["25"])

    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    json.dump(d, open(dst, "w"), indent=4, sort_keys=True)
    print(f"CLI preset: {os.path.basename(dst)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
