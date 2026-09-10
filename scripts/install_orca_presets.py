#!/usr/bin/env python3
"""Install filament presets into the profile folder OrcaSlicer is actually using.

Orca keeps user presets under ~/.config/OrcaSlicer/user/<profile>/filament/,
where <profile> is "default" when logged out but a Bambu account UUID when
logged in. The active one is named by `app.preset_folder` in OrcaSlicer.conf —
writing to the wrong one leaves the preset invisible in the GUI with no error.

Each preset also wants a companion ".info" file carrying sync metadata. We write
one with an empty sync_info so the preset stays local and is not pushed to the
user's Bambu cloud account.
"""
import glob
import json
import os
import sys

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
            info = os.path.join(dest_dir, name + ".info")
            if not os.path.exists(info):
                with open(info, "w") as fh:
                    fh.write(
                        "sync_info = \n"
                        f"user_id = {'' if profile == 'default' else profile}\n"
                        "setting_id = \n"
                        f"base_id = {base_id}\n"
                        "updated_time = 0\n"
                    )
        print(f"  installed: {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
