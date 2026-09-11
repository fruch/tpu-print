#!/usr/bin/env bash
# Slice every calibration + model STL for both printers and build an estimate table.
# Re-runnable: safe to run again after you fill the PENDING values into the profiles.
set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

# ---------------------------------------------------------------- config ----
ORCA="${ORCA:-$HOME/Downloads/OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.2.AppImage}"
BAMBU="${BAMBU:-$HOME/Applications/BambuStudio.AppImage}"
ORCA_SYS="$HOME/.config/OrcaSlicer/system"
BAMBU_SYS="$HOME/.config/BambuStudio/system"
BAMBU_USER="$HOME/.config/BambuStudio/user/default/filament"

# Every printer this script drives. Adding one means adding its presets and
# its ORCA_* array below, and its name here.
PRINTER_LIST=(ender3pro geniuspro h2s)

ENDER_MACHINE="$ORCA_SYS/Creality/machine/Creality Ender-3 Pro 0.4 nozzle.json"
ENDER_PROCESS="$ORCA_SYS/Creality/process/0.20mm Standard @Creality Ender3 Pro 0.4.json"
# Slice straight from the repo copies: Orca resolves `inherits` against the
# system presets by name regardless of where the file sits, so CLI slicing does
# not depend on the GUI install having happened (or having gone to the right
# profile folder).
ENDER_FILAMENT="$HERE/profiles/orca/CC3D TPU 98A Skin @Ender3Pro.json"

GENIUS_MACHINE="$ORCA_SYS/Artillery/machine/Artillery Genius Pro 0.4 nozzle.json"
GENIUS_PROCESS="$ORCA_SYS/Artillery/process/0.20mm Standard @Artillery Genius Pro.json"
GENIUS_FILAMENT="$HERE/profiles/orca/CC3D TPU 98A Skin @GeniusPro.json"

H2S_MACHINE="$ORCA_SYS/BBL/machine/Bambu Lab H2S 0.4 nozzle.json"
H2S_PROCESS="$ORCA_SYS/BBL/process/0.20mm Standard @BBL H2S.json"
H2S_FILAMENT="$HERE/profiles/orca/CC3D TPU 98A Skin @H2S.json"

BS_MACHINE="$BAMBU_SYS/BBL/machine/Bambu Lab H2S 0.4 nozzle.json"
BS_PROCESS="$BAMBU_SYS/BBL/process/0.20mm Standard @BBL H2S.json"
BS_FILAMENT_GUI="$BAMBU_USER/CC3D TPU 98A Skin.json"
BS_FILAMENT_CLI="$HERE/profiles/bambustudio/cli/CC3D TPU 98A Skin (CLI).json"

# The Ender chain never sets use_relative_e_distances, so Orca falls back to
# relative E while layer_change_gcode is empty, and refuses to slice:
#   "Relative extruder addressing requires resetting the extruder position ..."
ENDER_FIX=(--layer-change-gcode $'G92 E0\n')

# The two vendors' stock process presets disagree on more than one thing that
# drives material use -- infill (Creality 15% vs BBL 20%) and solid shells
# (Creality 7 top / 5 bottom vs BBL 4 / 3). Left alone, a model comparison
# measures those preset defaults rather than the printers, so pin a single
# lightweight profile across both. Each is overridable; set MODEL_INFILL= to
# an empty string to fall back to each preset's own defaults entirely.
# Tuned for a SOFT part in 98A TPU. 98A is the stiff end of TPU, so all the
# compliance has to come from geometry:
#   wall_loops      2, not 1. A single 0.42mm wall prints translucent and
#                   brittle and is too fragile for a part that gets handled,
#                   and on a Bowden machine it has nothing to hide
#                   under-extrusion behind. Two walls cost no extra print time.
#                   Pressing down on a broad face is carried mostly by the
#                   infill and the top shell, so this firms up the edges and
#                   the skin far more than it firms up the squeeze.
#   shells          solid top/bottom sheets are what make a print feel like a
#                   hard shell. 3 is about the floor before 5% infill pillows.
#   gyroid          isotropic and has no straight vertical columns, so it
#                   squashes evenly instead of feeling like a stack of ribs.
MODEL_INFILL="${MODEL_INFILL-4%}"
MODEL_PATTERN="${MODEL_PATTERN-gyroid}"
MODEL_WALLS="${MODEL_WALLS-2}"
# Tightens the gyroid wave along Z at low density, shortening the effective
# vertical column length so the infill resists compression BUCKLING instead of
# crushing permanently. Filament use is unchanged, and it only does anything
# below ~30% density with a gyroid pattern -- i.e. exactly this profile.
MODEL_GYROID_OPT="${MODEL_GYROID_OPT-1}"
MODEL_TOP="${MODEL_TOP-3}"
MODEL_BOTTOM="${MODEL_BOTTOM-3}"

MODEL_OVERRIDE=()
if [[ -n "$MODEL_INFILL" ]]; then
    MODEL_OVERRIDE=(
        --sparse-infill-density "$MODEL_INFILL"
        --sparse-infill-pattern "$MODEL_PATTERN"
        --wall-loops            "$MODEL_WALLS"
        --top-shell-layers      "$MODEL_TOP"
        --bottom-shell-layers   "$MODEL_BOTTOM"
    )
fi

# Orca-only: Bambu Studio has no --gyroid-optimized and dies with "setup params
# error" if handed one, so it stays out of the shared override list.
ORCA_ONLY=()
if [[ -n "$MODEL_INFILL" && "$MODEL_PATTERN" == "gyroid" ]]; then
    ORCA_ONLY=(--gyroid-optimized="$MODEL_GYROID_OPT")
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

bold() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
die()  { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# ------------------------------------------------------------- 0. checks ----
bold "0. Tooling"
[[ -x "$ORCA"  ]] || die "OrcaSlicer AppImage not found/executable: $ORCA  (override with ORCA=...)"
[[ -x "$BAMBU" ]] || die "Bambu Studio AppImage not found/executable: $BAMBU (override with BAMBU=...)"
echo "  Orca  : $ORCA"
echo "  Bambu : $BAMBU"
for f in "$ENDER_MACHINE" "$ENDER_PROCESS" "$GENIUS_MACHINE" "$GENIUS_PROCESS" \
         "$H2S_MACHINE" "$H2S_PROCESS" "$BS_MACHINE" "$BS_PROCESS"; do
    [[ -f "$f" ]] || die "missing preset: $f"
done

# ------------------------------------------------------- 1. sync profiles ---
bold "1. Install filament profiles"
if pgrep -f "bin/orca-slicer" >/dev/null 2>&1; then
    printf '\033[33m  WARNING: OrcaSlicer is running. It loads presets at startup and rewrites\033[0m\n'
    printf '\033[33m           its user preset folder on exit, so it will neither see these\033[0m\n'
    printf '\033[33m           presets nor keep them. Close Orca and re-run.\033[0m\n'
fi
python3 scripts/install_orca_presets.py "profiles/orca/*.json"
[[ -f "$BS_FILAMENT_GUI" ]] || die "Bambu Studio preset missing: $BS_FILAMENT_GUI (create it in the GUI first)"
python3 scripts/make_cli_preset.py "$BS_FILAMENT_GUI" "$BS_FILAMENT_CLI"

for f in "$ENDER_FILAMENT" "$GENIUS_FILAMENT" "$H2S_FILAMENT" "$BS_FILAMENT_CLI"; do
    [[ -f "$f" ]] || die "missing filament preset: $f"
done

pending=$(grep -l PENDING profiles/orca/*.json 2>/dev/null | wc -l)
if (( pending > 0 )); then
    printf '\033[33m  NOTE: %d profile(s) still contain PENDING calibration values.\033[0m\n' "$pending"
    printf '\033[33m        Estimates below are directional, not final.\033[0m\n'
fi

# --------------------------------------------------------- 2. model check ---
bold "2. Model inspection"
python3 scripts/inspect_models.py calibration model

# --------------------------------------------------------------- 3. slice ---
# slice <label> <outdir> <jobname> <stl> -- <slicer argv...>
slice_one() {
    local label="$1" outdir="$2" job="$3" stl="$4"; shift 5   # drop the "--"
    local work="$TMP/work"; rm -rf "$work"; mkdir -p "$work"
    local log="$TMP/slice.log"

    if ! "$@" --slice 0 --arrange 1 --outputdir "$work" "$stl" >"$log" 2>&1; then
        echo; cat "$log" >&2
        die "slice failed: [$label] $job"
    fi
    # Orca/Bambu exit 0 even on a slicing error; result.json is the real verdict.
    if [[ -f "$work/result.json" ]]; then
        local rc err
        rc=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('return_code',0))" "$work/result.json")
        err=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('error_string',''))" "$work/result.json")
        if [[ "$rc" != "0" ]]; then
            echo; cat "$log" >&2; echo "result.json: rc=$rc $err" >&2
            die "slice failed: [$label] $job -> $err"
        fi
    fi
    shopt -s nullglob
    local produced=("$work"/*.gcode)
    shopt -u nullglob
    (( ${#produced[@]} )) || { cat "$log" >&2; die "no g-code produced: [$label] $job"; }

    mkdir -p "$outdir"
    if (( ${#produced[@]} == 1 )); then
        mv "${produced[0]}" "$outdir/$job.gcode"
    else
        local i=1
        for g in "${produced[@]}"; do mv "$g" "$outdir/${job}_plate${i}.gcode"; ((i++)); done
    fi
    printf '  ok  %-12s %-12s %s\n' "$label" "$(basename "$outdir")" "$job"
}

# A project .3mf already carries its own machine/process/filament config —
# that is the whole point of exporting a calibration plate from Orca's
# Calibration menu. Overriding presets on top of one would throw away the
# per-object settings and custom G-code that make the test a test, so 3mf is
# sliced bare and only STL gets the printer presets applied.
slice_dir() {
    local label="$1" srcdir="$2" outdir="$3" mode="$4"; shift 4
    [[ -d "$srcdir" ]] || return 0
    shopt -s nullglob nocaseglob
    local files=("$srcdir"/*.stl "$srcdir"/*.3mf)
    shopt -u nullglob nocaseglob
    if (( ${#files[@]} == 0 )); then
        printf '  --  %-12s %s is empty, nothing to slice\n' "$label" "$srcdir"
        return 0
    fi
    local slicer_bin="$1"
    for f in "${files[@]}"; do
        local job; job="$(basename "${f%.*}")"
        if [[ "${f,,}" == *.3mf && "$mode" == "respect3mf" ]]; then
            slice_one "$label" "$outdir" "$job" "$f" -- "$slicer_bin"
        else
            slice_one "$label" "$outdir" "$job" "$f" -- "$@"
        fi
    done
}

bold "3. Slice"
if [[ -n "$MODEL_INFILL" ]]; then
    echo "  soft profile pinned on all printers: ${MODEL_WALLS} wall(s)," \
         "infill $MODEL_INFILL $MODEL_PATTERN, shells ${MODEL_TOP} top / ${MODEL_BOTTOM} bottom"
else
    echo "  model: each preset's own defaults (they differ per vendor — not comparable)"
fi
# Remove only what THIS script generates. `rm -rf out` would also take
# out/calibration/, which calibrate.sh writes and which can represent hours of
# printing decisions -- never blanket-delete a directory you do not own.
# Delete only what THIS script owns. out/<printer>/calibration/ belongs to
# calibrate.sh and can represent hours of printing decisions.
for _p in "${PRINTER_LIST[@]}"; do
    rm -rf "out/$_p/model" "out/$_p/preflight"
done
rm -f  out/estimates.csv out/estimates.md
for _p in "${PRINTER_LIST[@]}"; do mkdir -p "out/$_p/model" "out/$_p/preflight"; done
mkdir -p out/h2s/model/bambustudio

ORCA_ENDER=("$ORCA" --load-settings "$ENDER_MACHINE;$ENDER_PROCESS" --load-filaments "$ENDER_FILAMENT" "${ENDER_FIX[@]}")
ORCA_GENIUS=("$ORCA" --load-settings "$GENIUS_MACHINE;$GENIUS_PROCESS" --load-filaments "$GENIUS_FILAMENT" "${ENDER_FIX[@]}")
ORCA_H2S=("$ORCA"   --load-settings "$H2S_MACHINE;$H2S_PROCESS"     --load-filaments "$H2S_FILAMENT")
BS_H2S=("$BAMBU"    --load-settings "$BS_MACHINE;$BS_PROCESS"       --load-filaments "$BS_FILAMENT_CLI")

# Calibration STLs are per-printer: what you export from Orca's Calibration menu
# is already bound to the machine it was generated for.
slice_dir "ender3pro" calibration/ender3pro out/ender3pro/calibration respect3mf "${ORCA_ENDER[@]}"
slice_dir "geniuspro" calibration/geniuspro out/geniuspro/calibration respect3mf "${ORCA_GENIUS[@]}"
slice_dir "h2s"       calibration/h2s       out/h2s/calibration       respect3mf "${ORCA_H2S[@]}"

slice_dir "ender3pro" model out/ender3pro/model         presets "${ORCA_ENDER[@]}" "${MODEL_OVERRIDE[@]}" "${ORCA_ONLY[@]}"
slice_dir "geniuspro" model out/geniuspro/model        presets "${ORCA_GENIUS[@]}" "${MODEL_OVERRIDE[@]}" "${ORCA_ONLY[@]}"
slice_dir "h2s"       model out/h2s/model               presets "${ORCA_H2S[@]}"   "${MODEL_OVERRIDE[@]}" "${ORCA_ONLY[@]}"
slice_dir "h2s/bs"    model out/h2s/model/bambustudio   presets "${BS_H2S[@]}"     "${MODEL_OVERRIDE[@]}"

# ----------------------------------------------------------- 4. preflight ---
# Does the real footprint stick? Nothing else answers that: the coupon above
# has a fraction of the bed contact. This is ONLY an adhesion check -- the
# bottom of the part is flat, so it shows no structure and is not something to
# squeeze. Raise PREFLIGHT_LAYERS, or use scripts/preflight.py --height, to
# keep real geometry, at the cost of a much longer print.
bold "4a. Squish coupon (rounded, real thickness, model settings)"
# The point of this one is FEEL. It is printed at the real wall count, the real
# infill and the real pattern, at full scale, so squeezing it tells you how the
# finished part will behave. Scaling the model down would not: wall thickness
# does not scale, so a small copy is proportionally far stiffer.
# It is a plain block, not the part's shape -- geometry is what the pre-flight
# below and the estimates are for.
# A rounded box rather than a cube: the real part is a curved organic form, and
# curvature changes how a single wall wraps the surface. Its footprint
# proportions are copied from the real model. A rounded box beats a dome here
# because the broad flat-ish top is something you can actually press a thumb
# into, and beats a sphere because a sphere's lower half is one large overhang
# that would need supports.
# HEIGHT stays at the part's real thickness -- squish depends on wall thickness
# relative to part thickness, so shrinking the height would stiffen it the same
# way scaling the whole model down does.
SQUISH_SIZE="${SQUISH_SIZE:-62}"
SQUISH_HEIGHT="${SQUISH_HEIGHT:-30}"
SQ_STL="calibration/squish_coupon.stl"
SQ_ASPECT=""
first_model="$(ls model/*.stl 2>/dev/null | head -1)"
[[ -n "$first_model" ]] && SQ_ASPECT="--aspect-from ../$first_model"
SQUISH_RADIUS="${SQUISH_RADIUS:-12}"  # generous fillet; the real part has no sharp edges
(cd scripts && python3 make_test_shapes.py "${SQUISH_SHAPE:-rbox}" --out "../$SQ_STL" \
    --size "$SQUISH_SIZE" --height "$SQUISH_HEIGHT" \
    --radius "$SQUISH_RADIUS" $SQ_ASPECT) 2>/dev/null

for printer in "${PRINTER_LIST[@]}"; do
    case "$printer" in
      ender3pro) ARGV=("${ORCA_ENDER[@]}") ;;
      geniuspro) ARGV=("${ORCA_GENIUS[@]}") ;;
      h2s)       ARGV=("${ORCA_H2S[@]}") ;;
      *) die "no slicer arguments defined for printer '$printer'" ;;
    esac
    slice_one "$printer" "out/$printer/preflight" "squish_coupon" "$SQ_STL" -- \
        "${ARGV[@]}" "${MODEL_OVERRIDE[@]}" "${ORCA_ONLY[@]}"
done

bold "4b. Adhesion check (first ${PREFLIGHT_LAYERS:-25} layers of the real part)"
shopt -s nullglob
for g in out/*/model/*.gcode; do
    printer="$(cut -d/ -f2 <<< "$g")"
    dest="out/$printer/preflight/adhesion_$(basename "$g")"
    mkdir -p "out/$printer/preflight"
    printf '  %-10s %-28s ' "$printer" "$(basename "$dest")"
    python3 scripts/preflight.py "$g" "$dest" --layers "${PREFLIGHT_LAYERS:-25}" 2>&1 \
        | sed 's/^# //' || true
done
shopt -u nullglob

# ------------------------------------------------------------ 5. estimate ---
bold "5. Estimates"
python3 scripts/parse_estimates.py out

# The AppImages drop a numbered log in the working directory.
rm -f "$HERE"/[0-9]*.log

bold "Done"
echo "  out/estimates.md   <- read this"
echo "  out/estimates.csv"
