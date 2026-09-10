#!/usr/bin/env python3
"""Inspect STL/3MF meshes: bbox, triangle count, manifold status, build-volume fit.

Dependency-free: parses binary and ASCII STL directly. 3MF is reported as
UNKNOWN (Orca reads it fine, but we don't crack the container here).
"""
import json
import os
import struct
import sys
import zipfile
from collections import defaultdict

# name -> (x, y, z) in mm
PRINTERS = {
    "ender3pro": (220.0, 220.0, 250.0),
    "geniuspro": (220.0, 220.0, 250.0),
    "h2s": (340.0, 320.0, 340.0),
}


def _read_binary_stl(fh):
    fh.seek(80)
    (count,) = struct.unpack("<I", fh.read(4))
    data = fh.read(count * 50)
    if len(data) < count * 50:
        raise ValueError(f"truncated binary STL: want {count} tris, got {len(data)//50}")
    tris = []
    for i in range(count):
        off = i * 50 + 12  # skip the normal
        v = struct.unpack_from("<9f", data, off)
        tris.append((v[0:3], v[3:6], v[6:9]))
    return tris


def _read_ascii_stl(path):
    tris, cur = [], []
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) == 4 and parts[0] == "vertex":
                cur.append(tuple(float(x) for x in parts[1:4]))
                if len(cur) == 3:
                    tris.append(tuple(cur))
                    cur = []
    return tris


def read_stl(path):
    with open(path, "rb") as fh:
        head = fh.read(5)
        fh.seek(0)
        if head[:5].lower() == b"solid":
            # ASCII header is not proof — some binary files start with "solid".
            size = os.path.getsize(path)
            fh.seek(80)
            raw = fh.read(4)
            if len(raw) == 4:
                (count,) = struct.unpack("<I", raw)
                if size == 84 + count * 50:
                    fh.seek(0)
                    return _read_binary_stl(fh), "binary"
            return _read_ascii_stl(path), "ascii"
        return _read_binary_stl(fh), "binary"


def analyse(tris):
    """Return bbox, signed volume, and edge-manifold status."""
    xs = [v[0] for t in tris for v in t]
    ys = [v[1] for t in tris for v in t]
    zs = [v[2] for t in tris for v in t]
    bbox = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))

    # Signed volume via the divergence theorem (tetrahedra to origin), mm^3.
    vol = 0.0
    for a, b, c in tris:
        vol += (
            a[0] * (b[1] * c[2] - b[2] * c[1])
            - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0])
        ) / 6.0

    # Edge-manifold test: quantise vertices so float noise doesn't split a seam,
    # then require every undirected edge to be used by exactly two triangles.
    def key(v):
        return (round(v[0], 5), round(v[1], 5), round(v[2], 5))

    edges = defaultdict(int)
    for a, b, c in tris:
        ka, kb, kc = key(a), key(b), key(c)
        for e in ((ka, kb), (kb, kc), (kc, ka)):
            edges[tuple(sorted(e))] += 1
    bad = sum(1 for n in edges.values() if n != 2)

    return bbox, abs(vol), bad, len(edges)


def fits(bbox, volume, margin=1.0):
    """Does bbox fit in volume, allowing a 90-degree Z rotation?

    Deliberately conservative: only axis-aligned and 90-degree placements are
    considered. A long thin part can still fit diagonally, and the slicer's
    arrange will find that placement — so a "NO" here means "not without
    thought", not "cannot be sliced".
    """
    bx, by, bz = bbox
    vx, vy, vz = volume
    if bz > vz - margin:
        return False
    return (bx <= vx - margin and by <= vy - margin) or (
        by <= vx - margin and bx <= vy - margin
    )


def min_pieces(bbox, volume, margin=1.0):
    """Crude lower bound: how many pieces if we cut along the offending axes."""
    import math

    vx, vy, vz = volume
    bx, by, bz = bbox
    # try both orientations, take the cheaper split
    best = None
    for ax, ay in ((bx, by), (by, bx)):
        n = (
            math.ceil(ax / (vx - margin))
            * math.ceil(ay / (vy - margin))
            * math.ceil(bz / (vz - margin))
        )
        best = n if best is None else min(best, n)
    return best


def inspect(path):
    row = {"file": os.path.basename(path), "path": path}
    ext = os.path.splitext(path)[1].lower()

    if ext == ".3mf":
        row["format"] = "3mf"
        row["status"] = "SKIPPED (3mf container — slice it, Orca reads it natively)"
        try:
            with zipfile.ZipFile(path) as z:
                row["note"] = f"{len(z.namelist())} entries"
        except Exception as exc:
            row["status"] = f"ERROR: {exc}"
        return row

    try:
        tris, fmt = read_stl(path)
    except Exception as exc:
        row["status"] = f"ERROR: {exc}"
        return row

    if not tris:
        row["status"] = "ERROR: no triangles parsed"
        return row

    bbox, vol, bad_edges, n_edges = analyse(tris)
    row.update(
        {
            "format": f"stl/{fmt}",
            "triangles": len(tris),
            "bbox_mm": [round(v, 3) for v in bbox],
            "volume_cm3": round(vol / 1000.0, 3),
            "edges": n_edges,
            "non_manifold_edges": bad_edges,
            "watertight": bad_edges == 0,
        }
    )
    for name, vol_mm in PRINTERS.items():
        ok = fits(bbox, vol_mm)
        row[f"fits_{name}"] = ok
        if not ok:
            row[f"min_pieces_{name}"] = min_pieces(bbox, vol_mm)
    row["status"] = "OK"
    return row


def main(argv):
    paths = []
    for arg in argv:
        if os.path.isdir(arg):
            for root, _, files in os.walk(arg):
                for f in sorted(files):
                    if f.lower().endswith((".stl", ".3mf")):
                        paths.append(os.path.join(root, f))
        elif os.path.isfile(arg):
            paths.append(arg)

    if not paths:
        print("no STL/3MF files found in:", ", ".join(argv), file=sys.stderr)
        return 0

    rows = [inspect(p) for p in paths]

    for r in rows:
        print(f"\n── {r['file']}")
        if r["status"] != "OK":
            print(f"   {r['status']}")
            continue
        bb = r["bbox_mm"]
        print(f"   format      : {r['format']}, {r['triangles']} triangles")
        print(f"   bounding box: {bb[0]} x {bb[1]} x {bb[2]} mm")
        print(f"   volume      : {r['volume_cm3']} cm3")
        print(
            f"   watertight  : {'YES' if r['watertight'] else 'NO'} "
            f"({r['non_manifold_edges']} of {r['edges']} edges not shared by exactly 2 faces)"
        )
        for name, dims in PRINTERS.items():
            d = "x".join(str(int(v)) for v in dims)
            if r[f"fits_{name}"]:
                print(f"   fits {name:<10}: YES  (bed {d})")
            else:
                print(
                    f"   fits {name:<10}: NO   (bed {d}) "
                    f"-> needs at least {r[f'min_pieces_{name}']} pieces"
                )

    out = os.environ.get("INSPECT_JSON")
    if out:
        with open(out, "w") as fh:
            json.dump(rows, fh, indent=2)
        print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
