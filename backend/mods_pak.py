import os
import re
import decky
import mods


# re_chunk_000.pak.patch_NNN.pak  (groups: prefix, number, ".pak", optional ".disabled")
_PAK_PATCH_RE = re.compile(r"^(re_chunk_000\.pak\.patch_)(\d+)(\.pak)(\.disabled)?$", re.IGNORECASE)


def _next_pak_slot(install_dir: str) -> int:
    """Lowest unused re_chunk patch number above every existing one. RE4 loads
    `re_chunk_000.pak.patch_NNN.pak` in order with higher numbers overriding lower; the base
    game occupies the low numbers, so a mod pak must sit above the highest present. Counts
    `.disabled` mod paks too, so a disabled mod's slot isn't handed to another mod. Returns
    max(existing)+1 (1 if somehow none exist)."""
    highest = 0
    try:
        for name in os.listdir(install_dir):
            m = _PAK_PATCH_RE.match(name)
            if m:
                highest = max(highest, int(m.group(2)))
    except Exception:
        pass
    return highest + 1


def _renumber_pak_mods(install_dir: str) -> None:
    """Keep Moddy's RE4 `.pak` mods packed contiguously right above the base game's paks, so a
    gap left by uninstalling/disabling one can't stop the engine loading the rest. Preserves
    their relative order — which is load priority (a higher patch number overrides a lower one),
    matching authors' "install this after other X mods" guidance — renaming files and updating
    each owning record's `paths` in place. A no-op when already contiguous.

    A pak is "Moddy's" iff some installed record lists it; everything else at patch_NNN is the
    base game, whose highest number is the ceiling we pack above."""
    store = mods._load_store()

    # active basename -> owning mod_id, for every pak any record claims.
    owner_of: dict[str, str] = {}
    for mod_id, rec in store.items():
        for p in (rec.get("paths") or []):
            base = os.path.basename(p)
            if _PAK_PATCH_RE.match(base):
                owner_of[base] = mod_id

    try:
        names = os.listdir(install_dir)
    except Exception:
        return

    ceiling = 0
    mod_paks = []  # (current_num, on_disk_name, disabled, owner_id, active_basename)
    for name in names:
        m = _PAK_PATCH_RE.match(name)
        if not m:
            continue
        num, disabled = int(m.group(2)), bool(m.group(4))
        active_base = m.group(1) + m.group(2) + m.group(3)
        owner = owner_of.get(active_base)
        if owner is None:
            if not disabled:
                ceiling = max(ceiling, num)  # a base-game pak
        else:
            mod_paks.append((num, name, disabled, owner, active_base))

    # Compact downward in ascending order (each target slot is freed before it's needed).
    mod_paks.sort(key=lambda t: t[0])
    target = ceiling
    changed = False
    for _num, name, disabled, owner, active_base in mod_paks:
        target += 1
        new_active = f"re_chunk_000.pak.patch_{target:03d}.pak"
        new_name = new_active + (".disabled" if disabled else "")
        if new_name == name:
            continue
        try:
            os.rename(os.path.join(install_dir, name), os.path.join(install_dir, new_name))
        except Exception as e:
            decky.logger.error(f"pak renumber: failed to rename {name} -> {new_name}: {e}")
            continue
        rec = store.get(owner)
        if rec and rec.get("paths"):
            rec["paths"] = [new_active if os.path.basename(p) == active_base else p for p in rec["paths"]]
        changed = True
        decky.logger.info(f"pak renumber: {name} -> {new_name}")
    if changed:
        mods._save_store(store)
