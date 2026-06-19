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
import thunderstore
import nexus
import download_queue

# Sentinel returned all the way up when a Nexus download is gated behind Premium (v1 can't serve
# free downloads). The frontend keys off this exact string to trigger the website nxm:// handoff.
PREMIUM_REQUIRED = "premium_required"


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
        dep_ids = [f"nexus.{r['domain']}.{r['mod_id']}" for r in item["requirements"]]
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


async def run_cascade(provider: ModProvider, game, install_dir, ref, version, *, seen, installed,
                      top: bool = False, is_dependency: bool = False, with_deps: bool = True,
                      allow_missing: bool = False, variant=None):
    """Install `ref` plus its dependencies (depth-first), via `provider`. Returns True (success),
    False (hard failure), None (cancelled), PREMIUM_REQUIRED, or a {"needs_variant": ...} dict when a
    top-level install needs the UI to pick a variant.

    `seen` dedups the tree; `installed` collects the install ids freshly placed this run (so the
    caller can roll them back on cancel/failure). Deps are installed at latest (version=None); only
    the top-level mod honors an explicit `version` and a `variant` choice."""
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
                                    allow_missing=allow_missing)
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
                                 variant=variant if top else None)
    if isinstance(res, dict) and res.get("needs_variant"):
        if top:
            return res  # park for the UI (any deps already installed are recorded in `installed`)
        # A dependency that bundles variants can't ask the user mid-cascade — install its first.
        first = (res.get("variants") or [{}])[0].get("id")
        decky.logger.warning(f"{key} bundles variants; installing default {first!r} as a dependency")
        res = await mods.install_mod(game, install_dir, spec.mod, version=spec.version, url=spec.url,
                                     variant=first)
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
