import { showModal } from '@decky/ui';
import { toaster } from '@decky/api';

import { GameStatus, InstalledMod, uninstallMod, toggleMod } from '../../types';
import DependentsModal from '../../components/modals/DependentsModal';
import { modDisplayName } from '../../modName';

export interface UninstallTarget {
  uninstallId: string;        // recorded id to uninstall (Nexus/TS full_name, Workshop workshop.<…>)
  title: string;              // for the toast
  busyKey: string;            // key the busy state is tracked under
  dependents: InstalledMod[]; // installed mods that depend on this — matched venue-specifically by the caller
}

// Shared uninstall flow for every browse tab: when other installed mods depend on this one, warn and
// let the user cascade (delete/disable them too) or keep them, then uninstall via the recorded id.
// Dependents are computed by the caller (Thunderstore version-strips its versioned dep strings;
// Nexus/Workshop match the recorded id directly), so the venue difference stays out of here. Library
// mods this strands are not auto-cleaned — the Installed tab's "unused libraries" chip handles that
// on demand. `setInstalling` (from useBrowseInstall) drives the busy state during removal.
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
    };
    if (dependents.length > 0) {
      showModal(
        <DependentsModal
          dependentNames={dependents.map(m => modDisplayName(m))}
          primaryAction="delete"
          onDisable={c => { c(); run('disable'); }}
          onKeep={c => { c(); run('none'); }}
          onDelete={c => { c(); run('delete'); }}
        />,
      );
      return;
    }
    run('none');
  };
}
