import { ModalRoot, DialogButton, Focusable } from '@decky/ui';
import { showModal } from '@decky/ui';
import { FC, useEffect, useRef } from 'react';

import { QueueJob } from '../types';
import { cancelDownloadJob, clearDownloadJob, clearFinishedDownloads, resumeDownloadJob } from '../lib/api';
import { useDownloadQueue, useGameDownloadQueue, summarize, isActiveStatus, jobStatusText } from '../lib/downloadQueue';
import VariantModal from './modals/VariantModal';
import FileChoiceModal from './modals/FileChoiceModal';
import FomodWizardModal from './modals/FomodWizardModal';

/** Resolve a parked (needs_input) job's choice, then resume it. A FOMOD job shows the install
 *  wizard (resume with the chosen plugin indices as JSON); a multi-select job is a Nexus file
 *  picker (resume with ids comma-joined); otherwise it's a single-pick archive variant. All ride
 *  the same resume channel. */
export function promptVariant(job: QueueJob): void {
  if (job.fomod) {
    showModal(
      <FomodWizardModal
        model={job.fomod}
        onInstall={(selections, close) => { close(); resumeDownloadJob(job.job_id, JSON.stringify(selections)); }}
      />
    );
    return;
  }
  if (job.multi_select) {
    showModal(
      <FileChoiceModal
        modName={job.name}
        files={job.variants}
        onConfirm={(ids, close) => { close(); resumeDownloadJob(job.job_id, ids.join(',')); }}
      />
    );
    return;
  }
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

const DownloadQueueModal: FC<{ appid: number; closeModal?: () => void }> = ({ appid, closeModal }) => {
  const jobs = useGameDownloadQueue(appid);
  const hasFinished = jobs.some(j => !isActiveStatus(j.status));

  // The backend queue is globally serial — one worker drains it across all games — but this panel
  // only lists THIS game's jobs. So a job here can sit at "Queued" with nothing above it while the
  // worker is busy downloading for a different game. Surface that, without naming the other game's
  // mod, so the empty-list-but-still-queued state reads as "waiting in line", not "stuck".
  const { current } = summarize(useDownloadQueue());
  const foreignDownloading = current !== null && current.appid !== appid;

  // Release the single-open guard when the modal unmounts (closed by B/back or the button).
  useEffect(() => () => { modalOpen = false; }, []);

  // Default gamepad focus to the footer's first button — "Clear finished" when there are
  // finished jobs to clear, otherwise "Close" — instead of the top download row, so opening
  // the queue just to dismiss it doesn't start you deep in the list. rAF lets it win over the
  // modal's own initial autofocus (same trick as UnusedLibrariesModal). Mount-only so a job
  // finishing while you're scrolling the list doesn't yank focus back to the footer.
  const footerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const raf = requestAnimationFrame(() => {
      (footerRef.current?.querySelector('button, [tabindex]') as HTMLElement | null)?.focus();
    });
    return () => cancelAnimationFrame(raf);
  }, []);

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

        {foreignDownloading && (
          <div style={{
            marginBottom: '12px', padding: '8px 10px', borderRadius: '6px',
            background: 'var(--gpColorBgTertiary, rgba(255,255,255,0.06))',
            fontSize: '0.85em', color: 'var(--gpColorTextSecondary)',
          }}>
            ⬇ A download for another game is in progress.
          </div>
        )}

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
                    {j.warning && <span style={{ fontSize: '0.8em', color: '#f8a623' }}>⚠ {j.warning}</span>}
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
        <Focusable ref={footerRef} flow-children="horizontal" style={{ display: 'flex', gap: '8px', marginTop: '14px' }}>
          {hasFinished && (
            <DialogButton onClick={() => clearFinishedDownloads(appid)}>Clear finished</DialogButton>
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

/** Open the download-queue panel for one game (no-op if already open). Triggered by the pill and
 * the Y button. The panel shows only `appid`'s jobs — the queue is per-game from the UI's view. */
export function openDownloadQueue(appid: number): void {
  if (modalOpen) return;
  modalOpen = true;
  showModal(<DownloadQueueModal appid={appid} />);
}

/**
 * Footer-legend props for the Downloads (Y) button, spread onto any Focusable that owns a footer
 * legend. SteamUI resolves the legend from the *focused* Focusable, so each region that sets
 * Options/Filter must also set this for the prompt to appear there. Scoped to `appid`: the prompt
 * only shows (and Y only opens the panel) when *this game* has queued jobs.
 */
export function useQueueFooterProps(appid: number): { onOptionsButton?: () => void; onOptionsActionDescription?: string } {
  const jobs = useGameDownloadQueue(appid);
  return jobs.length > 0
    ? { onOptionsButton: () => openDownloadQueue(appid), onOptionsActionDescription: 'Downloads' }
    : {};
}
