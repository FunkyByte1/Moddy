import { InstalledMod } from './types';

// Thunderstore deps are recorded as versioned full_names ("Owner-Mod-1.2.3"); dropping the trailing
// version segment yields the install id ("Owner-Mod"). Hyphen-free ids (a Workshop
// "workshop.<appid>.<fileid>") have no version to strip and yield "" — callers must guard against
// that (see resolveDepId, which falls back to the raw id).
export const stripVersion = (dep: string): string => dep.split('-').slice(0, -1).join('-');

export interface ModGraph {
  /** installed mods keyed by lowercase id */
  byId: Map<string, InstalledMod>;
  /** lowercase ids of all installed mods */
  installedIds: Set<string>;
  /** lowercase ids of enabled installed mods */
  enabledIds: Set<string>;
  /** Resolve a recorded dependency string to the lowercase mod id it refers to. */
  resolveDepId(rawDep: string): string;
  /** A mod's plugin dependencies as resolved (lowercase) ids, minus modloader-provided packages. */
  modDeps(im?: InstalledMod | null): string[];
  /** Transitive deps needing action before `rootIds` can be enabled: `missing` (not installed) and
   *  `disabled` (installed but off). Cycle-guarded; recurses into deps-of-deps. */
  collectEnableDeps(rootIds: string[]): { missing: string[]; disabled: string[] };
  /** Installed mods that depend (directly or transitively) on any of `rootIds` — the reverse of
   *  collectEnableDeps. With `requireEnabled`, only enabled dependents are followed. Excludes the
   *  roots; cycle-guarded. */
  collectDependents(rootIds: string[], requireEnabled: boolean): InstalledMod[];
  /** Order `ids` so each mod's selected-group dependencies come before it (topological). */
  topoEnableOrder(ids: string[]): string[];
}

/**
 * Build a dependency-graph view over a game's installed mods: lookup indexes plus the transitive
 * enable-deps / dependents / topo-order queries the Installed tab uses to keep dependency chains
 * consistent when mods are enabled, disabled, or removed. Pure — no React, no backend — so it's the
 * single source of truth for this logic (previously inline in InstalledTab and partly duplicated in
 * orphanCleanup). `denylist` is the set of lowercase modloader-provided package ids that must never
 * count as a plugin dependency (they're satisfied by the Mod Loader tab).
 */
export function buildModGraph(installedMods: InstalledMod[], denylist: Set<string>): ModGraph {
  const byId = new Map(installedMods.map(m => [m.id.toLowerCase(), m]));
  const installedIds = new Set(installedMods.map(m => m.id.toLowerCase()));
  const enabledIds = new Set(installedMods.filter(m => m.enabled).map(m => m.id.toLowerCase()));

  // A dep may already be a full Moddy id (a Workshop "workshop.<appid>.<fileid>") or a versioned
  // Thunderstore full_name. Match an installed id directly first, then fall back to version-stripping
  // — blindly stripping mangles hyphen-free ids (a Workshop id has no '-', so stripping yields "").
  const resolveDepId = (rawDep: string): string => {
    const raw = rawDep.toLowerCase();
    if (installedIds.has(raw)) return raw;
    const stripped = stripVersion(rawDep).toLowerCase();
    return stripped || raw;
  };

  const modDeps = (im?: InstalledMod | null): string[] =>
    (im?.meta?.dependencies ?? []).map(resolveDepId).filter(d => !denylist.has(d));

  const collectEnableDeps = (rootIds: string[]): { missing: string[]; disabled: string[] } => {
    const missing: string[] = [];
    const disabled: string[] = [];
    const seen = new Set<string>();
    const stack = rootIds.map(i => i.toLowerCase());
    while (stack.length > 0) {
      const cur = stack.pop()!;
      for (const dep of modDeps(byId.get(cur))) {
        const dl = dep.toLowerCase();
        if (seen.has(dl)) continue;
        seen.add(dl);
        if (enabledIds.has(dl)) {
          stack.push(dl); // already enabled, but a sub-dep might be off
        } else if (installedIds.has(dl)) {
          disabled.push(dep);
          stack.push(dl); // recurse into the disabled dep's own deps
        } else {
          missing.push(dep); // not installed; backend resolves its sub-deps when it's installed
        }
      }
    }
    return { missing, disabled };
  };

  const collectDependents = (rootIds: string[], requireEnabled: boolean): InstalledMod[] => {
    const rootSet = new Set(rootIds.map(i => i.toLowerCase()));
    const seen = new Set<string>();
    const result: InstalledMod[] = [];
    const stack = [...rootSet];
    while (stack.length > 0) {
      const target = stack.pop()!;
      for (const m of installedMods) {
        const ml = m.id.toLowerCase();
        if (ml === target || seen.has(ml) || rootSet.has(ml)) continue;
        if (requireEnabled && !m.enabled) continue;
        if (!(m.meta?.dependencies ?? []).some(d => resolveDepId(d) === target)) continue;
        seen.add(ml);
        result.push(m);
        stack.push(ml);
      }
    }
    return result;
  };

  const topoEnableOrder = (ids: string[]): string[] => {
    const idSet = new Set(ids.map(i => i.toLowerCase()));
    const visited = new Set<string>();
    const result: string[] = [];
    const visit = (id: string) => {
      const lower = id.toLowerCase();
      if (visited.has(lower)) return;
      visited.add(lower);
      for (const dep of modDeps(byId.get(lower))) {
        if (idSet.has(dep.toLowerCase())) {
          const depMod = byId.get(dep.toLowerCase());
          if (depMod) visit(depMod.id);
        }
      }
      result.push(id);
    };
    for (const id of ids) visit(id);
    return result;
  };

  return {
    byId, installedIds, enabledIds,
    resolveDepId, modDeps, collectEnableDeps, collectDependents, topoEnableOrder,
  };
}
