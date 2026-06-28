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
import os
import shutil

import decky

import fomod


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


def stage_default_install(extract_dir: str, cfg_path: str, mod_name: str) -> "str | None":
    """Resolve the FOMOD under default options and materialise the chosen files into a fresh staging
    dir (sibling of extract_dir). Returns the staging path for the caller to feed to the loose-file
    merge, or None to fall back to legacy variant handling — when the FOMOD uses constructs we can't
    evaluate, fails to parse/resolve, or resolves to nothing on disk.

    FOMOD `source` paths are relative to the PACKAGE ROOT (the dir containing fomod/), not the
    archive root. `<folder>` copies the source's CONTENTS into the destination (FOMOD semantics);
    operations are applied in priority order so a later op overwrites an earlier one on a path clash.
    """
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
    try:
        plan = fomod.resolve(model, fomod.default_selections(model))
    except fomod.FomodError as e:
        decky.logger.warning(f"{mod_name}: FOMOD resolve failed ({e}); falling back to variant handling")
        return None

    pkg_root = os.path.dirname(os.path.dirname(cfg_path))  # the dir that contains the fomod/ folder
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
    decky.logger.info(f"{mod_name}: FOMOD resolved {placed} payload op(s) under default options")
    return staging
