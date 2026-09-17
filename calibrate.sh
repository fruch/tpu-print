#!/usr/bin/env bash
# Generate every TPU calibration print from the CLI -- no OrcaSlicer GUI.
#
#   ./calibrate.sh                 all tests, both printers
#   ./calibrate.sh level           just the first-layer / bed-levelling sheet
#   ./calibrate.sh temp            just the temperature tower
#   ./calibrate.sh retraction flow
#   PRINTERS=ender3pro ./calibrate.sh
#
# temp is a single tower (temperature is injected per layer band).
# retraction / flow / mvs are SWEEPS: the value cannot change mid-print, so
# each produces one small G-code per value. Print them in order and compare.
set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

ORCA="${ORCA:-$HOME/Downloads/OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.2.AppImage}"
SYS="$HOME/.config/OrcaSlicer/system"

PRINTERS="${PRINTERS:-ender3pro geniuspro h2s}"
TESTS=("$@"); [[ ${#TESTS[@]} -eq 0 ]] && TESTS=(level temp flow retraction mvs)

# CC3D rates this filament 195-215 C. Bracket the spec: a little over the top
# to find the ceiling, a little under the bottom. Sweeping to 235 puts half the
# tower above the filament's maximum, where it oozes regardless of anything
# else -- which then looks exactly like a moisture problem.
# FAST=1 trades resolution for time: coarser steps and shorter bands, so a
# whole suite fits in about an hour instead of three and a half. Good enough to
# find the right neighbourhood; re-run without it later to refine.
if [[ "${FAST:-0}" == "1" ]]; then
    : "${STEP:=10}" "${BAND:=4}" "${FLOW_STEP:=10}" "${SPD_STEP:=25}"
    : "${RETR_ENDER:=1 2.5 4 6}" "${RETR_GENIUS:=0.5 1 1.5 2}" "${RETR_H2S:=0.2 0.5 0.8}"
    : "${RETR_BAND:=7}"
fi

T_START="${START:-225}"; T_END="${END:-195}"; T_STEP="${STEP:-5}"; T_BAND="${BAND:-6}"

# Sweep values. Bowden and direct drive need different retraction ranges.
RETR_ENDER="${RETR_ENDER:-1 2 3 4 5 6}"   # Orca recommends 1-6mm for Bowden
RETR_GENIUS="${RETR_GENIUS:-0.5 1.0 1.5 2.0}"
RETR_H2S="${RETR_H2S:-0.2 0.4 0.6 0.8}"
RETR_BAND="${RETR_BAND:-10}"   # taller bands than the other towers: more travels to judge
FLOW_START="${FLOW_START:-90}"; FLOW_END="${FLOW_END:-115}"; FLOW_STEP="${FLOW_STEP:-5}"
SPD_START="${SPD_START:-40}";  SPD_END="${SPD_END:-140}";  SPD_STEP="${SPD_STEP:-20}"

# Calibration prints must be RIGID. The soft 1-wall / 5% profile used for the
# real part gives a floppy tower that falls over and measures nothing.
CAL=(--wall-loops 3 --sparse-infill-density 15% --top-shell-layers 3
     --bottom-shell-layers 3 --brim-type outer_only --brim-width 5
     --travel-speed 80)

bold() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
info() { printf '\033[36m%s\033[0m\n' "$*"; }
die()  { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

[[ -x "$ORCA" ]] || die "OrcaSlicer not found: $ORCA (override with ORCA=...)"

presets_for() {
    case "$1" in
      ender3pro)
        MACHINE="$SYS/Creality/machine/Creality Ender-3 Pro 0.4 nozzle.json"
        PROCESS="$SYS/Creality/process/0.20mm Standard @Creality Ender3 Pro 0.4.json"
        FILAMENT="$HERE/profiles/orca/CC3D TPU 98A Skin @Ender3Pro.json"
        # Ender chain leaves use_relative_e_distances unset -> relative E with
        # an empty layer_change_gcode, which Orca refuses to slice.
        EXTRA=(--layer-change-gcode $'G92 E0\n'); MVS_CEIL="${MVS_CEIL_ENDER:-5}" ;;
      geniuspro)
        MACHINE="$SYS/Artillery/machine/Artillery Genius Pro 0.4 nozzle.json"
        PROCESS="$SYS/Artillery/process/0.20mm Standard @Artillery Genius Pro.json"
        FILAMENT="$HERE/profiles/orca/CC3D TPU 98A Skin @GeniusPro.json"
        # Same gap as the Ender: the chain never sets use_relative_e_distances,
        # so Orca falls back to relative E with an empty layer_change_gcode.
        EXTRA=(--layer-change-gcode $'G92 E0\n'); MVS_CEIL="${MVS_CEIL_GENIUS:-8}" ;;
      h2s)
        MACHINE="$SYS/BBL/machine/Bambu Lab H2S 0.4 nozzle.json"
        PROCESS="$SYS/BBL/process/0.20mm Standard @BBL H2S.json"
        FILAMENT="$HERE/profiles/orca/CC3D TPU 98A Skin @H2S.json"
        EXTRA=(); MVS_CEIL="${MVS_CEIL_H2S:-16}" ;;
      *) die "unknown printer '$1' (expected ender3pro, geniuspro or h2s)" ;;
    esac
    [[ -f "$MACHINE" && -f "$PROCESS" && -f "$FILAMENT" ]] || die "missing preset for $1"
}

# slice <stl> <destination.gcode> [extra orca args...]
slice_to() {
    local stl="$1" dest="$2"; shift 2
    local work; work="$(mktemp -d)"
    if ! "$ORCA" --load-settings "$MACHINE;$PROCESS" --load-filaments "$FILAMENT" \
             "${EXTRA[@]}" "${CAL[@]}" "$@" \
             --slice 0 --arrange 1 --outputdir "$work" "$stl" >"$work/log" 2>&1; then
        cat "$work/log" >&2; rm -rf "$work"; die "slice failed -> $dest"
    fi
    local rc; rc=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('return_code',0))" "$work/result.json")
    [[ "$rc" == "0" ]] || { cat "$work/log" >&2; rm -rf "$work"; die "slice failed -> $dest (rc=$rc)"; }
    mkdir -p "$(dirname "$dest")"
    mv "$work"/*.gcode "$dest"
    rm -rf "$work"
}

est() { python3 scripts/inspect_gcode.py "$1" | grep -oE "est\. time.*" | sed 's/est\. time *: //'; }

mkdir -p calibration

for printer in $PRINTERS; do
    presets_for "$printer"
    OUT="out/$printer/calibration"
    STEP_N=0
    mkdir -p "$OUT"
    : > "out/$printer/.calibration.index"   # collected into INDEX.md at the end

    # nn <slug> -> sets FN to "out/calibration/<printer>/NN_<slug>.gcode"
    nn() {
        STEP_N=$((STEP_N + 1))
        FN="$(printf '%s/%02d_%s.gcode' "$OUT" "$STEP_N" "$1")"
    }
    note() { printf '%s\t%s\t%s\t%s\n' "$(basename "$FN")" "$1" "$2" "$3" >> "out/$printer/.calibration.index"; }

    for test in "${TESTS[@]}"; do
    case "$test" in

      level|first-layer)
        bold "$printer · first layer / bed levelling"
        STL="calibration/first_layer.3mf"
        [[ -f "$STL" ]] || die "missing $STL"
        # One solid layer with the lines all running the same way: uneven bed
        # height shows immediately as a change in line width or gaps, and a
        # single direction makes that far easier to read than the 45 default.
        nn "level_first_layer"
        slice_to "$STL" "$FN" \
            --infill-direction=0 --solid-infill-direction=0 \
            --sparse-infill-density 100% --bottom-shell-layers 1 \
            --brim-type outer_only --brim-width 3
        printf '  %-28s %s\n' "$(basename "$FN")" "$(est "$FN")"
        note "First layer / bed levelling" "first layer / bed level" "All lines run the same way. Look for width changes, gaps, or squashed shiny patches -- those are high/low spots. Adjust the bed and reprint until uniform."
        ;;

      temp)
        bold "$printer · temperature tower  ${T_START}->${T_END} C"
        STL="calibration/temp_tower.stl"
        LG="$(python3 scripts/make_temp_tower.py --start "$T_START" --end "$T_END" \
                --step "$T_STEP" --band-height "$T_BAND" --out "$STL" 2>/dev/null)"
        EXTRA_SAVE=("${EXTRA[@]}"); EXTRA=(--layer-change-gcode "$LG")
        nn "temp_tower_${T_START}-${T_END}"
        slice_to "$STL" "$FN"
        EXTRA=("${EXTRA_SAVE[@]}")
        python3 scripts/inspect_gcode.py "$FN" | grep -E "TEMP SWEEP|band starts" | sed 's/^ */  /' || true
        printf '  %-28s %s\n' "$(basename "$FN")" "$(est "$FN")"
        note "Temperature tower" "temperature tower ${T_START}-${T_END}C" "ONE print. Bottom band = ${T_START}C, each ${T_BAND}mm band ${T_STEP}C cooler going up. Pick the coolest band with no stringing between the pillars and no rough/bubbly surface."
        ;;

      retraction)
        bold "$printer · retraction tower"
        case "$printer" in
          geniuspro) vals="$RETR_GENIUS" ;;
          h2s)       vals="$RETR_H2S" ;;
          *)         vals="$RETR_ENDER" ;;
        esac
        nvals=$(wc -w <<< "$vals")
        towerh=$(python3 -c "print($nvals * $RETR_BAND)")
        STL="calibration/retraction_pillars.stl"
        (cd scripts && python3 make_test_shapes.py pillars --out "../$STL" \
            --height "$towerh" --bands "$nvals") 2>/dev/null

        # Slice ONCE at a known retraction with wipe off, then rescale the
        # retraction moves per band. Wipe must be off: with it on a retraction
        # is smeared over several travel moves and cannot be rescaled as one
        # number. Relative E (M83) is what makes the rescale safe.
        base=$(awk '{print $1}' <<< "$vals")
        raw="$(mktemp -d)/raw.gcode"
        EXTRA_SAVE=("${EXTRA[@]}")
        slice_to "$STL" "$raw" --filament-wipe=0 --filament-retraction-length "$base" --wall-loops 2
        EXTRA=("${EXTRA_SAVE[@]}")

        nn "retraction_tower"
        python3 scripts/retraction_tower.py "$raw" "$FN" \
            --base "$base" --values "$vals" --band-height "$RETR_BAND" \
            | sed 's/^/  /'
        rm -rf "$(dirname "$raw")"
        printf '  %-28s %s\n' "$(basename "$FN")" "$(est "$FN")"
        note "Retraction tower" "retraction tower ${vals// /, } mm" "ONE print. Two pillars with a gap; retraction changes every ${RETR_BAND}mm going up (bottom band first, values: ${vals}). Fewest strings across the gap wins. Prefer the SHORTEST band that is clean -- more retraction than you need grinds TPU in the extruder."
        ;;

      flow)
        bold "$printer · flow ratio tower (M221 per band)"
        STL="calibration/flow_tower.stl"
        LG="$(python3 scripts/make_temp_tower.py --mode flow --shape stairs \
                --start "$FLOW_START" --end "$FLOW_END" --step "$FLOW_STEP" \
                --band-height "$T_BAND" --out "$STL" 2>/dev/null)"
        EXTRA_SAVE=("${EXTRA[@]}"); EXTRA=(--layer-change-gcode "$LG")
        nn "flow_tower_${FLOW_START}-${FLOW_END}pct"
        # Flow is read off the TOP skin, so give each step a proper one and
        # a monotonic pattern, which is what makes gaps between lines visible.
        slice_to "$STL" "$FN" --top-shell-layers 4 --wall-loops 2 \
            --top-surface-pattern monotonic --top-surface-line-width 0.42
        EXTRA=("${EXTRA_SAVE[@]}")
        printf '  %-28s %s\n' "$(basename "$FN")" "$(est "$FN")"
        note "Flow ratio tower" "flow tower ${FLOW_START}-${FLOW_END}%" "ONE print, a staircase: each STEP has its own top surface, printed at its own flow. Lowest step = ${FLOW_START}%, +${FLOW_STEP}% per step going up. Look DOWN at the steps: gaps between the lines = too little flow, ridged or bulging = too much. The smoothest step wins; its % / 100 is your flow ratio."
        ;;

      mvs)
        bold "$printer · max flow tower (M220 per band)"
        STL="calibration/speed_tower.stl"
        LG="$(python3 scripts/make_temp_tower.py --mode speed --shape block \
                --start "$SPD_START" --end "$SPD_END" --step "$SPD_STEP" \
                --band-height "$T_BAND" --out "$STL" 2>/dev/null)"
        EXTRA_SAVE=("${EXTRA[@]}"); EXTRA=(--layer-change-gcode "$LG")
        nn "maxflow_tower_${SPD_START}-${SPD_END}pct"
        # Slice with the cap lifted so the slicer does not limit speed itself;
        # M220 then does the sweeping at print time.
        slice_to "$STL" "$FN" --filament-max-volumetric-speed "$MVS_CEIL" --wall-loops 2
        EXTRA=("${EXTRA_SAVE[@]}")
        printf '  %-28s %s\n' "$(basename "$FN")" "$(est "$FN")"
        note "Max flow tower" "max flow tower ${SPD_START}-${SPD_END}% of ${MVS_CEIL} mm3/s" "ONE print. Speed rises ${SPD_STEP}% per ${T_BAND}mm band. Find the band where the surface first goes thin/rough/gappy - the extruder stopped keeping up there. Take the band BELOW it: mm3/s = ${MVS_CEIL} x that band% / 100."
        ;;

      pa|pressure-advance)
        bold "$printer · pressure advance"
        if [[ "$printer" == h2s ]]; then
            info "  SKIPPED: the H2S self-calibrates PA with its nozzle sensor."
            info "  A manual value fights that. Leave it on auto."
        else
            info "  SKIPPED: stock Creality 4.2.2 Marlin ships with LIN_ADVANCE off,"
            info "  so M900 K is ignored and any pattern you print is meaningless."
            info "  Flash Klipper first, then this becomes worth automating."
        fi
        ;;

      *) die "unknown test '$test' (temp retraction flow mvs pa)" ;;
    esac
    done
done

# Turn each printer's collected notes into a readable index.
for printer in $PRINTERS; do
    idx="out/$printer/.calibration.index"
    [[ -f "$idx" ]] || continue
    python3 - "$printer" "$idx" <<'PY'
import os, sys, re
printer, idx = sys.argv[1], sys.argv[2]
out = f"out/{printer}/calibration"
rows = [l.rstrip("\n").split("\t") for l in open(idx) if l.strip()]

def est(fn):
    """Marlin writes the estimate at the END of the file, BBL near the top."""
    path = os.path.join(out, fn)
    if not os.path.exists(path):
        return "?"
    with open(path, "rb") as fh:
        head = fh.read(200_000)
        size = os.path.getsize(path)
        fh.seek(max(0, size - 200_000))
        t = (head + fh.read()).decode("utf-8", "replace")
    m = (re.search(r"total estimated time:\s*(.+)", t)
         or re.search(r"estimated printing time \(normal mode\)\s*=\s*(.+)", t))
    return m.group(1).strip() if m else "?"

L = [f"# {printer} — calibration prints, in order", "",
     "Print them in the order numbered below. Each step depends on the ones",
     "before it, so do not skip ahead.", "",
     "**Before anything:** dry the filament (55 °C, 6–8 h). Wet TPU strings at",
     "every setting and makes all of these unreadable.", "",
     "| # | File | What it is | Time |", "|---|---|---|---|"]
for i, (fn, _group, what, _how) in enumerate(rows, 1):
    L.append(f"| {i} | `{fn}` | {what} | {est(fn)} |")

L += ["", "---", "", "## How to read each one", ""]
seen = set()
for fn, group, what, how in rows:
    if group in seen:
        continue
    seen.add(group)
    L += [f"### {group}", "", how, ""]

L += ["---", "",
      "## Why retraction is still several files",
      "",
      "Temperature, flow and speed are all swept inside a single tower: the",
      "firmware applies `M104` / `M221` / `M220` at print time, so one file can",
      "step through many values.",
      "",
      "Retraction length has no such command on this firmware — the distances are",
      "written into every travel move when the file is sliced and cannot change",
      "mid-print. So each value is its own small print. Work up from the shortest",
      "and stop at the first clean one; you rarely need them all.", "",
      "## When you have your numbers", "",
      "Put them into `profiles/orca/CC3D TPU 98A Skin @*.json`, delete that",
      "value's `PENDING` line from `filament_notes`, then run `./run.sh` for",
      "real estimates.", ""]
open(os.path.join(out, "INDEX.md"), "w").write("\n".join(L))
print(f"  wrote {out}/INDEX.md")
PY
    rm -f "$idx"
done

bold "Done"
cat <<'EOF'
  Everything is in out/<printer>/calibration/, numbered in print order.
  Read out/<printer>/calibration/INDEX.md -- it lists every file, what it is,
  and what to look for.
EOF
