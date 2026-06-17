// Shared, module-level store for the background download queue.
//
// The QAM panel (index.tsx Content) and the routed ModPage are independent React trees with
// no shared React state, so the queue lives in a module singleton that both subscribe to via
// useSyncExternalStore. The backend is the source of truth: it emits a full `queue_state`
// snapshot on every structural change and a high-frequency `queue_progress` tick for the
// active job. We hold the latest snapshot and patch percents from progress ticks.
//
// initDownloadQueue() is called once from the plugin root; the listeners outlive any single
// page mount so background downloads stay visible after you leave a game's page.

import { useSyncExternalStore } from 'react';
import { addEventListener, removeEventListener } from '@decky/api';
import { QueueJob, getDownloadQueue } from './types';

let jobs: QueueJob[] = [];
const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

function subscribe(l: () => void): () => void {
  listeners.add(l);
  return () => { listeners.delete(l); };
}

function getSnapshot(): QueueJob[] {
  return jobs;
}

/** Read the live queue. Re-renders the calling component on any queue change. */
export function useDownloadQueue(): QueueJob[] {
  return useSyncExternalStore(subscribe, getSnapshot);
}

// A job is "active" (occupying the queue) while it is waiting, downloading, or parked for a user
// choice; done/failed/cancelled rows linger only so the user can see the outcome until cleared.
export const isActiveStatus = (s: QueueJob['status']): boolean =>
  s === 'queued' || s === 'downloading' || s === 'needs_input';

/** One-line human status for a job, shared by the modal and the Quick Access panel. */
export function jobStatusText(j: QueueJob): string {
  switch (j.status) {
    case 'downloading': {
      const nOfM = j.items_total > 1 ? ` · ${j.items_done} of ${j.items_total}` : '';
      return `${j.sub_label || 'Downloading…'}${nOfM} · ${j.percent}%`;
    }
    case 'queued': return 'Queued';
    case 'needs_input': return 'Waiting — choose a version';
    case 'done': return 'Done';
    case 'cancelled': return 'Cancelled';
    case 'failed': return j.error ? `Failed — ${j.error}` : 'Failed';
  }
}

export interface QueueSummary {
  active: QueueJob[];      // queued + downloading, in order
  current: QueueJob | null; // the one downloading now (if any)
  currentIndex: number;     // 1-based position of `current` among active (0 if none)
  total: number;            // active count
  hasFinished: boolean;     // any done/failed/cancelled rows present (→ offer "Clear")
}

export function summarize(all: QueueJob[]): QueueSummary {
  const active = all.filter(j => isActiveStatus(j.status));
  const current = active.find(j => j.status === 'downloading') ?? null;
  return {
    active,
    current,
    currentIndex: current ? active.indexOf(current) + 1 : 0,
    total: active.length,
    hasFinished: all.some(j => !isActiveStatus(j.status)),
  };
}

let stateListener: ((...args: any[]) => void) | undefined;
let progressListener: ((...args: any[]) => void) | undefined;

/** Wire the queue to backend events and hydrate the initial snapshot. Call once at plugin init. */
export function initDownloadQueue(): void {
  getDownloadQueue().then(initial => { jobs = initial ?? []; emit(); }).catch(() => {});

  stateListener = addEventListener<[next: QueueJob[]]>('queue_state', (next) => {
    jobs = next ?? [];
    emit();
  });
  // Patch just the active job's percent/sub_label without waiting for the next full snapshot.
  progressListener = addEventListener<[jobId: number, percent: number, subLabel: string]>(
    'queue_progress',
    (jobId, percent, subLabel) => {
      jobs = jobs.map(j => j.job_id === jobId ? { ...j, percent, sub_label: subLabel } : j);
      emit();
    },
  );
}

export function teardownDownloadQueue(): void {
  if (stateListener) removeEventListener('queue_state', stateListener);
  if (progressListener) removeEventListener('queue_progress', progressListener);
  stateListener = undefined;
  progressListener = undefined;
}
