#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["trimesh", "numpy", "scipy", "scikit-image", "manifold3d"]
# ///
"""Turn bottom_clean.stl into a thin strap-on back plate for toddler wiping
practice: a THICK mm shell under the curved skin only (both flat cuts dropped),
trimmed by a plane parallel to the body cut BACK_DEPTH mm behind it, with
5 webbing slots near the rim.

BACK_DEPTH defaults to 20 mm because the cleft floor is only ~41 mm behind the
body cut; cutting deeper eats into the cleft, which is the wiping area.

Each slot is a round-ended stadium, padded to THICK + PAD on the inside, and
leaves a bar between itself and the rim; the webbing goes through
the slot, around the bar, and is sewn back on itself (parachute-harness style).

The STL is written print-ready: flat rim on the bed, back (wiping) surface up.
Only the near-flat inside of each cheek needs support (support-threshold-angle 15).

Usage:
  uv run scripts/make_strap_shell.py [in.stl] [out.stl]
  THICK=4 WEBBING=38 BACK_DEPTH=15 uv run scripts/make_strap_shell.py
"""
import os
import sys

import manifold3d as m3d
import numpy as np
import trimesh
from scipy.ndimage import binary_fill_holes, distance_transform_edt
from scipy.spatial import cKDTree
from skimage.measure import marching_cubes

SRC = sys.argv[1] if len(sys.argv) > 1 else "model/bottom_clean.stl"
DST = sys.argv[2] if len(sys.argv) > 2 else "model/bottom_strap_shell.stl"
THICK = float(os.environ.get("THICK", 5))        # shell depth under the skin, mm
WEBBING = float(os.environ.get("WEBBING", 25))   # webbing width, mm (1" harness tape)
SLOT_W = float(os.environ.get("SLOT_W", 5))      # slot width, mm (webbing thickness + slack)
BAR = float(os.environ.get("BAR", 8))            # material left between slot and rim, mm
PITCH = float(os.environ.get("PITCH", 0.5))      # voxel size, mm
BACK_DEPTH = float(os.environ.get("BACK_DEPTH", 20))  # trim plane, mm behind the body cut
PAD = float(os.environ.get("PAD", 4))            # extra thickness around each slot, mm
FALL = float(os.environ.get("FALL", 10))         # distance the pad blends back over, mm

mesh = trimesh.load(SRC)

# The flat cuts (body cut, seat) are the big planar facets; everything else is skin.
big = [i for i in np.argsort(mesh.facets_area)[::-1] if mesh.facets_area[i] >= 1000]
flat = np.zeros(len(mesh.faces), bool)
for i in big:
    flat[mesh.facets[i]] = True
skin = mesh.submesh([np.where(~flat)[0]], append=True)
b = -mesh.facets_normal[big[0]]                 # away from the body, towards the back
seat = next(i for i in big if abs(mesh.facets_normal[i] @ b) < 0.9)
seat_n = mesh.facets_normal[seat]               # outward normal of the flat seat
seat_d = mesh.vertices[mesh.faces[mesh.facets[seat][0]][0]] @ seat_n
up = np.cross(b, [1.0, 0, 0])                   # along the body cut, towards the waist
up *= np.sign(up[2]) or 1
depth = mesh.vertices @ b
d0 = depth.min()

# Voxelise: distance inside the part, and distance to the skin only.
pts, _ = trimesh.sample.sample_surface(mesh, int(mesh.area / 0.02), seed=1)
skin_pts, _ = trimesh.sample.sample_surface(skin, int(skin.area / 0.02), seed=2)
lo = mesh.bounds[0] - 2
shape = tuple(np.ceil((mesh.bounds[1] + 2 - lo) / PITCH).astype(int) + 1)
cut = d0 + BACK_DEPTH

# Two rims: where the trim plane crosses the skin (waist), and the edge of the
# seat opening (gluteal fold, where harness leg straps run).
waist_rim = skin_pts[np.abs(skin_pts @ b - cut) < 0.3]
fold_rim = skin_pts[(np.abs(skin_pts @ seat_n - seat_d) < 0.3) & (skin_pts @ b > cut + 2 * BAR)]
cx = (mesh.bounds[0][0] + mesh.bounds[1][0]) / 2
w = mesh.extents[0]


def pick(rim, x0, x1, key):
    """Rim point with x in [x0, x1] (fractions of width from centre) maximising key."""
    cand = rim[(rim[:, 0] >= cx + x0 * w) & (rim[:, 0] <= cx + x1 * w)]
    return cand[np.argmax(cand @ key)]


# ponytail: anchors are hand-placed bands (fractions of width from centre); move them here if the fit is off.
anchors = {
    "waist_left": (pick(waist_rim, -0.32, -0.28, up), b),     # top of the left cheek
    "waist_center": (pick(waist_rim, -0.02, 0.02, up), b),    # top of the cleft, far from the wiping area
    "waist_right": (pick(waist_rim, 0.28, 0.32, up), b),
    "leg_left": (pick(fold_rim, -0.32, -0.28, b), -seat_n),   # rearmost point of the fold
    "leg_right": (pick(fold_rim, 0.28, 0.32, b), -seat_n),
}

# Slot frames: `along` the rim, `inward` along the skin away from the rim, `n` out of the skin.
tree = cKDTree(skin_pts)
slots = {}
for name, (p, away) in anchors.items():
    # Local skin normal from nearby skin samples (PCA), pointing outward.
    # Wide patch at the cleft so both walls average out to a symmetric normal.
    _, nb = tree.query(p, k=4000 if name == "waist_center" else 200)
    q = skin_pts[nb] - skin_pts[nb].mean(0)
    n = np.linalg.svd(q)[2][2]
    if np.dot(n, p - mesh.centroid) < 0:
        n = -n
    inward = away - np.dot(away, n) * n
    inward /= np.linalg.norm(inward)
    slots[name] = (p + inward * (BAR + SLOT_W / 2), np.cross(n, inward), inward, n)

# Shell thickness: THICK everywhere, THICK + PAD around each slot (on the inside,
# so the wiping surface stays smooth), blending back over FALL mm.
half_len = (WEBBING + 2) / 2
reach = SLOT_W / 2 + BAR + 2                   # full pad out to (and past) the rim
thick = np.full(shape, THICK, np.float32)
for c, along, inward, n in slots.values():
    r = half_len + reach + FALL + THICK + PAD
    i0 = np.maximum(np.floor((c - r - lo) / PITCH).astype(int), 0)
    i1 = np.minimum(np.ceil((c + r - lo) / PITCH).astype(int) + 1, shape)
    g = np.stack(np.meshgrid(*[lo[k] + PITCH * np.arange(i0[k], i1[k]) for k in range(3)],
                             indexing="ij"), -1) - c
    dx = np.maximum(np.abs(g @ along) - half_len, 0)
    dist = np.hypot(dx, g @ inward)            # in-skin distance from the slot's centre line
    t = np.clip((reach + FALL - dist) / FALL, 0, 1)
    bump = THICK + PAD * t * t * (3 - 2 * t)   # smoothstep
    box = tuple(slice(a, z) for a, z in zip(i0, i1))
    thick[box] = np.maximum(thick[box], bump)


def rasterise(p):
    g = np.zeros(shape, bool)
    i = np.round((p - lo) / PITCH).astype(int)
    g[i[:, 0], i[:, 1], i[:, 2]] = True
    return g


solid = binary_fill_holes(rasterise(pts))
d_in = distance_transform_edt(solid) * PITCH
d_skin = distance_transform_edt(~rasterise(skin_pts)) * PITCH
# Inside the part AND within the local thickness of the skin.
field = np.where(solid, np.minimum(d_in, thick - d_skin), -PITCH)

verts, faces, _, _ = marching_cubes(field, PITCH / 2, spacing=(PITCH,) * 3)
verts += lo
smooth = trimesh.Trimesh(verts, faces[:, ::-1])
trimesh.smoothing.filter_taubin(smooth, iterations=5)  # take the voxel steps off the skin
shell = m3d.Manifold(m3d.Mesh(vert_properties=smooth.vertices.astype(np.float32),
                              tri_verts=smooth.faces.astype(np.uint32)))
shell = shell.simplify(0.05)  # 1M triangles -> slicer-friendly, max 0.05 mm deviation
assert shell.status() == m3d.Error.NoError, shell.status()
shell = shell.trim_by_plane(b.tolist(), float(cut))             # keep the back
assert not shell.is_empty(), "nothing left after trimming"

# Stadium slots (round ends: TPU tears from sharp corners).
r = SLOT_W / 2
stadium = m3d.Manifold.hull(m3d.Manifold.batch_boolean(
    [m3d.Manifold.cylinder(4 * (THICK + PAD), r, r, 48, True).translate([sx * (half_len - r), 0, 0])
     for sx in (-1, 1)], m3d.OpType.Add))
for name, (c, along, inward, n) in slots.items():
    xf = np.hstack([np.column_stack([along, inward, n]), c[:, None]])
    genus = shell.genus()
    shell = shell - stadium.transform(xf)
    # A slot that goes all the way through adds exactly one handle.
    through = shell.genus() == genus + 1
    print(f"{name:13s} slot at {np.round(c, 1)} normal {np.round(n, 2)} through={through}")
    assert through, f"{name} slot does not cut through the shell"

out = shell.to_mesh()
res = trimesh.Trimesh(out.vert_properties[:, :3], out.tri_verts)
# Print orientation: flat rim on the bed, back (wiping) surface up.
flip = trimesh.geometry.align_vectors(b, [0, 0, 1])
hips = flip[:3, :3] @ [1.0, 0, 0]               # keep hip-to-hip along the bed's X
flip = trimesh.transformations.rotation_matrix(-np.arctan2(hips[1], hips[0]), [0, 0, 1]) @ flip
res.apply_transform(flip)
res.apply_translation(-res.bounds[0])
res.export(DST)
print(f"wrote {DST}: {res.extents.round(1)} mm, {res.volume / 1000:.0f} cm3, "
      f"{len(res.faces)} triangles, watertight={res.is_watertight}")
