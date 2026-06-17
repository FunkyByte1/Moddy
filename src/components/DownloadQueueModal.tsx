import { ModalRoot, DialogButton, Focusable } from '@decky/ui';
import { showModal } from '@decky/ui';
import { FC, useEffect } from 'react';

import { QueueJob, cancelDownloadJob, clearDownloadJob, clearFinishedDownloads, resumeDownloadJob } from '../types';
import { useDownloadQueue, isActiveStatus, jobStatusText } from '../downloadQueue';
import VariantModal from './modals/VariantModal';

/** Ask which variant to install for a parked (needs_input) job, then resume it from its cache. */
export function promptVariant(job: QueueJob): void {
  showModal(
    <VariantModal
      modName={job.name}
      variants={job.variants}
      onPick={(id, close) => { close(); resumeDownloadJob(job.job_id, id); }}
    />
  );
}

// The full download-queue panel. Rendered via showModal so SteamUI's ModalRoot traps gamepad
// focus inside it (and B/back closes it) — which is how you get "focus moves to the panel and
// stays there until you close it". The header pill is just the at-a-glance trigger that opens
// this. Lives in its own module (with the open() helper and the footer-button hook) so the
// store stays component-free and there's no import cycle.

const statusColor = (j: QueueJob): string => {
  switch (j.status) {
    case 'done': return '#5ba85b';
    case 'failed': return '#e25b5b';
    default: return 'var(--gpColorTextSecondary)';
  }
};

const DownloadQueueModal: FC<{ closeModal?: () => void }> = ({ closeModal }) => {
  const jobs = useDownloadQueue();
  const hasFinished = jobs.some(j => !isActiveStatus(j.status));

  // Release the single-open guard when the modal unmounts (closed by B/back or the button).
  useEffect(() => () => { modalOpen = false; }, []);

  return (
    <ModalRoot closeModal={closeModal}>
      {/* Y closes the modal (it's what opened it). onOptionsButton on the wrapper applies to every
          focused child via the footer-legend merge, and shows the "Close" prompt on Y. */}
      <Focusable
        onOptionsButton={() => closeModal?.()}
        onOptionsActionDescription="Close"
        style={{ padding: '12px 4px' }}
      >
        <div style={{ fontWeight: 'bold', fontSize: '1.2em', marginBottom: '12px' }}>Downloads</div>

        {jobs.length === 0 ? (
          <div style={{ color: 'var(--gpColorTextSecondary)' }}>No downloads.</div>
        ) : (
          <Focusable style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '50vh', overflowY: 'auto' }}>
            {jobs.map(j => {
              const active = isActiveStatus(j.status);
              // Every row carries a trailing button (Cancel while active, Clear once finished) so
              // every row is focusable/scrollable — finished rows had no focusable child before, so
              // gamepad nav skipped them — and finished items can be dismissed individually.
              return (
                <div
                  key={j.job_id}
                  style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '8px', borderRadius: '6px', background: 'var(--gpColorBgTertiary, rgba(255,255,255,0.06))' }}
                >
                  <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontWeight: 500 }}>{j.name}</span>
                    <span style={{ fontSize: '0.85em', color: statusColor(j) }}>{jobStatusText(j)}</span>
                    {j.status === 'downloading' && (
                      <div style={{ width: '100%', height: '5px', background: 'var(--gpColorBg)', borderRadius: '3px' }}>
                        <div style={{ width: `${j.percent}%`, height: '100%', background: 'var(--gpSystemLightBlue)', borderRadius: '3px', transition: 'width 0.2s ease' }} />
                      </div>
                    )}
                  </div>
                  {j.status === 'needs_input' ? (
                    <Focusable flow-children="horizontal" style={{ display: 'flex', gap: '6px', flexShrink: 0 }}>
                      <DialogButton style={{ minWidth: '96px', width: '96px', height: '36px', padding: '0' }} onClick={() => promptVariant(j)}>
                        Choose…
                      </DialogButton>
                      <DialogButton style={{ minWidth: '90px', width: '90px', height: '36px', padding: '0' }} onClick={() => cancelDownloadJob(j.job_id)}>
                        Cancel
                      </DialogButton>
                    </Focusable>
                  ) : (
                    <DialogButton
                      style={{ minWidth: '90px', width: '90px', height: '36px', padding: '0', flexShrink: 0 }}
                      onClick={() => (active ? cancelDownloadJob(j.job_id) : clearDownloadJob(j.job_id))}
                    >
                      {active ? 'Cancel' : 'Clear'}
                    </DialogButton>
                  )}
                </div>
              );
            })}
          </Focusable>
        )}

        {/* flow-children="horizontal" so the D-pad navigates left/right between these (the default
            for a Focusable group is vertical, which is why it was up/down before). */}
        <Focusable flow-children="horizontal" style={{ display: 'flex', gap: '8px', marginTop: '14px' }}>
          {hasFinished && (
            <DialogButton onClick={() => clearFinishedDownloads()}>Clear finished</DialogButton>
          )}
          <DialogButton onClick={() => closeModal?.()}>Close</DialogButton>
        </Focusable>
      </Focusable>
    </ModalRoot>
  );
};

export default DownloadQueueModal;

// Single-open guard: while the modal is up it has focus, so the page's button can't normally
// re-fire — but rapid presses before focus moves could. Reset on the modal's unmount (above).
let modalOpen = false;

/** Open the download-queue modal (no-op if already open). Triggered by the pill and the Y button. */
export function openDownloadQueue(): void {
  if (modalOpen) return;
  modalOpen = true;
  showModal(<DownloadQueueModal />);
}

/**
 * Footer-legend props for the Downloads (Y) button, spread onto any Focusable that owns a footer
 * legend. SteamUI resolves the legend from the *focused* Focusable, so each region that sets
 * Options/Filter must also set this for the prompt to appear there. Empty while the queue is idle.
 */
export function useQueueFooterProps(): { onOptionsButton?: () => void; onOptionsActionDescription?: string } {
  const jobs = useDownloadQueue();
  return jobs.length > 0
    ? { onOptionsButton: openDownloadQueue, onOptionsActionDescription: 'Downloads' }
    : {};
}
