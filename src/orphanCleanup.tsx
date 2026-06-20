import { showModal } from '@decky/ui';

import { GameStatus, InstalledMod, toggleMod, uninstallMod } from './types';
import { modDisplayName } from './modName';
import { stripVersion } from './modGraph';
import OrphanedDependenciesModal from './components/modals/OrphanedDependenciesModal';

export type RemovalMode = 'uninstall' | 'disable';

// Forward dependency edges among *installed* mods, keyed/valued by lowercase id.
// Built from installed mods' recorded meta deps, dropping edges to modloader-provided
// (denylisted) packages and to anything not installed.
function buildForwardDeps(game: GameStatus, denylist: Set<string>): Map<string, Set<string>> {
  const installed = new Set(game.installed_mods.map(m => m.id.toLowerCase()));
  const fwd = new Map<string, Set<string>>();
  // A dep string may already be a full Moddy id (a Workshop "workshop.<appid>.<fileid>"
  // id), or a versioned Thunderstore full_name ("Owner-Mod-1.2.3"). Match the installed
  // id directly first, and only fall back to version-stripping — blindly stripping
  // mangles ids with no version suffix.
  const resolve = (rawDep: string): string | null => {
    const raw = rawDep.toLowerCase();
    if (installed.has(raw)) return raw;
    const stripped = stripVersion(rawDep).toLowerCase();
    return installed.has(stripped) ? stripped : null;
  };
  const link = (modId: string, rawDep: string) => {
    const m = modId.toLowerCase();
    const d = resolve(rawDep);
    if (!d || m === d || denylist.has(d)) return;
    if (!fwd.has(m)) fwd.set(m, new Set());
    fwd.get(m)!.add(d);
  };
  for (const im of game.installed_mods) {
    for (const dep of im.meta?.dependencies ?? []) link(im.id, dep);
  }
  return fwd;
}

/**
 * Library/API mods that become orphaned when `removedIds` are uninstalled (mode
 * 'uninstall') or disabled (mode 'disable').
 *
 * Cascades: a library counts as orphaned when *all* of its remaining dependents are
 * themselves being removed, so dependency chains (mod → R2API → HookGenPatcher) are
 * fully collected. Pre-existing orphans — libraries nothing depended on to begin with
 * — are deliberately left alone; only libraries this removal strands are returned.
 *
 * For 'disable', only enabled mods count as dependents (a disabled mod neither needs
 * its deps nor can be disabled again), so it returns enabled libraries no longer
 * required by anything still enabled.
 */
export function findOrphanedLibraries(
  game: GameStatus,
  denylist: Set<string>,
  removedIds: Iterable<string>,
  mode: RemovalMode,
): InstalledMod[] {
  const fwd = buildForwardDeps(game, denylist);
  const active = (im: InstalledMod) => (mode === 'disable' ? im.enabled : true);
  const removed = new Set([...removedIds].map(id => id.toLowerCase()));

  // Active mods (excluding the growing `removed` set) that depend on the library.
  const remainingDependents = (libLower: string): boolean =>
    game.installed_mods.some(im => {
      const l = im.id.toLowerCase();
      return active(im) && l !== libLower && !removed.has(l) && (fwd.get(l)?.has(libLower) ?? false);
    });
  // Whether any active mod (removed or not) ever depended on it — used to skip
  // pre-existing orphans so an unrelated removal doesn't flag long-unused libraries.
  const everDependedOn = (libLower: string): boolean =>
    game.installed_mods.some(im => {
      const l = im.id.toLowerCase();
      return active(im) && l !== libLower && (fwd.get(l)?.has(libLower) ?? false);
    });

  const orphans: InstalledMod[] = [];
  let changed = true;
  while (changed) {
    changed = false;
    for (const im of game.installed_mods) {
      const lower = im.id.toLowerCase();
      if (!im.is_library || removed.has(lower) || !active(im)) continue;
      if (!everDependedOn(lower)) continue;        // never used → leave it alone
      if (!remainingDependents(lower)) {           // all its users are being removed
        removed.add(lower);
        orphans.push(im);
        changed = true;
      }
    }
  }
  return orphans;
}

const nameOf = (im: InstalledMod) => modDisplayName(im);

/**
 * Compute the orphaned libraries left by removing `removedIds` and, if any, prompt
 * the user to uninstall / disable / keep them. Fire-and-forget: call it after the
 * triggering removal's own refresh. `game` should be the pre-removal snapshot (the
 * removal is simulated via `removedIds`).
 */
export function showOrphanCleanup(opts: {
  game: GameStatus;
  denylist: Set<string>;
  removedIds: Iterable<string>;
  mode: RemovalMode;
  onRefresh: () => Promise<void>;
  setBusy: (b: boolean) => void;
}): void {
  const { game, denylist, removedIds, mode, onRefresh, setBusy } = opts;
  const orphans = findOrphanedLibraries(game, denylist, removedIds, mode);
  if (orphans.length === 0) return;

  showModal(
    <OrphanedDependenciesModal
      names={orphans.map(nameOf)}
      mode={mode}
      onUninstall={async (close) => {
        close(); setBusy(true);
        for (const o of orphans) await uninstallMod(game.appid, o.id);
        await onRefresh(); setBusy(false);
      }}
      onDisable={async (close) => {
        close(); setBusy(true);
        for (const o of orphans) await toggleMod(game.appid, o.id, false);
        await onRefresh(); setBusy(false);
      }}
      onKeep={(close) => { close(); }}
    />
  );
}
