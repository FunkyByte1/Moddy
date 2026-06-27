import { Focusable } from '@decky/ui';
import { FC } from 'react';

import { useGameDownloadQueue, summarize } from '../lib/downloadQueue';
import { openDownloadQueue } from './DownloadQueueModal';

// At-a-glance queue indicator in the ModPage header. Shows what's downloading now for THIS game +
// position + percent; selecting it (or the Y "Downloads" button) opens the full, focus-trapped
// modal. Hidden entirely when this game's queue is empty (another game's download won't show it).
const DownloadQueuePill: FC<{ appid: number }> = ({ appid }) => {
  const jobs = useGameDownloadQueue(appid);
  if (jobs.length === 0) return null;

  const { current } = summarize(jobs);
  const lead = current ?? jobs.find(j => j.status === 'queued') ?? jobs[jobs.length - 1];
  // While downloading, show the active package + "N of M" (the cascade position) + percent.
  const nOfM = current && current.items_total > 1 ? ` · ${current.items_done} of ${current.items_total}` : '';
  const pctText = current ? ` · ${current.percent}%` : '';
  const label = current ? (current.sub_label || current.name) : lead.name;

  return (
    <Focusable
      onActivate={() => openDownloadQueue(appid)}
      onClick={() => openDownloadQueue(appid)}
      style={{
        display: 'flex', alignItems: 'center', gap: '8px',
        padding: '4px 12px', borderRadius: '14px',
        background: 'var(--gpColorBgTertiary, rgba(255,255,255,0.08))',
        fontSize: '0.85em', maxWidth: '420px', cursor: 'pointer',
      }}
    >
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        ⬇ {label}{nOfM}{pctText}
      </span>
    </Focusable>
  );
};

export default DownloadQueuePill;
