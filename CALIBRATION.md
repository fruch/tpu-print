# TPU calibration — quick flow per printer

**Filament:** CC3D TPU 98A 340M, skin colour, 1.75 mm
**Printers:** Creality Ender 3 Pro (Bowden) · Bambu Lab H2S (direct drive)

Do all calibration in **OrcaSlicer**. Bambu Studio has no Calibration menu.
Orca is a Bambu Studio fork, so the filament fields map 1:1 and you can copy
the finished numbers across by hand afterwards.

---

## Step 0 — before anything (both printers)

1. **Dry the spool: 55 °C for 6–8 h.** Wet TPU makes every number below noise.
2. Loosen the spool so it unwinds with almost no pull. TPU stretches; any drag
   shows up as under-extrusion you will then wrongly "fix" in the flow test.
3. Stock brass 0.4 nozzle is fine. 98A is the forgiving end of TPU.

---

## Ender 3 Pro

### Hardware first — this is where Bowden TPU actually fails

| Check | Why |
|---|---|
| Back off the extruder idler spring until it *just* grips | Over-tension buckles TPU inside the arm |
| Inspect the plastic extruder arm for a hairline crack | The #1 cause of "TPU won't feed" — replace before calibrating |
| Close the gap between the extruder gear and the PTFE inlet | Any gap and TPU curls into it |

Do not calibrate around a cracked arm. You will be measuring the crack.

### Orca setup

- Printer: `Creality Ender-3 Pro 0.4 nozzle`
- Filament: `CC3D TPU 98A Skin @Ender3Pro`
- Process: `0.20mm Standard @Creality Ender3 Pro 0.4`

### Step 1a — set a retraction baseline BEFORE the temp tower

The Ender machine preset ships `retraction_length = 4 mm`. That is a PLA value.
At 4 mm on a Bowden tube TPU **buckles inside the tube instead of retracting**,
then oozes on the way back — so the temp tower strings at every temperature and
tells you nothing about temperature.

The usual advice ("temperature first") assumes retraction is merely suboptimal.
On Bowden + TPU it is bad enough to make the tower unreadable, so break the
order here. The profile now ships these as a starting point:

| Setting | Value | Why |
|---|---|---|
| retraction length | 2.5 mm | sane Bowden-TPU start; the tower becomes readable |
| retraction speed | 25 mm/s | fast retracts grind soft filament |
| wipe | on | cuts the ooze trail before travel |
| Z-hop type | **Normal Lift** | *Slope Lift* ramps diagonally and keeps the nozzle low across the part — it will clip a floppy TPU tower and knock it over |

Refine properly in step 4. This is only to make steps 1–3 legible.

### Order — each step depends on the one before

| # | Calibration menu | Range to set | Expect |
|---|---|---|---|
| 1 | Temperature | **225 → 195 °C**, 5 °C steps | brackets the vendor's 195–215; see note |
| 2 | Flow rate → Pass 1 (Coarse) → Pass 2 (Fine) | — | run both, in order |
| 3 | Pressure advance | **SKIP** | see below |
| 4 | Retraction test | 0.5 → 4 mm @ 25 mm/s | lands 2–3 mm |
| 5 | Advanced → Max flowrate | 1 → 8 mm³/s | lands **2–3 mm³/s** |
| 6 | Verification prints | — | see [Final verification](#final-verification) |

**Why skip pressure advance:** stock Creality 4.2.2 Marlin ships with
`LIN_ADVANCE` disabled, so Orca's PA pattern prints a meaningless result. Either
accept slightly soft corners, or flash Klipper first and then run it. Don't
spend an evening on the pattern otherwise.

**Step 5 is the one that decides quality here.** On Bowden, max flowrate is the
real ceiling, not the temperature.

### If the tower wobbles or gets knocked over

A temp tower is tall and thin, and in TPU it is floppy. In order of effect:

1. **Z-hop type → Normal Lift** (straight up, not the default Slope Lift).
2. **Drop travel speed** from 150 mm/s to ~80. A bed-slinger whips a tall part.
3. **Add a brim** — TPU sticks well, but the footprint is small.
4. **Print the calibration model rigid** — 2–3 walls, 15–20% infill. Do not use
   the soft 1-wall profile from `run.sh` for calibration prints; a floppy test
   tower measures nothing and falls over.

### If it strings at every temperature

Then it is not temperature. In order of likelihood:

1. **Wet filament.** TPU is strongly hygroscopic and this dominates everything
   else. 55 °C for 6–8 h. If you skipped step 0, do it now — no retraction value
   rescues wet TPU.
2. **Retraction too long** — see step 1a above.
3. **Nozzle too hot across the whole tower.** CC3D rates this filament
   195–215 °C. A 200–235 sweep spends half its bands above the maximum, where
   TPU oozes regardless of anything else — and the result looks exactly like a
   moisture problem. Use 225 → 195. `./calibrate.sh` now defaults to that.

---

## Bambu Lab H2S

### Hardware first

Nothing to modify — direct drive, hardened gears, hardened 0.4 nozzle. Two rules:

- Run TPU from the **external spool holder**, never the AMS 2 Pro.
- **Do not heat the chamber.** Leave the vents open. A warm filament path
  softens the strand before it reaches the gears.

### Orca setup

- Printer: `Bambu Lab H2S 0.4 nozzle`
- Filament: `CC3D TPU 98A Skin @H2S`
- Process: `0.20mm Standard @BBL H2S`

### Order

| # | Calibration menu | Range to set | Expect |
|---|---|---|---|
| 1 | Temperature | **225 → 195 °C**, 5 °C steps | or reuse the Ender's result |
| 2 | Flow rate → Pass 1 (Coarse) → Pass 2 (Fine) | — | run both, in order |
| 3 | Pressure advance | **leave on AUTO** | see below |
| 4 | Retraction test | 0 → 1 mm | lands 0.4–0.8 mm |
| 5 | Advanced → Max flowrate | 5 → 20 mm³/s | lands **8–12 mm³/s** |
| 6 | Verification prints | — | see [Final verification](#final-verification) |

**Why leave PA alone:** the H2S self-calibrates pressure advance per filament
using its eddy-current nozzle sensor. A manual PA value fights that and makes
things worse.

---

## Final verification

Skip the generic 20 mm cube. Orca ships **11 test models** — right-click the
plate in Prepare mode → **Add Handy Model**. Nothing to download.

Run these three, in this order:

| Model | What it catches | Why it matters for TPU |
|---|---|---|
| **Orca_stringhell** | stringing / oozing | Stringing is TPU's dominant failure mode. This is the harshest test there is, and it validates retraction *and* temperature together — the two you just calibrated |
| **OrcaToleranceTest** | real fit tolerance | Base with six hex holes at 0.0 / 0.05 / 0.1 / 0.2 / 0.3 / 0.4 mm plus a hex tester. Check with a 6 mm Allen key or the printed tester |
| **ksr_fdmtest_v4** | overhangs, bridges, holes | All-in-one torture test, once the two above pass |

Also available: `OrcaCube_v2`, `Voron_Design_Cube_v7`, `OrcaPlug_v2`, `calicat`,
`3DBenchy`, `Stanford_Bunny`. If you want a cube, **use Voron_Design_Cube_v7 or
OrcaCube_v2** — both are better designed than a generic XYZ cube.

**Don't bother with 3DBenchy for TPU.** It is a PLA benchmark; its overhangs and
bridging will look bad in any flexible filament and teach you nothing about your
settings.

### Acting on the tolerance result

Measure the holes and the tester with calipers, then correct with:

- **Filament settings → Basic information** → Shrinkage (XY), Shrinkage (Z)
- **Print settings → Quality → Precision** → X-Y hole compensation,
  X-Y contour compensation, Precise wall

Repeat until the fit is right. This matters more for TPU than for rigid
filament: a soft part deforms under caliper pressure, so measure gently and
consistently.

---

## What transfers between the two machines

| Value | Transfers? |
|---|---|
| Nozzle temperature | **Yes** — run the tower once, reuse |
| Flow ratio | Usually — re-verify with Pass 2 |
| Pressure advance | No |
| Retraction length | No — 2–3 mm Bowden vs 0.4–0.8 mm direct drive |
| Max volumetric speed | No — ~3 mm³/s vs ~10 mm³/s |

Run steps 3–5 separately on each printer. Only step 1 is shared.

---

## Recording the results

Orca writes flow rate and max volumetric speed **back into the filament preset
automatically** ("… calibration result has been saved to preset"). Temperature
and retraction you type in yourself:

**Filament settings → Filament** → nozzle temperature
**Filament settings → Setting Overrides** → retraction length

Then mirror them into this repo so a re-run picks them up:

```bash
cd ~/projects/tpu-print
cp ~/.config/OrcaSlicer/user/default/filament/"CC3D TPU 98A Skin @Ender3Pro.json" profiles/orca/
cp ~/.config/OrcaSlicer/user/default/filament/"CC3D TPU 98A Skin @H2S.json"       profiles/orca/
```

Delete the `PENDING` lines from `filament_notes` as you replace each value —
that is how you know what is left, and `run.sh` warns while any remain.

For the H2S, copy the same four numbers by hand into Bambu Studio's
`CC3D TPU 98A Skin` preset. The field names are identical.

---

## Saving a calibration plate for later re-slicing

Optional, and only useful if you want to reprint a test without setting it up again.

After Orca builds the calibration plate: **File → Save Project As** →
`calibration/ender3pro/` or `calibration/h2s/`, as `.3mf`.

A project `.3mf` carries its own machine, process and filament config plus the
per-object settings that make the test a test. `run.sh` slices `.3mf` files
**bare**, without overriding presets, precisely so those survive.

Exporting a calibration test as a plain **STL is useless** — the test lives in
the settings Orca attaches to the mesh, not in the geometry.

---

## After calibration

```bash
cd ~/projects/tpu-print
cp /path/to/your-part.stl model/
./run.sh
cat out/estimates.md
```

See [README.md](README.md) for what the script does and the CLI gotchas behind it.
