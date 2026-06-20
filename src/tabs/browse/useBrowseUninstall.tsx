import { showModal } from '@decky/ui';
import { toaster } from '@decky/api';

import { GameStatus, uninstallMod, toggleMod } from '../../types';
import DependentsModal from '../../components/modals/DependentsModal';
import { showOrphanCleanup } from '../../orphanCleanup';
import { modDisplayName } from '../../modName';
import { BrowseItem, PagedVenueAdapter } from './types';

// Shared uninstall flow for every browse venue: warn about dependents (disable/delete/ignore), then
// uninstall via the venue's recorded id, then prompt orphan cleanup. The only venue-specific bit is
// adapter.uninstallId (Nexus full_name vs Workshop workshop.<appid>.<fileid> vs Thunderstore
// full_name). `setInstalling` (from useBrowseInstall) drives the busy state during removal.
export function useBrowseUninstall(
  adapter: PagedVenueAdapter,
  game: GameStatus,
  onRefresh: () => Promise<void>,
  setInstalling: (id: string | null) => void,
) {
  return (it: BrowseItem) => {
    const uid = adapter.uninstallId(game, it);
    const dependents = game.installed_mods.filter(m => (m.meta?.dependencies ?? []).includes(uid));
    const run = async (action: 'disable' | 'delete' | 'none') => {
      setInstalling(it.key);
      try {
        if (action === 'delete') for (const d of dependents) await uninstallMod(game.appid, d.id);
        else if (action === 'disable') for (const d of dependents) await toggleMod(game.appid, d.id, false);
        const ok = await uninstallMod(game.appid, uid);
        toaster.toast({ title: 'Moddy', body: ok ? `Removed ${it.title}` : `Failed to remove ${it.title}` });
        await onRefresh();
      } finally { setInstalling(null); }
      const removedIds = action === 'delete' ? [uid, ...dependents.map(d => d.id)] : [uid];
      showOrphanCleanup({
        game, denylist: new Set<string>(), removedIds, mode: 'uninstall',
        onRefresh, setBusy: b => setInstalling(b ? it.key : null),
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
