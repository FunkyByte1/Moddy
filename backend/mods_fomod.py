"""Bridge between the pure FOMOD engine (fomod.py) and the loose-file installer.

The engine is game-agnostic and does no I/O; this module is the side-effecting glue: find a mod's
fomod/ModuleConfig.xml, resolve it under DEFAULT options (the v1 'auto-apply defaults' behaviour —
a manual wizard comes later), and materialise the chosen files into a staging tree shaped like the
mod's logical root. The caller (_install_mod_loose_merge) then treats that tree exactly like an
ordinary extracted payload, so all the existing merge / per-file tracking / .moddy-orig backup /
toggle machinery is reused unchanged.

FOMOD detection takes PRECEDENCE over the folder-variant heuristic (_detect_variants): a real FOMOD's
option folders (00 Core / 01 Legiana / …) are NOT mutually-exclusive variants — Core is required —
so guessing one folder silently drops required files. Resolving the FOMOD installs the correct set.
"""
import json
import os
import shutil

import decky

import fomod

# Sentinel `selections_json` meaning "resolve under engine defaults, don't park" — used for a FOMOD
# pulled in as a same-domain dependency, which can't prompt the user mid-cascade.
FOMOD_DEFAULTS = "__moddy_fomod_defaults__"


def find_config(extract_dir: str) -> "str | None":
    """Locate fomod/ModuleConfig.xml within an extracted archive, case-insensitively on both the
    `fomod` directory and the file name (FOMOD authors capitalise inconsistently). Returns the path,
    or None if this archive is not a FOMOD."""
    for root, _dirs, files in os.walk(extract_dir):
        if os.path.basename(root).lower() == "fomod":
            for fn in files:
                if fn.lower() == "moduleconfig.xml":
                    return os.path.join(root, fn)
    return None


def _resolve_ci(base: str, rel: str) -> "str | None":
    """Resolve a '/'-separated FOMOD relative path against `base` case-insensitively (FOMOD paths
    are case-insensitive; the Deck filesystem is case-sensitive, so a `Armors\\…` source referenced
    as `armors/…` wouldn't be found by a plain join). Returns the real on-disk path or None."""
    cur = base
    for seg in rel.split("/"):
        if not seg or seg == ".":
            continue
        try:
            entries = os.listdir(cur)
        except OSError:
            return None
        match = next((e for e in entries if e.lower() == seg.lower()), None)
        if match is None:
            return None
        cur = os.path.join(cur, match)
    return cur


def _load_model(cfg_path: str, mod_name: str):
    """Parse the FOMOD; return the model, or None to fall back to legacy variant handling (parse
    error, or constructs the engine can't evaluate — fail loud, don't guess)."""
    try:
        with open(cfg_path, "rb") as f:
            model = fomod.parse(f.read())
    except (fomod.FomodError, OSError) as e:
        decky.logger.warning(f"{mod_name}: FOMOD parse failed ({e}); falling back to variant handling")
        return None
    if model.unsupported:
        decky.logger.warning(
            f"{mod_name}: FOMOD uses unsupported constructs {sorted(model.unsupported)}; "
            "falling back to variant handling")
        return None
    return model


def _materialize(plan, pkg_root: str, extract_dir: str, mod_name: str) -> "str | None":
    """Copy a resolved plan's ops into a fresh staging dir (sibling of extract_dir), shaped like the
    mod's logical root. Returns the staging path, or None if nothing landed (caller falls back).

    `<folder>` copies the source's CONTENTS into the destination (FOMOD semantics); ops are applied
    in priority order so a later op overwrites an earlier one on a path clash. Sources resolve
    case-insensitively against the PACKAGE ROOT (the dir containing fomod/)."""
    staging = extract_dir.rstrip("/") + "_fomod"
    if os.path.exists(staging):
        shutil.rmtree(staging)
    os.makedirs(staging, exist_ok=True)

    placed = 0
    missing: list[str] = []
    for op in plan.operations:
        src = _resolve_ci(pkg_root, op.source)
        if src is None or not os.path.exists(src):
            missing.append(op.source)
            continue
        dest = os.path.normpath(os.path.join(staging, *[s for s in op.destination.split("/") if s]))
        if dest != staging and not dest.startswith(staging + os.sep):
            decky.logger.warning(f"{mod_name}: FOMOD destination escapes staging, skipped: {op.destination!r}")
            continue
        if op.is_folder:
            if os.path.isdir(src):
                shutil.copytree(src, dest, dirs_exist_ok=True)  # later op overwrites earlier
                placed += 1
            else:
                missing.append(op.source)
        else:
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(src, os.path.join(dest, os.path.basename(src)))
            placed += 1

    if missing:
        decky.logger.warning(
            f"{mod_name}: FOMOD referenced {len(missing)} path(s) not found in the archive "
            f"(e.g. {missing[:3]})")
    if placed == 0:
        decky.logger.error(f"{mod_name}: FOMOD resolved to no installable files; falling back")
        shutil.rmtree(staging, ignore_errors=True)
        return None
    decky.logger.info(f"{mod_name}: FOMOD staged {placed} payload op(s)")
    return staging


def prepare(extract_dir: str, cfg_path: str, mod_name: str, selections_json: "str | None"):
    """Drive a FOMOD install. Returns one of:
      - dict {"needs_fomod": True, ...} : park for the wizard (the model has real choices and the
        caller passed no selections yet) — the caller surfaces it to the UI like a variant park;
      - str : the staging dir to install (resolved under defaults, or under the wizard selections);
      - None : fall back to legacy variant handling (not auto-resolvable).

    `selections_json` is None on the first pass (park or default-install) and, on resume, the JSON
    the wizard sent back through the same channel as the variant id."""
    model = _load_model(cfg_path, mod_name)
    if model is None:
        return None

    if selections_json is None:
        if fomod.has_choices(model):
            decky.logger.info(f"{mod_name}: FOMOD has options — parking for the install wizard")
            return {"needs_fomod": True, "fomod": fomod.serialize_for_ui(model)}
        selections = fomod.default_selections(model)
    elif selections_json == FOMOD_DEFAULTS:
        selections = fomod.default_selections(model)
    else:
        try:
            selections = fomod.decode_selections(json.loads(selections_json))
        except (ValueError, TypeError, KeyError, IndexError) as e:
            decky.logger.warning(f"{mod_name}: bad FOMOD selections ({e}); using defaults")
            selections = fomod.default_selections(model)

    try:
        plan = fomod.resolve(model, selections)
    except fomod.FomodError as e:
        decky.logger.warning(f"{mod_name}: FOMOD resolve failed ({e}); falling back to variant handling")
        return None
    pkg_root = os.path.dirname(os.path.dirname(cfg_path))  # the dir that contains the fomod/ folder
    return _materialize(plan, pkg_root, extract_dir, mod_name)
