import { useState, useMemo, useEffect } from 'react';

import { useDownloadQueue, isActiveStatus } from '../../downloadQueue';

// Shared install busy-state for every browse tab (paged Nexus/Workshop + bulk Thunderstore/BMI).
// Queue venues show an optimistic `pending` mark on click that hands off to the real download-queue
// job; the inline venue (Workshop) uses only the local `installing` id. The hook owns that state and
// exposes the primitives each tab's own install action uses (the install *action* differs per venue
// — a plain enqueue, an inline subscribe, or a dependency-prompt flow — so it stays in the tab).
//
// `pending` + `queuedRefs` are exposed for the bulk tab's pendingDepIds in-flight set.
export function useBrowseInstall(installModel: 'queue' | 'inline') {
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

  // `key` is the install id (full_name / fileId). Queue venues also read the optimistic + queued sets.
  const isBusy = (key: string): boolean =>
    installModel === 'queue'
      ? installing === key || pending.has(key) || queuedRefs.has(key.toLowerCase())
      : installing === key;

  const addPending = (ref: string) => setPending(p => new Set(p).add(ref));
  const removePending = (ref: string) => setPending(p => { const n = new Set(p); n.delete(ref); return n; });

  return { installing, setInstalling, isBusy, addPending, removePending, pending, queuedRefs };
}
