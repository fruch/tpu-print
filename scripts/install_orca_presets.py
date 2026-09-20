#!/usr/bin/env python3
"""Install filament presets into the profile folder OrcaSlicer is actually using.

Orca keeps user presets under ~/.config/OrcaSlicer/user/<profile>/filament/,
where <profile> is "default" when logged out but a Bambu account UUID when
logged in. The active one is named by `app.preset_folder` in OrcaSlicer.conf —
writing to the wrong one leaves the preset invisible in the GUI with no error.

Each preset also wants a companion ".info" file carrying sync metadata. We write
one with an empty sync_info so the preset stays local and is not pushed to the
user's Bambu cloud account.

The .info also carries the updated_time Orca uses to decide, on every launch,
whether to keep the local preset or replace it with the cloud copy. It compares
that field -- not the .json mtime -- so a preset installed here must claim a
fresh timestamp or Orca silently overwrites it. See write_info().
"""
import glob
import json
import os
import sys
import time

CONF = os.path.expanduser("~/.config/OrcaSlicer/OrcaSlicer.conf")
USER_ROOT = os.path.expanduser("~/.config/OrcaSlicer/user")
SYSTEM_ROOT = os.path.expanduser("~/.config/OrcaSlicer/system")


def active_profiles():
    """Active profile folder first, then any other that already holds presets."""
    profiles = []
    try:
        app = json.load(open(CONF)).get("app", {})
        folder = app.get("preset_folder") or "default"
        profiles.append(folder)
    except Exception:
        profiles.append("default")
    for d in sorted(glob.glob(os.path.join(USER_ROOT, "*"))):
        name = os.path.basename(d)
        if os.path.isdir(os.path.join(d, "filament")) and name not in profiles:
            profiles.append(name)
    return profiles


def parent_setting_id(preset):
    """setting_id of the system preset this one inherits, for the .info base_id."""
    parent = preset.get("inherits")
    if not parent:
        return ""
    for path in glob.glob(os.path.join(SYSTEM_ROOT, "*", "filament", "*.json")):
        if os.path.basename(path)[:-5] == parent:
            try:
                return json.load(open(path)).get("setting_id", "") or ""
            except Exception:
                return ""
    return ""


def write_info(path, profile, base_id):
    """Write the companion .info, always bumping updated_time to now.

    Orca compares this timestamp against the cloud copy at startup and keeps
    whichever is newer. Both previous behaviours lost to the cloud: a new .info
    was written with updated_time = 0, and an existing one was left untouched,
    so a preset installed here kept whatever timestamp it had last time. Either
    way Orca decided the cloud was at least as fresh and overwrote the values
    this script had just installed -- silently, on the next launch.

    Fields Orca owns are preserved when the file already exists. setting_id
    especially: rewriting it makes Orca treat this as a different preset and
    duplicate it in the GUI.
    """
    fields = {
        "sync_info": "",
        "user_id": "" if profile == "default" else profile,
        "setting_id": "",
        "base_id": base_id,
    }
    order = list(fields)
    if os.path.exists(path):
        for line in open(path):
            key, sep, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if not sep or key == "updated_time":
                continue
            if key not in fields:
                order.append(key)
            fields[key] = value

    fields["updated_time"] = str(int(time.time()))
    order.append("updated_time")
    with open(path, "w") as fh:
        for key in order:
            fh.write(f"{key} = {fields[key]}\n")


def main(argv):
    srcs = sorted(glob.glob(argv[0] if argv else "profiles/orca/*.json"))
    if not srcs:
        print("no presets to install", file=sys.stderr)
        return 1

    profiles = active_profiles()
    print(f"  active Orca profile: {profiles[0]}"
          + (f"  (also mirroring to: {', '.join(profiles[1:])})" if len(profiles) > 1 else ""))

    for src in srcs:
        preset = json.load(open(src))
        name = os.path.basename(src)[:-5]
        base_id = parent_setting_id(preset)

        for profile in profiles:
            dest_dir = os.path.join(USER_ROOT, profile, "filament")
            os.makedirs(dest_dir, exist_ok=True)
            with open(os.path.join(dest_dir, name + ".json"), "w") as fh:
                json.dump(preset, fh, indent=1, sort_keys=True)
            write_info(os.path.join(dest_dir, name + ".info"), profile, base_id)
        print(f"  installed: {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
