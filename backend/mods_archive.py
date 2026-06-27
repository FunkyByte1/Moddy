import os
import re
import decky


def _system_env() -> dict:
    """A copy of the environment with Steam's dynamic-linker overrides stripped, for shelling out to
    system binaries. Decky runs the plugin under Steam, which exports LD_LIBRARY_PATH/LD_PRELOAD
    pointing at Steam's bundled libs (an incompatible libreadline/libstdc++). A system binary like
    `7z` — or the `/bin/sh` it spawns — then dies with `symbol lookup error: … undefined symbol`
    (e.g. rl_trim_arg_from_keyseq from readline). Removing these lets the child resolve system libs."""
    return {k: v for k, v in os.environ.items() if k not in ("LD_LIBRARY_PATH", "LD_PRELOAD")}


def extract_archive(archive_path: str, dest_dir: str) -> None:
    """Extract a mod archive into dest_dir. RE4/MHW/Nexus mods ship as .zip, .7z, or .rar;
    Python's zipfile only handles zip, so 7z/rar are handed to the system `7z` (ships on
    SteamOS). Routes by magic bytes since the downloaded file may carry no extension."""
    import zipfile, subprocess
    import shutil as _sh
    os.makedirs(dest_dir, exist_ok=True)
    with open(archive_path, "rb") as f:
        magic = f.read(8)
    if magic[:2] == b"PK":
        with zipfile.ZipFile(archive_path, "r") as z:
            z.extractall(dest_dir)
        return
    sevenzip = _sh.which("7z") or _sh.which("7za") or _sh.which("7zz") or _sh.which("7zr")
    for cand in ("/usr/bin/7z", "/usr/bin/7zz", "/usr/bin/7za"):
        if not sevenzip and os.path.isfile(cand):
            sevenzip = cand
    if not sevenzip:
        raise Exception("system 7z not found — cannot extract a .7z/.rar mod archive")
    result = subprocess.run(
        [sevenzip, "x", "-y", f"-o{dest_dir}", archive_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=_system_env(),
    )
    if result.returncode != 0:
        raise Exception(f"7z failed: {result.stderr.decode(errors='replace')[:200]}")


def _is_archive_junk(rel: str) -> bool:
    """macOS zip cruft that must never be placed into a mod folder or counted when deciding whether
    a single wrapper folder should be stripped: the `__MACOSX/` metadata tree, `.DS_Store`, and
    AppleDouble `._*` resource forks. Nexus archives zipped on macOS routinely carry these."""
    parts = rel.replace("\\", "/").split("/")
    if "__MACOSX" in parts:
        return True
    base = parts[-1]
    return base == ".DS_Store" or base.startswith("._")


def _safe_folder_name(name: str) -> str:
    """A filesystem-safe Mods/ subfolder name derived from a mod's name, for the rare SMAPI
    archive that ships manifest.json at its root with no containing folder. Strips path separators
    and a leading dot (a leading dot would mark the folder disabled to SMAPI)."""
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", name).strip().lstrip(".")
    return cleaned or "Mod"


def _detect_variants(extract_dir: str) -> list[dict]:
    """List the selectable payloads in an extracted loose-file (zip_natives / zip_nativepc) mod
    archive. A payload is a directory that directly holds a `.pak`, or that contains a `natives/`
    (RE4) or `nativePC/` (MHW) subtree. Most mods have exactly one; some bundle several
    mutually-exclusive options the user must choose between (e.g. RE4's "Max Stack Sizes" ships 21
    `.pak` variants — 0999/9999/x02…, each in its own folder with a modinfo.ini). Returns
    [{"id": <path relative to extract_dir>, "label": <folder name>}], sorted; 0 or 1 entries means
    no choice is needed."""
    payload_dirs: set[str] = set()
    for root, dirs, files in os.walk(extract_dir):
        in_natives = (os.sep + "natives" + os.sep) in (root + os.sep).lower()
        if not in_natives and any(f.lower().endswith(".pak") for f in files):
            payload_dirs.add(root)              # a folder holding a .pak
        for d in dirs:
            if d.lower() in ("natives", "nativepc"):
                payload_dirs.add(root)          # the parent of a natives/ or nativePC/ tree
    variants = []
    for d in sorted(payload_dirs):
        rel = os.path.relpath(d, extract_dir)
        variants.append({"id": rel, "label": os.path.basename(d) if rel != "." else "(default)"})
    return variants


# Files that are mod-manager metadata / documentation rather than game assets — skipped when
# wrapping a Fluffy-packaged mod (no nativePC/ folder) into the loader's folder.
_LOOSE_METADATA_NAMES = {"modinfo.ini", "desktop.ini", "thumbs.db"}
_LOOSE_METADATA_EXTS = {".txt", ".md", ".url", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".pdf", ".html"}

# Top-level folder names that appear directly inside MHW's nativePC/. Used to tell a real content
# folder (keep it — `pl/…` must become `nativePC/pl/…`) from a "<Mod Name>/" wrapper folder (descend
# into it) when a Fluffy archive has a single top-level dir. Stracker plugins live in nativePC/plugins.
_MHW_NATIVEPC_DIRS = {
    "pl", "npc", "em", "common", "stage", "ui", "gui", "vfx", "sound", "se", "wp", "facial",
    "equip", "quest", "gm", "hm", "it", "id", "motion", "demo", "title", "map", "hit", "ce",
    "cs", "sm", "mc", "scaffold", "shell", "archon", "assets", "animation", "chunk", "stm",
    "plugins", "loader", "nativepc",
}


def _looks_like_nativepc_content(name: str) -> bool:
    return name.lower() in _MHW_NATIVEPC_DIRS


def _is_loose_metadata(rel: str) -> bool:
    """True for a wrap-loose archive entry that's mod-manager metadata or a preview/readme, not a
    game asset. Only top-level entries are screened (assets nested inside content folders, e.g. a
    `pl/.../foo.png` texture sidecar, are kept) — so this matches RE4's modinfo.ini/screenshot skip
    but is scoped to the archive root."""
    if os.sep in rel:
        return False  # nested file — part of the content tree, keep it
    name = os.path.basename(rel).lower()
    if name in _LOOSE_METADATA_NAMES:
        return True
    return os.path.splitext(name)[1] in _LOOSE_METADATA_EXTS


def _strip_loose_wrapper(search_root: str) -> str:
    """If the payload is entirely inside a single "<Mod Name>/" wrapper directory (e.g.
    "<Mod Name>/pl/…", with at most metadata files beside it), return that inner dir so the content
    isn't buried a level too deep. A lone top-level dir is only treated as a wrapper when its name
    is NOT a known nativePC content folder — otherwise `pl/…` (an armor mod touching only `pl`) would
    be wrongly stripped to `f_equip/…`. The Fluffy norm — content folders directly at the root next
    to modinfo.ini — has multiple dirs or a content-named dir, so it's returned unchanged."""
    try:
        entries = os.listdir(search_root)
    except OSError:
        return search_root
    dirs = [e for e in entries if os.path.isdir(os.path.join(search_root, e))]
    nonmeta_files = [e for e in entries if not os.path.isdir(os.path.join(search_root, e)) and not _is_loose_metadata(e)]
    if len(dirs) == 1 and not nonmeta_files and not _looks_like_nativepc_content(dirs[0]):
        return os.path.join(search_root, dirs[0])
    return search_root
