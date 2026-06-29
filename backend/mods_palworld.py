import os
import mods
import mods_common
import mods_archive
from registry import ModInfo, GameProfile
import decky
import utils
from install_txn import _StagedInstall


# ── Palworld (Nexus) mods ─────────────────────────────────────────────────────
# Palworld Nexus archives come in three shapes, routed to different game subdirs:
#   A) full Pal/ tree   — files under a Binaries/ or Content/ segment -> merged into the game's Pal/
#                         (e.g. a UE4SS Lua mod + its LogicMods .pak shipped together).
#   B) bare pak(s)      — loose .pak/.ucas/.utoc -> Pal/Content/Paks/~mods/.
#   C) loose UE4SS mod  — enabled.txt / Scripts/ / *.lua / dlls/ at the root, no Pal structure ->
#                         Pal/Binaries/Win64/Mods/<ModReference>/ (UE4SS auto-loads a folder with
#                         enabled.txt). The folder name comes from a single wrapper dir, else the
#                         mod's catalog filename.
# Every placed file is tracked per-file, so the natives-style toggle (.disabled rename of paks +
# enabled.txt) and the generic paths-based uninstall both act on it without new machinery.
_PALWORLD_PAK_EXTS = (".pak", ".ucas", ".utoc")
_PALWORLD_PAKS_DIR = os.path.join("Pal", "Content", "Paks", "~mods")
# RE-UE4SS 3.x (the Okaetsu Palworld build) LOADS Lua/C++ mods from Pal/Binaries/Win64/ue4ss/Mods/ —
# confirmed: DekMCM (the Mod Config Menu), itself a Lua mod, only works when placed there. Older
# archives — and UE4SS 2.x — target the bare Win64/Mods/, so a mod placed there installs but never
# loads; we remap it (see _pw_remap_ue4ss). Separately, DekMCM (once loaded) READS each mod's
# `modconfig.json` from the FILESYSTEM paths Content/Paks/LogicMods/ and Win64/Mods/<mod>/ — so a
# blueprint mod's loose LogicMods/<name>.modconfig.json must be kept (see the loose-root branch),
# else the mod is absent from the config menu.
_PALWORLD_UE4SS_MODS_DIR = os.path.join("Pal", "Binaries", "Win64", "ue4ss", "Mods")


def _pw_remap_ue4ss(parts: "list[str]") -> "list[str]":
    """Remap a re-rooted Binaries/Win64/Mods/... -> Binaries/Win64/ue4ss/Mods/... so a legacy archive
    (UE4SS-2.x layout, e.g. DekMCM) lands where RE-UE4SS 3.x scans for Lua mods. A path already under
    ue4ss/Mods/ (a current mod, e.g. PalSchema) is left unchanged."""
    if [p.lower() for p in parts[:3]] == ["binaries", "win64", "mods"]:
        return parts[:2] + ["ue4ss"] + parts[2:]
    return parts
# The Deck's filesystem (and Proton's view of it) is case-sensitive, while the engine/UE4SS scan
# fixed-cased dirs (Content/Paks/, Binaries/Win64/Mods/). An archive shipping a lower/odd-cased
# segment (`content/`, `binaries/`) would otherwise land in a dir nothing reads, so the structural
# segments are pinned to canonical casing (mirrors the natives merge canonicalizing its top dir).
# Free-form leaves (mod folder names, .pak basenames) aren't in the table, so they pass through.
_PW_CANON = {"binaries": "Binaries", "win64": "Win64", "content": "Content", "paks": "Paks",
             "mods": "Mods", "logicmods": "LogicMods", "scripts": "Scripts", "dlls": "dlls"}

# PalSchema (Nexus 2361) is a UE4SS data-mod loader: a data mod is a plain folder of JSON under
# Pal/Binaries/Win64/ue4ss/Mods/PalSchema/mods/<ModName>/, with files sorted into recognized
# category subdirs (PalSchema scans these names; verified against okaetsu.github.io/PalSchema docs
# + real collection mods). NOTE the dir is lowercase `mods` — distinct from UE4SS's own `Mods`, and
# the case-sensitive Deck FS won't match it if recased (see _pw_canon_tail).
_PALSCHEMA_DIRS = {"blueprints", "raw", "items", "appearance", "pals", "skins", "translations"}
_PALSCHEMA_MODS_DIR = os.path.join(_PALWORLD_UE4SS_MODS_DIR, "PalSchema", "mods")


def _pw_canon_tail(parts: "list[str]") -> "list[str]":
    """Canonicalize only the LEADING run of structural UE dir segments (binaries/win64/content/paks/
    mods/…) to fixed casing, stopping at the first non-structural (free-form) segment. Critical: a
    deeper `mods` belonging to PalSchema (…/ue4ss/Mods/PalSchema/mods/<name>/) must stay lowercase —
    blanket-recasing every `mods` to `Mods` sent it to a dir PalSchema never scans on the
    case-sensitive Deck FS. Stopping at the first free-form segment (e.g. `ue4ss`, a mod name) leaves
    everything past the structural prefix at its original (already-correct) casing."""
    out, structural = [], True
    for p in parts:
        if structural and p.lower() in _PW_CANON:
            out.append(_PW_CANON[p.lower()])
        else:
            structural = False
            out.append(p)
    return out


def _pw_is_palschema(rel: str) -> bool:
    """A PalSchema data file: a .json/.jsonc under one of PalSchema's recognized category subdirs
    (blueprints/raw/items/…). The category marker + JSON extension together avoid misclassifying an
    unrelated `raw`/`items` folder of binaries as PalSchema content."""
    if not rel.lower().endswith((".json", ".jsonc")):
        return False
    return any(seg in _PALSCHEMA_DIRS for seg in (p.lower() for p in rel.split("/")))


def _pw_palschema_placements(files: "list[tuple[str, str]]", mod: ModInfo) -> "list[tuple[str, str]]":
    """Place a loose PalSchema data mod's JSON under Pal/Binaries/Win64/ue4ss/Mods/PalSchema/mods/
    <ModName>/<category>/…. ModName comes from a single shared wrapper dir (the common case — the
    archive wraps everything in one folder), else the mod's catalog filename. Each file is re-rooted
    from its category-marker segment on, so a wrapper named oddly (or version-suffixed) is normalized
    away. `files` must already be the PalSchema subset (see _pw_is_palschema)."""
    wrappers = {rel.split("/")[0] for _ab, rel in files
                if "/" in rel and rel.split("/")[0].lower() not in _PALSCHEMA_DIRS}
    modname = mods_archive._safe_folder_name(next(iter(wrappers)) if len(wrappers) == 1 else mod.filename)
    out: list[tuple[str, str]] = []
    for ab, rel in files:
        segs = [p.lower() for p in rel.split("/")]
        mi = next(i for i, s in enumerate(segs) if s in _PALSCHEMA_DIRS)
        out.append((ab, os.path.join(_PALSCHEMA_MODS_DIR, modname, *rel.split("/")[mi:])))
    return out


def _pw_pak_dest(rel: str) -> str:
    """A loose pak's Content/Paks/ destination, basename-flattened with the pak EXTENSION lowercased
    (UE discovers paks with a case-sensitive `*.pak` glob, so an uppercase `.PAK` wouldn't load); the
    stem is preserved. A pak shipped under a `LogicMods/` segment is a BLUEPRINT mod — UE4SS's
    BPModLoaderMod only scans Pal/Content/Paks/LogicMods/, so it must land there, not in ~mods/."""
    stem, ext = os.path.splitext(os.path.basename(rel))
    if ext.lower() in _PALWORLD_PAK_EXTS:
        ext = ext.lower()
    subdir = "LogicMods" if "logicmods" in [p.lower() for p in rel.split("/")] else "~mods"
    return os.path.join("Pal", "Content", "Paks", subdir, stem + ext)


def _pw_is_lua(rel: str) -> bool:
    """A UE4SS Lua/C++ mod marker: enabled.txt / main.lua / any *.lua / a Scripts|dlls path segment."""
    segs = [p.lower() for p in rel.split("/")]
    return (os.path.basename(rel).lower() in ("enabled.txt", "main.lua")
            or rel.lower().endswith(".lua") or "scripts" in segs or "dlls" in segs)


def _pw_lua_placements(files: "list[tuple[str, str]]", mod: ModInfo) -> "list[tuple[str, str]]":
    """Place a loose UE4SS Lua/C++ mod's files under Pal/Binaries/Win64/ue4ss/Mods/<ModName>/ (where
    RE-UE4SS 3.x loads them). ModName comes from a single wrapper dir, else the mod's catalog filename.
    `files` must already exclude paks."""
    top_dirs = {rel.split("/")[0] for _ab, rel in files if "/" in rel}
    top_files = {rel for _ab, rel in files if "/" not in rel}
    if len(top_dirs) == 1 and not top_files and not any(d.lower() in ("scripts", "dlls") for d in top_dirs):
        root_dir = next(iter(top_dirs))
        modname, prefix = mods_archive._safe_folder_name(root_dir), root_dir + "/"
    else:
        modname, prefix = mods_archive._safe_folder_name(mod.filename), ""
    out: list[tuple[str, str]] = []
    for ab, rel in files:
        if prefix and not rel.startswith(prefix):
            continue  # stray file beside the wrapper dir
        sub = rel[len(prefix):] if prefix else rel
        out.append((ab, os.path.join(_PALWORLD_UE4SS_MODS_DIR, modname, *sub.split("/"))))
    return out


def _palworld_placements(extract_root: str, mod: ModInfo) -> "list[tuple[str, str]] | None":
    """Classify an extracted Palworld mod archive (shapes A/B/C above) and return the
    (staged-source-abs, install-dir-relative-dest) placements, or None when nothing installable is
    found. Pure path logic over the extracted tree so it's unit-testable. Shapes B and C are NOT
    mutually exclusive — a loose pak can ship alongside a loose UE4SS mod (e.g. a LogicMods pak + its
    config script), so both halves are placed rather than one silently dropped."""
    files: list[tuple[str, str]] = []
    for root, _dirs, names in os.walk(extract_root):
        for fn in names:
            ab = os.path.join(root, fn)
            rel = os.path.relpath(ab, extract_root).replace("\\", "/")
            if not mods_archive._is_archive_junk(rel):
                files.append((ab, rel))
    if not files:
        return None

    def has_seg(rel: str, seg: str) -> bool:
        return seg in [p.lower() for p in rel.split("/")]

    def is_pak(rel: str) -> bool:
        return rel.lower().endswith(_PALWORLD_PAK_EXTS)

    # Shape A — structured Pal mod: any file under a Binaries/ or Content/ segment. Cut each path to
    # that segment and re-root it under Pal/ (canonicalizing the standard UE dir casing, and remapping
    # a legacy Win64/Mods/ Lua path to ue4ss/Mods/) so files self-locate. A loose pak shipped alongside
    # the tree still goes to ~mods/; genuine strays (a root readme) are dropped.
    if any(has_seg(rel, "binaries") or has_seg(rel, "content") for _ab, rel in files):
        out: list[tuple[str, str]] = []
        for ab, rel in files:
            parts = rel.split("/")
            lparts = [p.lower() for p in parts]
            idxs = [lparts.index(s) for s in ("binaries", "content") if s in lparts]
            if idxs:
                tail = _pw_remap_ue4ss(_pw_canon_tail(parts[min(idxs):]))
                out.append((ab, os.path.join("Pal", *tail)))
            elif is_pak(rel):
                out.append((ab, _pw_pak_dest(rel)))
        return out or None

    # Loose-root archive (no Binaries/Content wrapper). Route each file:
    #  - a PalSchema data mod (JSON under blueprints/raw/items/… ) -> ue4ss/Mods/PalSchema/mods/<Name>/
    #    (shape D — a curated collection staple; e.g. True Monster Rancher, VC_Merchant).
    #  - under a LogicMods/ or ~mods/ segment -> Content/Paks/<that>/<rest>, KEEPING a pak's companion
    #    files next to it — a blueprint mod ships its pak AND its <name>.modconfig.json (+ a preview
    #    .png) loose in LogicMods/, and DekMCM reads that modconfig.json from Content/Paks/LogicMods/.
    #  - else a bare pak -> Content/Paks/~mods/.
    #  - else part of a loose UE4SS Lua/C++ mod -> ue4ss/Mods/<ModName>/ (shape C).
    out: list[tuple[str, str]] = []
    ps_files = [(ab, rel) for ab, rel in files if _pw_is_palschema(rel)]
    if ps_files:
        out += _pw_palschema_placements(ps_files, mod)
        files = [(ab, rel) for ab, rel in files if not _pw_is_palschema(rel)]
    leftover: list[tuple[str, str]] = []
    for ab, rel in files:
        parts = rel.split("/")
        segs = [p.lower() for p in parts]
        if "logicmods" in segs:
            out.append((ab, os.path.join("Pal", "Content", "Paks", "LogicMods", *parts[segs.index("logicmods") + 1:])))
        elif "~mods" in segs:
            out.append((ab, os.path.join("Pal", "Content", "Paks", "~mods", *parts[segs.index("~mods") + 1:])))
        elif is_pak(rel):
            out.append((ab, _pw_pak_dest(rel)))
        else:
            leftover.append((ab, rel))
    if any(_pw_is_lua(rel) for _ab, rel in leftover):
        out += _pw_lua_placements(leftover, mod)
    return out or None


def _palworld_commit(install_dir: str, mods_path: str, mod: ModInfo, version: str | None,
                     placements: "list[tuple[str, str]] | None", staging: str) -> bool:
    """Stage `placements` [(src_abs, dest_rel)] and commit all-or-nothing into the game tree, retiring
    the prior install (active + .disabled forms). On a dest collision (multi-file installs) the last
    file wins. A displaced stock game file is preserved as *.moddy-orig. Records the mod with its
    tracked paths. The caller owns the extract/staging dir lifecycle."""
    import shutil
    if not placements:
        decky.logger.error(f"{mod.name}: no installable Palworld content found — refusing to install")
        return False
    old_paths = (mods._load_store().get(mod.id) or {}).get("paths") or []
    by_dest: dict[str, str] = {}
    for src, dest_rel in placements:
        by_dest[dest_rel] = src  # last file wins on a collision
    staged: list[tuple[str, str]] = []
    for dest_rel, src in by_dest.items():
        staged_abs = os.path.join(staging, dest_rel)
        os.makedirs(os.path.dirname(staged_abs), exist_ok=True)
        shutil.copyfile(src, staged_abs)
        staged.append((staged_abs, dest_rel))
    placed: list[str] = []
    is_foreign = mods_common._overwrite_guard(install_dir, mods_path, mod, [d for _s, d in staged])
    with _StagedInstall(install_dir, is_foreign=is_foreign) as txn:
        for p in old_paths:
            txn.retire(p)
        for staged_abs, dest_rel in staged:
            txn.place(staged_abs, dest_rel)
            placed.append(dest_rel)
    mods.set_installed_record(mod.id, version or "latest", mod.filename, paths=placed, mod=mod)
    decky.logger.info(f"Installed {mod.name} ({version or 'latest'}) — {len(placed)} file(s)")
    return True


async def _install_mod_zip_palworld(game: GameProfile, install_dir: str, mods_path: str, mod: ModInfo, version: str | None, url: str | None) -> bool | None:
    """Install a Palworld (Nexus) mod: download, extract (.zip/.7z/.rar), classify it into one of the
    three shapes (see _palworld_placements), and place each file at its game-relative destination,
    all-or-nothing. Per-file tracking lets the natives-style toggle and generic uninstall handle it."""
    import shutil
    tmp_archive = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{mod.filename}_tmp.archive")
    tmp_extract = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{mod.filename}_extract")
    staging = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{mod.filename}_pw_staging")
    for p in (tmp_extract, staging):
        if os.path.exists(p):
            shutil.rmtree(p)
    try:
        decky.logger.info(f"Downloading {mod.name} from {utils.redact_url(url)}")
        await utils.download(url, tmp_archive, game.appid)
        mods_archive.extract_archive(tmp_archive, tmp_extract)
        return _palworld_commit(install_dir, mods_path, mod, version,
                                _palworld_placements(tmp_extract, mod), staging)
    except utils.InstallCancelledError:
        decky.logger.info(f"Install of {mod.name} was cancelled")
        return None
    except Exception as e:
        decky.logger.error(f"Failed to install {mod.name}: {e}")
        return False
    finally:
        if os.path.exists(tmp_archive):
            os.remove(tmp_archive)
        for p in (tmp_extract, staging):
            if os.path.exists(p):
                shutil.rmtree(p)


async def install_palworld_files(game: GameProfile, install_dir: str, mod: ModInfo, version: str | None, urls: list) -> bool | None:
    """Install MULTIPLE user-chosen Nexus files of one Palworld mod (the file-picker path) under a
    single record: each file is downloaded + extracted into its own subdir, classified via
    _palworld_placements, and all placements are committed together. Backs the version / Steam-variant
    / add-on picker. Returns True/False/None."""
    import shutil
    mods_path = mods.resolve_mods_path(game, install_dir)
    tmp_root = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{mod.filename}_pwmulti")
    staging = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{mod.filename}_pwmulti_staging")
    for p in (tmp_root, staging):
        if os.path.exists(p):
            shutil.rmtree(p)
    try:
        placements: list[tuple[str, str]] = []
        for i, url in enumerate(urls):
            arch = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{mod.filename}_{i}.archive")
            ext = os.path.join(tmp_root, str(i))
            try:
                decky.logger.info(f"Downloading {mod.name} file {i + 1}/{len(urls)} from {utils.redact_url(url)}")
                await utils.download(url, arch, game.appid)
                mods_archive.extract_archive(arch, ext)
                placements += (_palworld_placements(ext, mod) or [])
            finally:
                if os.path.exists(arch):
                    os.remove(arch)
        return _palworld_commit(install_dir, mods_path, mod, version, placements, staging)
    except utils.InstallCancelledError:
        decky.logger.info(f"Install of {mod.name} was cancelled")
        return None
    except Exception as e:
        decky.logger.error(f"Failed to install {mod.name}: {e}")
        return False
    finally:
        for p in (tmp_root, staging):
            if os.path.exists(p):
                shutil.rmtree(p)
