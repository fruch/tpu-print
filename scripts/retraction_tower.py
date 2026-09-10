#!/usr/bin/env python3
"""Turn a single sliced G-code into a retraction tower.

Retraction length is written into every travel move when the file is sliced,
and no firmware command changes it mid-print the way M104/M221/M220 change
temperature, flow and speed. So instead of slicing once per value, slice ONCE
and rewrite the retraction moves here, band by band.

Requirements on the input (calibrate.sh arranges all of them):
  * relative extrusion (M83) -- so each retraction is a self-contained delta
  * wipe DISABLED -- with wipe on, a retraction is smeared across several
    "G1 X.. Y.. E-.03" moves and cannot be rescaled as one number
  * a known, uniform slice-time retraction length (--base)

Each retraction is paired with the deretraction that follows it and both are
scaled by the same factor, so the extruder stays exactly in balance no matter
where a band boundary falls.
"""
import argparse
import re
import sys

RETRACT = re.compile(r"^G1 E-([0-9.]+)(\s+F[0-9.]+)?\s*$")
DERETRACT = re.compile(r"^G1 E([0-9.]+)(\s+F[0-9.]+)?\s*$")
ZMOVE = re.compile(r"^G[01](?=.*\bZ([0-9.]+))")


def fmt(v):
    return f"{v:.5f}".rstrip("0").rstrip(".")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--base", type=float, required=True,
                    help="retraction length the file was sliced with")
    ap.add_argument("--values", required=True,
                    help='space separated, bottom band first, e.g. "1.5 2.0 2.5 3.0"')
    ap.add_argument("--band-height", type=float, required=True)
    ap.add_argument("--base-height", type=float, default=1.2,
                    help="height of the base slab below band 0")
    a = ap.parse_args()

    values = [float(v) for v in a.values.split()]
    out, z = [], 0.0
    pending = None          # scale to reuse for the matching deretraction
    band_now = None
    counts = {v: 0 for v in values}
    net = 0.0

    for line in open(a.src, errors="replace"):
        stripped = line.rstrip("\n")

        m = re.search(r"^G[01]\b.*\bZ([0-9.]+)", stripped)
        if m:
            z = float(m.group(1))

        band = int(max(0.0, z - a.base_height) // a.band_height)
        band = min(band, len(values) - 1)

        r = RETRACT.match(stripped)
        if r:
            if band != band_now:
                band_now = band
                out.append(f"; === retraction band {band + 1}: {values[band]} mm "
                           f"(Z >= {a.base_height + band * a.band_height:.2f}) ===\n")
            scale = values[band] / a.base
            pending = scale
            counts[values[band]] += 1
            newv = float(r.group(1)) * scale
            net -= newv
            out.append(f"G1 E-{fmt(newv)}{r.group(2) or ''}\n")
            continue

        d = DERETRACT.match(stripped)
        if d and pending is not None:
            newv = float(d.group(1)) * pending
            net += newv
            out.append(f"G1 E{fmt(newv)}{d.group(2) or ''}\n")
            pending = None
            continue

        out.append(line)

    open(a.dst, "w").writelines(out)

    total = sum(counts.values())
    print(f"# rewrote {total} retractions across {len(values)} bands", file=sys.stderr)
    for v in values:
        print(f"#   {v} mm : {counts[v]}", file=sys.stderr)
    # A tiny residual is just the final unmatched retraction at end of print.
    print(f"# net extruder drift from rescaling: {net:+.5f} mm", file=sys.stderr)
    if abs(net) > max(values) + 1e-6:
        print("# WARNING: unexpected extruder imbalance", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
