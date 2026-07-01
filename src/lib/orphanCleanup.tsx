import { showModal } from '@decky/ui';

import { GameStatus, InstalledMod } from '../types';
import { uninstallMod, setLibraryIgnored } from './api';
import { modDisplayName } from './modName';
import { stripVersion } from './modGraph';
import { collectionSources } from './modSources';
import UnusedLibrariesModal from '../components/modals/UnusedLibrariesModal';

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
 * Library/API mods that nothing installed currently relies on — the input for the Installed tab's
 * "unused libraries" cleanup chip.
 *
 * A library is *used* if some live consumer depends on it, where a live consumer is any non-library
 * mod or another library already known to be used. Starting from the non-library mods and growing
 * that "used" set to a fixpoint walks dependency chains (mod → R2API → HookGenPatcher), so a library
 * kept alive only through another (itself-used) library stays used. Everything else — including
 * libraries that nothing ever depended on — is unused.
 *
 * Disabled mods still count as consumers: a disabled mod would want its deps back when re-enabled,
 * so we don't strand them. This reflects the *current* installed state (no hypothetical removal); the
 * chip surfaces it on demand rather than prompting after every uninstall.
 *
 * Denylisted packages (modloader-provided cores like BepInExPack, satisfied by the Mod Loader tab)
 * are never candidates: every mod depends on them, but those edges are intentionally dropped from the
 * graph (they're not plugin deps), which would otherwise leave them looking dependent-less. They're
 * core infrastructure, not disposable libraries.
 *
 * Libraries brought in by a COLLECTION are also excluded: a collection's dependency graph isn't
 * recorded as per-mod meta deps (so its frameworks — Content Patcher, SpaceCore, FTM — would always
 * look orphaned), and a collection's libraries are managed by it (removed via "Uninstall collection",
 * ref-counted), not by this manual-cleanup chip. After a collection is uninstalled the library loses
 * its collection source and becomes eligible again if it's then genuinely unused.
 *
 * Libraries the user explicitly marked "don't flag as unused" (ignore_unused — for a framework that
 * IS depended on via an undocumented dependency the graph can't see) are excluded too.
 */
export function findUnusedLibraries(game: GameStatus, denylist: Set<string>): InstalledMod[] {
  const fwd = buildForwardDeps(game, denylist);
  const isLib = new Map(game.installed_mods.map(m => [m.id.toLowerCase(), !!m.is_library]));
  const used = new Set<string>();
  let changed = true;
  while (changed) {
    changed = false;
    for (const m of game.installed_mods) {
      const ml = m.id.toLowerCase();
      // A library can only keep its own deps alive once it is itself known to be used; a
      // non-library is always a live consumer.
      if (m.is_library && !used.has(ml)) continue;
      for (const dep of fwd.get(ml) ?? []) {
        if (isLib.get(dep) && !used.has(dep)) { used.add(dep); changed = true; }
      }
    }
  }
  return game.installed_mods.filter(m =>
    m.is_library && !m.ignore_unused && !denylist.has(m.id.toLowerCase()) && !used.has(m.id.toLowerCase())
    && collectionSources(m.sources).length === 0);
}

/**
 * Surface the currently-unused libraries and let the user clean them up, defaulting to removing all
 * but allowing individual deselection. Fire-and-forget; no-op when nothing is unused. Called from the
 * Installed tab's cleanup chip (not automatically after a removal).
 */
export function showUnusedLibrariesCleanup(opts: {
  game: GameStatus;
  denylist: Set<string>;
  onRefresh: () => Promise<void>;
  setBusy: (b: boolean) => void;
}): void {
  const { game, denylist, onRefresh, setBusy } = opts;
  const libs = findUnusedLibraries(game, denylist);
  if (libs.length === 0) return;

  showModal(
    <UnusedLibrariesModal
      libraries={libs.map(l => ({ id: l.id, name: modDisplayName(l) }))}
      onCleanup={async (removeIds, close) => {
        close(); setBusy(true);
        for (const id of removeIds) await uninstallMod(game.appid, id);
        await onRefresh(); setBusy(false);
      }}
      onIgnore={async (ignoreIds, close) => {
        close(); setBusy(true);
        for (const id of ignoreIds) await setLibraryIgnored(id, true);
        await onRefresh(); setBusy(false);
      }}
    />
  );
}
