import { useState, useMemo, useEffect } from 'react';

import { GameStatus } from '../../types';
import { useDownloadQueue, isActiveStatus } from '../../downloadQueue';
import { BrowseItem, PagedVenueAdapter } from './types';

// Shared install busy-state for every browse venue (paged + bulk). Queue venues (Thunderstore,
// Nexus) show an optimistic `pending` mark on click that hands off to the real download-queue job;
// inline venues (Workshop) use only the local `installing` id. The adapter's isBusy/install decide
// which apply — this hook just owns the state and threads it in.
export function useBrowseInstall(
  adapter: PagedVenueAdapter,
  game: GameStatus,
  onRefresh: () => Promise<void>,
) {
  const [installing, setInstalling] = useState<string | null>(null);
  const [pending, setPending] = useState<Set<string>>(new Set());

  const queue = useDownloadQueue();
  const queuedRefs = useMemo(
    () => new Set(queue.filter(j => isActiveStatus(j.status)).map(j => j.ref.toLowerCase())),
    [queue],
  );
  // Hand off the optimistic mark once the real job appears in the queue (queue venues only).
  useEffect(() => {
    setPending(p => {
      if (p.size === 0) return p;
      let changed = false;
      const next = new Set(p);
      for (const fn of p) if (queuedRefs.has(fn.toLowerCase())) { next.delete(fn); changed = true; }
      return changed ? next : p;
    });
  }, [queuedRefs]);

  const isBusy = (it: BrowseItem) => adapter.isBusy(it, { installing, pending, queuedRefs });

  const handleInstall = (it: BrowseItem) =>
    adapter.install(it, {
      game, onRefresh, setInstalling,
      addPending: (ref) => setPending(p => new Set(p).add(ref)),
      removePending: (ref) => setPending(p => { const n = new Set(p); n.delete(ref); return n; }),
    });

  return { installing, setInstalling, isBusy, handleInstall };
}
