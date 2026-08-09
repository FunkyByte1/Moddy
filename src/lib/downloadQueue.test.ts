import { describe, it, expect } from 'vitest';
import { isActiveStatus, jobStatusText, summarize, terminalTransitionAppids } from './downloadQueue';
import type { QueueJob } from '../types';

// Importing downloadQueue pulls in ./types (which imports @decky/api at module load), so this also
// proves the @decky mock in vitest-setup/setup.ts works end-to-end.

const job = (over: Partial<QueueJob>): QueueJob => ({
  job_id: 1, appid: 1, name: 'Mod', ref: 'Owner-Mod', kind: 'thunderstore',
  status: 'queued', error: '', warning: '', percent: 0, sub_label: '',
  items_done: 0, items_total: 0, variants: [],
  ...over,
}) as QueueJob;

describe('isActiveStatus', () => {
  it('is true for queued / downloading / needs_input', () => {
    expect(isActiveStatus('queued')).toBe(true);
    expect(isActiveStatus('downloading')).toBe(true);
    expect(isActiveStatus('needs_input')).toBe(true);
  });
  it('is false for terminal statuses', () => {
    expect(isActiveStatus('done')).toBe(false);
    expect(isActiveStatus('failed')).toBe(false);
    expect(isActiveStatus('cancelled')).toBe(false);
  });
});

describe('jobStatusText', () => {
  it('shows sub-label + N of M + percent while downloading a multi-item job', () => {
    expect(jobStatusText(job({
      status: 'downloading', sub_label: 'R2API', items_done: 2, items_total: 5, percent: 40,
    }))).toBe('R2API · 2 of 5 · 40%');
  });
  it('omits the "N of M" for a single-item download', () => {
    expect(jobStatusText(job({ status: 'downloading', sub_label: 'Mod', items_total: 1, percent: 10 })))
      .toBe('Mod · 10%');
  });
  it('defaults the sub-label when downloading without one', () => {
    expect(jobStatusText(job({ status: 'downloading', sub_label: '', items_total: 1, percent: 0 })))
      .toBe('Downloading… · 0%');
  });
  it('renders the simple statuses', () => {
    expect(jobStatusText(job({ status: 'queued' }))).toBe('Queued');
    expect(jobStatusText(job({ status: 'needs_input' }))).toBe('Waiting — choose a version');
    expect(jobStatusText(job({ status: 'done' }))).toBe('Done');
    expect(jobStatusText(job({ status: 'cancelled' }))).toBe('Cancelled');
  });
  it('includes the error message on failure, with a fallback', () => {
    expect(jobStatusText(job({ status: 'failed', error: 'network down' }))).toBe('Failed — network down');
    expect(jobStatusText(job({ status: 'failed', error: '' }))).toBe('Failed');
  });
});

describe('summarize', () => {
  it('counts active jobs, finds the current download, and flags finished rows', () => {
    const all = [
      job({ job_id: 1, status: 'done' }),
      job({ job_id: 2, status: 'queued' }),
      job({ job_id: 3, status: 'downloading' }),
      job({ job_id: 4, status: 'needs_input' }),
      job({ job_id: 5, status: 'failed' }),
    ];
    const s = summarize(all);
    expect(s.active.map(j => j.job_id)).toEqual([2, 3, 4]); // queued + downloading + needs_input, in order
    expect(s.current?.job_id).toBe(3);
    expect(s.currentIndex).toBe(2); // 1-based position of the downloading job among active
    expect(s.total).toBe(3);
    expect(s.hasFinished).toBe(true); // done/failed present
  });

  it('reports no current download and no finished rows for an all-queued list', () => {
    const s = summarize([job({ job_id: 1, status: 'queued' }), job({ job_id: 2, status: 'queued' })]);
    expect(s.current).toBeNull();
    expect(s.currentIndex).toBe(0);
    expect(s.total).toBe(2);
    expect(s.hasFinished).toBe(false);
  });
});

describe('terminalTransitionAppids (launch-option heal trigger)', () => {
  it('reports the appid when an active job reaches a terminal status', () => {
    const prev = [job({ job_id: 1, appid: 632360, status: 'downloading' })];
    const next = [job({ job_id: 1, appid: 632360, status: 'done' })];
    expect(terminalTransitionAppids(prev, next)).toEqual([632360]);
  });

  it('fires for failed and cancelled too — a partial collection may still have installed the loader', () => {
    const prev = [
      job({ job_id: 1, appid: 10, status: 'downloading' }),
      job({ job_id: 2, appid: 20, status: 'queued' }),
    ];
    const next = [
      job({ job_id: 1, appid: 10, status: 'failed' }),
      job({ job_id: 2, appid: 20, status: 'cancelled' }),
    ];
    expect(terminalTransitionAppids(prev, next).sort()).toEqual([10, 20]);
  });

  it('dedupes multiple same-game completions into one appid', () => {
    const prev = [
      job({ job_id: 1, appid: 632360, status: 'downloading' }),
      job({ job_id: 2, appid: 632360, status: 'queued' }),
    ];
    const next = [
      job({ job_id: 1, appid: 632360, status: 'done' }),
      job({ job_id: 2, appid: 632360, status: 'done' }),
    ];
    expect(terminalTransitionAppids(prev, next)).toEqual([632360]);
  });

  it('ignores lingering terminal rows on hydrate (job unknown to the previous snapshot)', () => {
    const next = [job({ job_id: 1, status: 'done' }), job({ job_id: 2, status: 'failed' })];
    expect(terminalTransitionAppids([], next)).toEqual([]);
  });

  it('ignores jobs that stay active or stay terminal across snapshots', () => {
    const prev = [
      job({ job_id: 1, status: 'downloading' }),
      job({ job_id: 2, status: 'done' }),
    ];
    const next = [
      job({ job_id: 1, status: 'downloading', percent: 80 }),
      job({ job_id: 2, status: 'done' }),
    ];
    expect(terminalTransitionAppids(prev, next)).toEqual([]);
  });
});
