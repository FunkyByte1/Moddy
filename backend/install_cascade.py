"""Shared recursive mod-install cascade + per-venue providers.

The Thunderstore and Nexus installs were two near-identical recursive cascades living on the RPC
Plugin class (depth-first dependency install, skip-already-installed, denylist, rollback bookkeeping,
variant parking). They diverged only in venue specifics — id derivation, catalog lookup, dependency
resolution, ModInfo/URL construction, and a couple of policy knobs — yet had to be kept in sync by
hand. This module owns the ONE shared cascade (`run_cascade`) and the dependency-sizing pre-pass
(`collect_plan`); each venue supplies a `ModProvider` that fills in only the venue-specific bits.

A `ref` is whatever uniquely identifies a mod to its provider: a Thunderstore full_name string, or a
(domain, mod_id) tuple for Nexus. Providers translate a ref to the install id, the catalog item, its
dependency refs, and the concrete install (ModInfo + version + download URL).
"""
from dataclasses import dataclass

import decky

import registry
import mods
import mods_fomod
import thunderstore
import nexus
import ficsit
import download_queue

# Sentinel returned all the way up when a Nexus download is gated behind Premium (v1 can't serve
# free downloads). The frontend keys off this exact string to trigger the website nxm:// handoff.
PREMIUM_REQUIRED = "premium_required"


def _is_game_modloader(game, domain: str, mod_id) -> bool:
    """True if (domain, mod_id) is this game's modloader sourced from Nexus (e.g. MHW's Stracker's
    Loader = monsterhunterworld/1982). Such a Nexus requirement is the loader, not a mod, so the
    cascade skips it — it's installed/managed by the modloader system. Also matches a loader installed
    from elsewhere (e.g. SMAPI from GitHub) but referenced by its Nexus id via `nexus_skip_ids`."""
    game_domain = game.catalog.get("nexus_domain", "")
    for ml in game.modloaders:
        if ml.source.type == "nexus" and ml.source.nexus_domain == domain and str(ml.source.mod_id) == str(mod_id):
            return True
        if domain == game_domain and str(mod_id) in ml.nexus_skip_ids:
            return True
    return False


def _is_game_ficsit_modloader(game, mod_reference: str) -> bool:
    """True if `mod_reference` is this game's modloader sourced from ficsit (Satisfactory's SML).
    Every Satisfactory mod declares SML as a dependency, but SML is the loader — installed/managed
    by the modloader system — so the cascade skips it rather than installing it as a content mod."""
    for ml in game.modloaders:
        # Case-insensitive: ficsit mod_references are canonical, but a dependency could conceivably
        # reference the loader with drifted casing (e.g. "Sml") — still skip it as the loader.
        if ml.source.type == "ficsit" and ml.source.mod_reference.lower() == (mod_reference or "").lower():
            return True
    return False


@dataclass
class InstallSpec:
    """The concrete install a provider resolved for a ref: the ModInfo to hand to mods.install_mod,
    plus the version label and download URL."""
    mod: "registry.ModInfo"
    version: str
    url: str


class ModProvider:
    """Per-venue adapter for the shared cascade. Subclasses set `denylist` (lowercase install ids to
    skip) and `deps_fatal` (True: a failed dependency aborts the whole install — Thunderstore; False:
    best-effort, log + continue — Nexus), and implement the lookup/build hooks below. All hooks are
    synchronous; the cascade owns the async install/progress calls."""

    denylist: set
    deps_fatal: bool

    def key(self, ref) -> str:
        """ref -> the install id used for dedup, denylist, and presence checks (lowercased where the
        upstream id is case-insensitive)."""
        raise NotImplementedError

    def find(self, game, ref):
        """ref -> an opaque catalog/api item (consumed by dep_refs/build_install), or None if the mod
        can't be found. Called only when the mod isn't being skipped, so it may hit the network."""
        raise NotImplementedError

    def missing_result(self, ref, is_dependency: bool, allow_missing: bool) -> bool:
        """What the cascade returns when find() is None."""
        raise NotImplementedError

    def dep_refs(self, game, item, ref):
        """The dependency refs to recurse into, as (ref, label) pairs (label is a human name used in
        best-effort failure warnings). Already filtered to installable deps."""
        raise NotImplementedError

    def build_install(self, game, item, ref, version):
        """Resolve the concrete install: an InstallSpec, PREMIUM_REQUIRED, or None (which the cascade
        treats as a hard failure)."""
        raise NotImplementedError


class ThunderstoreProvider(ModProvider):
    deps_fatal = True  # a Thunderstore mod with a missing/failed dependency is incomplete -> abort

    def __init__(self, denylist: set):
        self.denylist = denylist

    def key(self, ref) -> str:
        return ref.lower()

    def find(self, game, ref):
        return thunderstore.find_package(game.thunderstore_community, ref)

    def missing_result(self, ref, is_dependency, allow_missing):
        # A dependency we can't find: skip it under "install anyway", else fail the cascade. The
        # top-level mod always fails if missing — you can't install what isn't there.
        if is_dependency and allow_missing:
            decky.logger.warning(f"Dependency {ref} not in catalog; skipping (install anyway)")
            return True
        decky.logger.error(f"Thunderstore package not found in catalog: {ref}")
        return False

    def dep_refs(self, game, item, ref):
        # Always install deps at the catalog's latest; the version pinned in a dep string is only the
        # minimum the parent was tested against. Implicit deps (declared per-game) cover runtime
        # requirements the Thunderstore manifest omits (e.g. RoR2 mods needing Newtonsoft.Json).
        explicit = []
        for dep_str in item.get("latest", {}).get("dependencies", []):
            parsed = thunderstore.parse_dep(dep_str)
            if not parsed:
                decky.logger.warning(f"Could not parse dep string '{dep_str}' for {ref}")
                continue
            explicit.append(parsed[0])
        return [(fn, fn) for fn in list(game.implicit_deps) + explicit]

    def build_install(self, game, item, ref, version):
        latest = item.get("latest", {})
        target_version = version or latest.get("version_number")
        if version:
            url = thunderstore.get_download_url(item["owner"], item["name"], version)
        else:
            url = latest.get("download_url")
        if not url or not target_version:
            decky.logger.error(f"Could not resolve download URL for {ref}")
            return None
        mod = registry.ModInfo(
            id=item["full_name"],
            name=item["name"],
            description=latest.get("description", ""),
            filename=item["name"],
            source=registry.ModSource(
                type="thunderstore", owner=item["owner"], repo=item["name"], install_type="zip_dir",
            ),
            author=item["owner"],
            homepage=item.get("package_url", ""),
            thumbnail=latest.get("icon", ""),
            modloader=game.modloaders[0].id if game.modloaders else "",
            dependencies=list(latest.get("dependencies", [])),
        )
        return InstallSpec(mod=mod, version=target_version, url=url)


class NexusProvider(ModProvider):
    deps_fatal = False  # a failed Nexus requirement is best-effort: warn, but install the mod anyway

    def __init__(self, denylist: set):
        self.denylist = denylist

    def key(self, ref) -> str:
        domain, mod_id = ref
        return f"nexus.{domain}.{mod_id}"

    def find(self, game, ref):
        domain, mod_id = ref
        info = nexus.get_mod(domain, mod_id)
        if not info:
            decky.logger.error(f"Nexus mod not found: {self.key(ref)}")
            return None
        return {"info": info, "requirements": nexus.get_requirements(domain, mod_id)}

    def missing_result(self, ref, is_dependency, allow_missing):
        return False  # logged in find(); Nexus has no "install anyway"

    def dep_refs(self, game, item, ref):
        domain, _mod_id = ref
        out = []
        for req in item["requirements"]:
            req_id = f"nexus.{req['domain']}.{req['mod_id']}"
            # The game's modloader is often itself a Nexus mod that others list as a requirement
            # (MHW mods depend on Stracker's Loader, nexus mod 1982). It's installed/managed by the
            # modloader system, not as a mod — installing it again here duplicates it (and its bundled
            # nativePC/plugins). Skip it.
            if _is_game_modloader(game, req["domain"], req["mod_id"]):
                decky.logger.info(f"Skipping modloader requirement {req_id} ({req.get('name')}) — managed as the loader")
                continue
            # Only same-domain Nexus mods are installable through this game's catalog; others are
            # still recorded as deps (see build_install) but left to the user.
            if req["domain"] != domain:
                decky.logger.info(f"Skipping cross-domain requirement {req_id} ({req.get('name')})")
                continue
            out.append(((req["domain"], req["mod_id"]), req.get("name") or req_id))
        return out

    def build_install(self, game, item, ref, version):
        domain, mod_id = ref
        info = item["info"]
        key = self.key(ref)
        # Record real requirements, but not the modloader (managed separately; see dep_refs).
        dep_ids = [f"nexus.{r['domain']}.{r['mod_id']}" for r in item["requirements"]
                   if not _is_game_modloader(game, r["domain"], r["mod_id"])]
        try:
            file_id = nexus.primary_file_id(domain, mod_id)
            if not file_id:
                decky.logger.error(f"No downloadable file for {key}")
                return None
            url = nexus.get_download_url(domain, mod_id, file_id)
        except nexus.PremiumRequired:
            decky.logger.info(f"Nexus mod {key} requires Premium")
            return PREMIUM_REQUIRED
        if not url:
            decky.logger.error(f"Could not resolve Nexus download URL for {key}")
            return None
        mod = registry.ModInfo(
            id=key,
            name=info.get("name") or key,
            description=info.get("summary", "") or "",
            # A safe, collision-free on-disk label; the real name lives in meta for display.
            filename=f"nexus-{mod_id}",
            source=registry.ModSource(
                type="nexus",
                install_type=game.catalog.get("install_type", "zip_flat"),
                nexus_domain=domain,
                mod_id=str(mod_id),
            ),
            author=info.get("author", "") or info.get("uploaded_by", "") or "",
            homepage=f"https://www.nexusmods.com/{domain}/mods/{mod_id}",
            thumbnail=info.get("picture_url", "") or "",
            modloader=game.modloaders[0].id if game.modloaders else "",
            dependencies=dep_ids,
        )
        target_version = version or str(info.get("version", "") or "") or "latest"
        return InstallSpec(mod=mod, version=target_version, url=url)


class FicsitProvider(ModProvider):
    """ficsit.app (Satisfactory) provider. A `ref` is a mod_reference string (e.g. "RefinedPower").
    Every mod declares SML (the loader) as a dependency — skipped here, since it's managed by the
    modloader system — and may declare other ficsit mods, which are installed depth-first at latest.
    Best-effort on deps (deps_fatal=False): a missing/failed requirement warns but doesn't abort, so
    one flaky dependency can't block the rest of an install."""
    deps_fatal = False

    def __init__(self, denylist: set):
        self.denylist = denylist

    def key(self, ref) -> str:
        # Original case (ficsit mod_references are case-sensitive); the store's lookups are
        # case-insensitive (find_installed_record), so presence checks tolerate catalog-vs-record drift.
        return f"ficsit.{ref}"

    def find(self, game, ref):
        mod = ficsit.get_mod(ref)
        if not mod:
            decky.logger.error(f"ficsit mod not found: {self.key(ref)}")
            return None
        return mod

    def missing_result(self, ref, is_dependency, allow_missing):
        return False  # logged in find(); ficsit has no "install anyway"

    def dep_refs(self, game, item, ref):
        out = []
        for dep in ficsit.dependencies(item):
            dref = dep.get("mod_id")
            if not dref:
                continue
            # Optional deps aren't auto-installed (they're enhancements, not requirements).
            if dep.get("optional"):
                continue
            # SML is every mod's dependency but it's the loader, managed by the modloader system.
            if _is_game_ficsit_modloader(game, dref):
                decky.logger.info(f"Skipping loader requirement ficsit.{dref} — managed as the loader")
                continue
            out.append((dref, dref))
        return out

    def build_install(self, game, item, ref, version):
        key = self.key(ref)
        win = ficsit.windows_version(item)
        if not win or not win.get("version_id"):
            # No Windows (Proton client) build for the latest version — can't install it on the Deck.
            decky.logger.error(f"No installable Windows build for {key}")
            return None
        url = ficsit.download_url(win["version_id"])
        authors = item.get("authors") or []
        author = ((authors[0] or {}).get("user") or {}).get("username", "") if authors else ""
        # Record real requirements (minus the loader); cosmetic — drives the "depended on by" warning.
        dep_ids = [f"ficsit.{d['mod_id']}" for d in ficsit.dependencies(item)
                   if d.get("mod_id") and not d.get("optional")
                   and not _is_game_ficsit_modloader(game, d["mod_id"])]
        mod = registry.ModInfo(
            id=key,
            name=item.get("name") or ref,
            description=item.get("short_description", "") or "",
            # The mod_reference is the exact on-disk folder name SML loads from (Mods/<ModRef>/).
            filename=ref,
            source=registry.ModSource(
                type="ficsit",
                install_type=game.catalog.get("install_type", "zip_smod"),
                mod_reference=ref,
            ),
            author=author,
            homepage=f"https://ficsit.app/mod/{item.get('id', '') or ''}",
            thumbnail=item.get("logo", "") or "",
            modloader=game.modloaders[0].id if game.modloaders else "",
            dependencies=dep_ids,
        )
        # ficsit installs are always the latest version (no per-version pick); `version` is ignored.
        return InstallSpec(mod=mod, version=win["version"], url=url)


async def run_cascade(provider: ModProvider, game, install_dir, ref, version, *, seen, installed,
                      top: bool = False, is_dependency: bool = False, with_deps: bool = True,
                      allow_missing: bool = False, variant=None, source=None):
    """Install `ref` plus its dependencies (depth-first), via `provider`. Returns True (success),
    False (hard failure), None (cancelled), PREMIUM_REQUIRED, or a {"needs_variant": ...} dict when a
    top-level install needs the UI to pick a variant.

    `seen` dedups the tree; `installed` collects the install ids freshly placed this run (so the
    caller can roll them back on cancel/failure). Deps are installed at latest (version=None); only
    the top-level mod honors an explicit `version` and a `variant` choice.

    `source` stamps Installed-page provenance on every mod placed this run (the whole tree, since it's
    threaded into the recursive calls). Defaults to None → install_mod records {"id":"manual"} as for
    a direct Browse install; a modpack passes its collection:<slug> source so the set can be grouped
    and ref-count-uninstalled."""
    key = provider.key(ref)
    if key in seen:
        return True
    seen.add(key)

    if key in provider.denylist:
        decky.logger.info(f"Skipping denylisted {key}")
        return True

    # "Already installed" means the files are actually on disk, not merely that a record exists —
    # a modloader uninstall can orphan records whose files are gone, and a stale record must not turn
    # a reinstall into a silent no-op. A version pin always reinstalls.
    present = mods.installed_files_present(game, install_dir, key)
    if present and version is None:
        decky.logger.info(f"{key} already installed; skipping")
        return True
    was_fresh = not present  # fresh installs are rollback-eligible; updates of present mods are not

    item = provider.find(game, ref)
    if item is None:
        return provider.missing_result(ref, is_dependency, allow_missing)

    # Install dependencies first (depth-first).
    for dep_ref, dep_label in (provider.dep_refs(game, item, ref) if with_deps else []):
        dep_res = await run_cascade(provider, game, install_dir, dep_ref, None, seen=seen,
                                    installed=installed, is_dependency=True, with_deps=True,
                                    allow_missing=allow_missing, source=source)
        if dep_res == PREMIUM_REQUIRED:
            return PREMIUM_REQUIRED
        if dep_res is None:
            return None  # propagate cancellation (rollback happens at the top level)
        if dep_res is False:
            if provider.deps_fatal:
                decky.logger.error(f"Dependency {dep_label} of {key} failed to install; aborting")
                return False
            # Best-effort: a failed requirement doesn't abort, but surface it so the user knows the
            # mod may be incomplete rather than silently swallowing it.
            decky.logger.warning(f"Dependency {dep_label} did not install (continuing)")
            await download_queue.note_warning(f"Couldn't install dependency: {dep_label}")

    spec = provider.build_install(game, item, ref, version)
    if spec == PREMIUM_REQUIRED:
        return PREMIUM_REQUIRED
    if spec is None:
        return False

    await download_queue.note_item(spec.mod.name)
    res = await mods.install_mod(game, install_dir, spec.mod, version=spec.version, url=spec.url,
                                 variant=variant if top else None, source=source)
    if isinstance(res, dict) and (res.get("needs_variant") or res.get("needs_fomod")):
        if top:
            return res  # park for the UI (any deps already installed are recorded in `installed`)
        # A dependency can't ask the user mid-cascade — install its default. A FOMOD dependency
        # resolves under engine defaults; a variant-bundling one installs its first variant.
        if res.get("needs_fomod"):
            decky.logger.warning(f"{key} is a FOMOD dependency; installing default options")
            choice = mods_fomod.FOMOD_DEFAULTS
        else:
            choice = (res.get("variants") or [{}])[0].get("id")
            decky.logger.warning(f"{key} bundles variants; installing default {choice!r} as a dependency")
        res = await mods.install_mod(game, install_dir, spec.mod, version=spec.version, url=spec.url,
                                     variant=choice, source=source)
    if res is True and was_fresh and installed is not None:
        installed.append(spec.mod.id)  # the install id (original case), not the lowercased dedup key
    return res


def collect_plan(provider: ModProvider, game, ref, *, version=None, with_deps, seen, plan, unresolved,
                 install_dir=None):
    """Dry-run walk of the dependency tree, mirroring run_cascade's skip logic, into `plan` (the
    depth-first refs an install will actually download — used to size "N of M") and `unresolved`
    (declared deps not found in the catalog). Downloads nothing. When `install_dir` is given a mod
    only counts as installed (and drops out of the plan) once its files are on disk; without it the
    record alone is enough."""
    key = provider.key(ref)
    if key in seen or key in provider.denylist:
        return
    seen.add(key)
    existing = mods.find_installed_record(key)
    if existing and version is None and (install_dir is None or mods.mod_files_present(game, install_dir, existing)):
        return
    item = provider.find(game, ref)
    if item is None:
        unresolved.append(ref)
        return
    if with_deps:
        for dep_ref, _label in provider.dep_refs(game, item, ref):
            collect_plan(provider, game, dep_ref, version=None, with_deps=True, seen=seen, plan=plan,
                         unresolved=unresolved, install_dir=install_dir)
    plan.append(ref)
