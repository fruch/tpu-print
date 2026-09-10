#!/usr/bin/env python3
"""Cut a sliced G-code down to its first N mm: a pre-flight for a long print.

Before committing 11 hours, print the bottom of the ACTUAL part at the ACTUAL
settings. Calibration towers validate the filament; they say nothing about
whether this specific geometry adheres over a 200 mm footprint or whether a
1-wall / 5% gyroid profile holds together. This does.

The bottom is also where a long print fails: first-layer adhesion, the brim,
the first few soft layers. If 30 minutes of this look right, the remaining
hours are mostly repetition.

Keeps the original start G-code and end G-code, so the printer heats up,
prints, then retracts, lifts, cools and parks exactly as it normally would.
"""
import argparse
import os
import re
import sys


def find_end_block(lines):
    """Everything after the last real extrusion move is the end G-code."""
    stop = len(lines)
    for i, l in enumerate(lines):
        if l.startswith("; EXECUTABLE_BLOCK_END"):
            stop = i + 1
            break
    last_move = 0
    for i in range(stop - 1, -1, -1):
        l = lines[i]
        if l.startswith(("G1 ", "G0 ")) and re.search(r"\b[XY]-?[0-9.]", l) \
           and re.search(r"\bE-?[0-9.]", l):
            last_move = i
            break
    return last_move + 1, stop


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--height", type=float, default=None,
                    help="mm of the part to keep")
    ap.add_argument("--minutes", type=float, default=None,
                    help="cut at roughly this many minutes of printing instead "
                         "(uses Orca's M73 remaining-time marks)")
    ap.add_argument("--layers", type=int, default=25,
                    help="how many layers to keep (default; --height and "
                         "--minutes override it)")
    a = ap.parse_args()

    lines = open(a.src, errors="replace").read().splitlines(keepends=True)
    end_start, end_stop = find_end_block(lines)

    # Build a table of layers up front: (line index, Z, minutes elapsed).
    # Two dialects, and they agree on nothing:
    #   Orca / Marlin : ";LAYER_CHANGE"  then ";Z:0.8"
    #   Orca / BBL    : "; CHANGE_LAYER" then "; Z_HEIGHT: 0.8"
    # "M73 P<pct> R<minutes left>" gives elapsed time; M73 P0 can sit hundreds
    # of lines in on BBL output, so find it wherever it is.
    total_r = None
    for l in lines[:end_start]:
        m = re.match(r"^M73 P0 R(\d+)", l)
        if m:
            total_r = int(m.group(1))
            break

    layers, pending_idx, last_r = [], None, total_r
    for i, l in enumerate(lines[:end_start]):
        if l.startswith(";LAYER_CHANGE") or l.startswith("; CHANGE_LAYER"):
            pending_idx = i
            continue
        m = re.match(r"^;\s*(?:Z|Z_HEIGHT)\s*:\s*([0-9.]+)", l)
        if m and pending_idx is not None:
            elapsed = (total_r - last_r) if (total_r is not None and last_r is not None) else None
            layers.append((pending_idx, float(m.group(1)), elapsed))
            pending_idx = None
            continue
        m = re.match(r"^M73 P\d+ R(\d+)", l)
        if m:
            last_r = int(m.group(1))

    if not layers:
        print("! no layers found -- is this a sliced g-code?", file=sys.stderr)
        return 2

    # Pick the cut: whichever criterion was given, layers is the default.
    pick = None
    if a.height is not None:
        pick = next((k for k, (_, z, _) in enumerate(layers) if z > a.height), None)
    elif a.minutes is not None:
        pick = next((k for k, (_, _, e) in enumerate(layers)
                     if e is not None and e >= a.minutes), None)
    else:
        pick = a.layers if a.layers < len(layers) else None

    if pick is None or pick == 0:
        target = (f"{a.height} mm" if a.height is not None else
                  f"{a.minutes} min" if a.minutes is not None else f"{a.layers} layers")
        print(f"! {os.path.basename(a.src)} is already shorter than {target}",
              file=sys.stderr)
        return 2

    cut, z_at_cut, _ = layers[pick]
    elapsed = layers[pick - 1][2]

    out = lines[:cut]
    out.append("\n; ---- pre-flight truncation ----\n")
    want = (f"{a.height} mm" if a.height is not None else
            f"~{a.minutes:.0f} min" if a.minutes is not None else f"{a.layers} layers")
    out.append(f"; cut at Z={z_at_cut:.2f} mm (requested {want})\n")
    out.append("; the header's time/filament figures describe the FULL print\n")
    out.append("G1 E-2 F1500 ; retract before parking\n")
    out.append("M107 ; fan off\n")
    out.extend(lines[end_start:end_stop])

    open(a.dst, "w").writelines(out)
    kept = pick   # from the layer table, so both dialects count correctly
    msg = f"# kept {kept} layers up to Z={z_at_cut:.2f} mm"
    if elapsed:
        msg += f", about {elapsed // 60}h {elapsed % 60}m" if elapsed >= 60 else f", about {elapsed}m"
    print(msg, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
