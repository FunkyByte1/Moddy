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


def _find_bin(*names: str) -> str | None:
    """Resolve the first of `names` to an executable path, falling back to /usr/bin (PATH may be
    sparse under Steam's launch env)."""
    import shutil as _sh
    for n in names:
        found = _sh.which(n)
        if found:
            return found
    for n in names:
        cand = os.path.join("/usr/bin", n)
        if os.path.isfile(cand):
            return cand
    return None


def _extractors_for(magic: bytes, archive_path: str, dest_dir: str) -> list[tuple[str, list]]:
    """Ordered (binary, argv) extractor candidates for a non-zip archive, by magic bytes.

    RAR (`Rar!`, both v4 and v5) is the important case. `7z` is tried first — on SteamOS (the
    device target) its build includes the RAR codec and is the reference-quality RAR reader, so it
    stays the production path. But several *desktop* distro builds ship `7z` WITHOUT the RAR codec
    (e.g. Fedora strips it for licensing); there it exits cleanly with "Cannot open the file as
    archive" and we fall through to `bsdtar` (libarchive, near-universal, reads RAR5) and then the
    dedicated `unrar`/`unar`, using whichever is present and succeeds. `.7z` and unknown payloads
    stay 7z-first (its native format) with bsdtar as a safety net."""
    sevenzip = _find_bin("7z", "7zz", "7za", "7zr")
    bsdtar = _find_bin("bsdtar")
    unar = _find_bin("unar")
    unrar = _find_bin("unrar")
    is_rar = magic[:5] == b"Rar!\x1a"
    candidates: list[tuple[str | None, list]] = []

    def sevenz(b):
        return (b, [b, "x", "-y", f"-o{dest_dir}", archive_path])

    def tar(b):
        return (b, [b, "-x", "-f", archive_path, "-C", dest_dir])

    if is_rar:
        if sevenzip:
            candidates.append(sevenz(sevenzip))
        if bsdtar:
            candidates.append(tar(bsdtar))
        if unrar:
            candidates.append((unrar, [unrar, "x", "-y", archive_path, dest_dir + os.sep]))
        if unar:
            candidates.append((unar, [unar, "-quiet", "-force-overwrite", "-no-directory",
                                      "-output-directory", dest_dir, archive_path]))
    else:
        if sevenzip:
            candidates.append(sevenz(sevenzip))
        if bsdtar:
            candidates.append(tar(bsdtar))
    return [c for c in candidates if c[0]]


def extract_archive(archive_path: str, dest_dir: str) -> None:
    """Extract a mod archive into dest_dir. RE4/MHW/Nexus mods ship as .zip, .7z, or .rar;
    Python's zipfile only handles zip, so 7z/rar are handed to a system extractor. Routes by magic
    bytes since the downloaded file may carry no extension, and tries several extractors in turn so
    a distro whose `7z` lacks the RAR codec still installs RAR mods. See _extractors_for."""
    import zipfile, subprocess
    os.makedirs(dest_dir, exist_ok=True)
    with open(archive_path, "rb") as f:
        magic = f.read(8)
    if magic[:2] == b"PK":
        with zipfile.ZipFile(archive_path, "r") as z:
            z.extractall(dest_dir)
        return

    candidates = _extractors_for(magic, archive_path, dest_dir)
    kind = "RAR" if magic[:5] == b"Rar!\x1a" else "7z/other"
    if not candidates:
        tools = "bsdtar, 7z, unar or unrar" if kind == "RAR" else "7z or bsdtar"
        raise Exception(f"no extractor found for {kind} archive — install one of: {tools}")
    errors: list[str] = []
    for binary, argv in candidates:
        result = subprocess.run(
            argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=_system_env(),
        )
        if result.returncode == 0:
            return
        name = os.path.basename(binary)
        errors.append(f"{name}: {result.stderr.decode(errors='replace').strip()[:160] or f'exit {result.returncode}'}")
    raise Exception(
        f"could not extract {kind} archive (tried {', '.join(os.path.basename(b) for b, _ in candidates)}): "
        + " | ".join(errors)
    )


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
