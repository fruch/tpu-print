# tpu-print

Batch-slice CC3D TPU 98A across a **Creality Ender 3 Pro** and a **Bambu Lab H2S**,
check models against both build volumes, and produce a side-by-side time/filament
estimate — without opening a GUI.

Calibration itself is a GUI job: see **[CALIBRATION.md](CALIBRATION.md)**.

---

## Layout

```
calibration/
  ender3pro/     drop calibration .3mf projects here (optional)
  h2s/
model/           drop the STL you actually want to print here
profiles/
  orca/          the two Orca filament presets — source of truth, edit these
  bambustudio/   snapshot of the GUI preset + a generated CLI-safe copy
scripts/
  inspect_models.py       bbox / manifold / build-volume fit (no dependencies)
  inspect_gcode.py        what a g-code contains: test type, temp sweep, retractions
  install_orca_presets.py install presets into the profile folder Orca really uses
  make_cli_preset.py      GUI preset -> Bambu-Studio-CLI-safe preset
  make_temp_tower.py      banded tower STL + the matching layer-change g-code
  make_test_shapes.py     pillars / plate test bodies
  retraction_tower.py     rescale retraction moves per band
  preflight.py            cut a long print down to its first N layers
  parse_estimates.py      G-code headers -> estimates.csv + estimates.md
out/                   generated; wiped on every run
run.sh                 the whole pipeline
```

## Use

Two entry points:

```bash
./calibrate.sh                 # generate the calibration prints (do this first)
cp ~/Downloads/my-part.stl model/
./run.sh                       # slice the real part + a pre-flight, and estimate
cat out/estimates.md
```

`calibrate.sh` writes `out/calibration/<printer>/`, numbered in print order, with
an `INDEX.md` explaining each file and what to look for. Work through those,
put the resulting numbers into `profiles/orca/*.json`, then re-run `./run.sh`.

`run.sh` also writes `out/preflight/` — the first 25 layers of the real part at
the real settings. Print that before committing to a long job.

Override the slicer locations if they move:

```bash
ORCA=/path/to/OrcaSlicer.AppImage BAMBU=/path/to/BambuStudio.AppImage ./run.sh
```

`run.sh` is re-runnable and idempotent: it wipes `out/`, reinstalls the profiles
from `profiles/orca/`, and re-slices everything. Run it once now for the build-volume
sanity check, and again after calibration gives you real numbers.

## Calibration (`calibrate.sh`)

```bash
./calibrate.sh                 # all tests, both printers
./calibrate.sh level           # just the first-layer / bed-levelling sheet
PRINTERS=h2s ./calibrate.sh temp
```

Five prints per printer, one per topic:

| # | Test | How one print covers many values |
|---|---|---|
| 1 | first layer / bed level | single solid layer, infill forced to 0° so height errors are obvious |
| 2 | temperature tower | `M104` injected per layer band |
| 3 | flow ratio tower | `M221` (extrusion multiplier) per band |
| 4 | retraction tower | sliced once, then the retraction moves are rescaled per band by `scripts/retraction_tower.py` |
| 5 | max flow tower | `M220` (feedrate multiplier) per band |

The first three use firmware commands that take effect at print time, which is
what lets one file sweep a value the slicer bakes in. Retraction has no such
command, so it is done by post-processing — which needs relative extrusion
(`M83`) and wipe disabled, both of which the script forces.

Pressure advance is deliberately skipped: stock Creality 4.2.2 Marlin ships
with `LIN_ADVANCE` off, and the H2S self-calibrates PA with its nozzle sensor.

## What `run.sh` does

1. **Checks tooling** — both AppImages present and executable, all presets resolve.
2. **Installs profiles** — copies `profiles/orca/*.json` into Orca's user preset
   dir and regenerates the Bambu Studio CLI preset. Warns if any profile still
   contains `PENDING`.
3. **Inspects models** — bounding box, triangle count, watertight/manifold status,
   and whether each part fits each bed (allowing a 90° Z rotation). Parts that
   don't fit get a minimum piece count.
   The check is deliberately conservative — it does not try diagonal placement,
   so a long thin part can be reported as not fitting and still slice fine once
   `--arrange` rotates it. Treat a `NO` as "look at this", not "impossible".
4. **Slices** into exactly two trees:
   ```
   out/ender3pro/{calibration,model}/
   out/h2s/{calibration,model,model/bambustudio}/
   ```
   The model goes through Bambu Studio as well as Orca for the H2S, so you can
   compare the two slicers on identical input.
5. **Parses estimates** into `out/estimates.csv` and `out/estimates.md`.

A failed slice stops the run with the slicer's full stderr. Nothing is skipped
silently, and no missing number is ever interpolated — absent fields are written
as `MISSING`.

---

## Model profile (softness knobs)

The model slices are pinned to one profile across both printers, tuned for a
**soft part in 98A TPU**. Without pinning, the comparison would just measure the
two vendors' preset defaults (Creality 15% infill / 7 top / 5 bottom vs
BBL 20% / 4 / 3).

| Env var | Default | Effect |
|---|---|---|
| `MODEL_WALLS` | `1` | **The dominant lever.** Bending stiffness goes with thickness³, so 2→1 walls softens far more than any infill change |
| `MODEL_INFILL` | `5%` | Lower is softer; below ~3% gyroid gets fragile |
| `MODEL_PATTERN` | `gyroid` | Isotropic, no vertical columns — squashes evenly instead of feeling ribbed |
| `MODEL_TOP` / `MODEL_BOTTOM` | `3` / `3` | Solid sheets are what make a print feel like a hard shell. 2 is softer but pillows at 5% infill |
| `MODEL_GYROID_OPT` | `1` | Tightens the gyroid wave along Z so sparse infill resists compression **buckling** instead of crushing permanently. Same filament, same time. Only does anything below ~30% density with gyroid — i.e. exactly this profile. Orca-only; Bambu Studio errors on the flag |

```bash
MODEL_WALLS=2 MODEL_INFILL=10% ./run.sh   # stiffer
MODEL_INFILL= ./run.sh                    # no pinning, each preset's own defaults
```

**98A is the stiff end of TPU** — roughly shopping-cart-wheel firm. Geometry can
make the part *compress*, but the surface will still feel firm. Genuinely
soft-to-touch means 85–95A filament; no slicer setting substitutes for that.

**One wall of TPU is hard to print on the Bowden Ender.** There is no second
wall to hide under-extrusion, so the flow and retraction calibration in
[CALIBRATION.md](CALIBRATION.md) stops being optional.

---

## Printers

| | Ender 3 Pro | H2S |
|---|---|---|
| Bed | 220 × 220 × 250 mm | 340 × 320 × 340 mm |
| Extruder | Bowden | Direct drive |
| Orca machine preset | `Creality Ender-3 Pro 0.4 nozzle` | `Bambu Lab H2S 0.4 nozzle` |
| Orca process preset | `0.20mm Standard @Creality Ender3 Pro 0.4` | `0.20mm Standard @BBL H2S` |
| Filament preset | `CC3D TPU 98A Skin @Ender3Pro` | `CC3D TPU 98A Skin @H2S` |
| Bambu Studio | — (not supported) | `CC3D TPU 98A Skin` |

---

## CLI gotchas found the hard way

These are all worked around in `run.sh`; documented so the workarounds aren't
mistaken for cargo cult.

**1. The Ender chain never sets `use_relative_e_distances`.**
Orca falls back to relative E while `layer_change_gcode` is empty, and refuses:

> Relative extruder addressing requires resetting the extruder position at each
> layer to prevent loss of floating point accuracy. Add "G92 E0" to layer_gcode.

Fixed by passing `--layer-change-gcode $'G92 E0\n'` on the Ender command only.

**2. Don't pre-flatten the `inherits` chain.** Orca resolves `inherits` itself
from the datadir. Handing it a flattened preset fails compatibility validation
with `return_code -17`, *"The selected printer is not compatible with the process
preset in the 3mf."* Pass the system preset paths as-is.

**3. Both slicers exit 0 on a failed slice.** The real verdict is `return_code`
in the `result.json` written to `--outputdir`. `run.sh` checks it.

**4. Bambu Studio's CLI rejects its own GUI presets.** The GUI omits `"type"` and
pads per-variant arrays with the string `"nil"`; the CLI then errors with
`unknown config type` and `nozzle_temperature: 215,nil,nil not in range`.
`make_cli_preset.py` writes a CLI-safe sibling and leaves the GUI preset alone.

**5. Generic TPU has no density, so grams come out `0.00`.** Both profiles pin
`filament_density` to 1.21 g/cm³ — the generic polyester-TPU figure, not a CC3D
spec. It only scales the gram estimate. Weigh a real print and correct it if the
grams matter. Both slicers use the same value so the comparison stays honest.

**6. Three G-code header formats, and one lies about units.**

| | Orca / Marlin (Ender) | Orca / BBL (H2S) | Bambu Studio |
|---|---|---|---|
| length | `filament used [mm] =` | same | `total filament length [mm] :` |
| volume | `filament used [cm3] =` | same | `total filament volume [cm^3] :` — **actually mm³** |
| weight | `total filament used [g] =` | `filament used [g] =` | `total filament weight [g] :` |
| time | `estimated printing time (normal mode) =` | `model printing time: …; total estimated time: …` | same as Orca/BBL |

`parse_estimates.py` handles all three and normalises the Bambu volume.

**7. Calibration tests do not survive an STL export.** The test is the settings
Orca attaches to the mesh, not the geometry. Save a **project `.3mf`** instead;
`run.sh` slices `.3mf` bare so the embedded config survives.

---

## Status

The two Orca profiles still carry `PENDING` markers on every calibration-derived
field — flow ratio, pressure advance, retraction length, max volumetric speed —
and the temperature is the vendor's starting point, not a measured one. Nothing
was invented. Estimates produced now are good for **comparing the two printers**,
not for predicting a real print time.

Work through [CALIBRATION.md](CALIBRATION.md), fill the values in, re-run.


---

## Third-party content

`calibration/first_layer.3mf` is a first-layer calibration patch that came from
elsewhere and carries no licence or designer metadata. It is included for
convenience; swap in your own if you would rather not redistribute it.

## Licence

MIT — see [LICENSE](LICENSE). The filament profiles and calibration numbers are
specific to CC3D TPU 98A on these two machines; treat them as a worked example,
not as values to copy.
