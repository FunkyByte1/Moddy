import { showModal } from '@decky/ui';
import { toaster } from '@decky/api';

import { GameStatus, InstalledMod, uninstallMod, toggleMod } from '../../types';
import DependentsModal from '../../components/modals/DependentsModal';
import { showOrphanCleanup } from '../../orphanCleanup';
import { modDisplayName } from '../../modName';

export interface UninstallTarget {
  uninstallId: string;        // recorded id to uninstall (Nexus/TS full_name, Workshop workshop.<…>)
  title: string;              // for the toast
  busyKey: string;            // key the busy state is tracked under
  dependents: InstalledMod[]; // installed mods that depend on this — matched venue-specifically by the caller
}

// Shared uninstall flow for every browse tab: warn about dependents (disable/delete/ignore), then
// uninstall via the recorded id, then prompt orphan cleanup. Dependents are computed by the caller
// (Thunderstore version-strips its versioned dep strings; Nexus/Workshop match the recorded id
// directly), so the venue difference stays out of here. `setInstalling` (from useBrowseInstall)
// drives the busy state during removal.
export function useBrowseUninstall(
  game: GameStatus,
  onRefresh: () => Promise<void>,
  setInstalling: (id: string | null) => void,
) {
  return ({ uninstallId, title, busyKey, dependents }: UninstallTarget) => {
    const run = async (action: 'disable' | 'delete' | 'none') => {
      setInstalling(busyKey);
      try {
        if (action === 'delete') for (const d of dependents) await uninstallMod(game.appid, d.id);
        else if (action === 'disable') for (const d of dependents) await toggleMod(game.appid, d.id, false);
        const ok = await uninstallMod(game.appid, uninstallId);
        toaster.toast({ title: 'Moddy', body: ok ? `Removed ${title}` : `Failed to remove ${title}` });
        await onRefresh();
      } finally { setInstalling(null); }
      const removedIds = action === 'delete' ? [uninstallId, ...dependents.map(d => d.id)] : [uninstallId];
      showOrphanCleanup({
        game, denylist: new Set<string>(), removedIds, mode: 'uninstall',
        onRefresh, setBusy: b => setInstalling(b ? busyKey : null),
      });
    };
    if (dependents.length > 0) {
      showModal(
        <DependentsModal
          dependentNames={dependents.map(m => modDisplayName(m))}
          onDisable={c => { c(); run('disable'); }}
          onIgnore={c => { c(); run('none'); }}
          onDelete={c => { c(); run('delete'); }}
        />,
      );
      return;
    }
    run('none');
  };
}
