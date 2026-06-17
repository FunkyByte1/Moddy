import { ButtonItem, Navigation, PanelSection, PanelSectionRow, staticClasses } from '@decky/ui';
import { definePlugin, routerHook, toaster } from '@decky/api';
import { useState, useEffect } from 'react';

import contextMenuPatch, { LibraryContextMenu } from './contextMenuPatch';
import ModPage from './ModPage';
import SettingsPage from './SettingsPage';
import { GameStatus, getSupportedAppids, getSupportedGames, exportLogs, cancelDownloadJob, clearFinishedDownloads } from './types';
import { initDownloadQueue, teardownDownloadQueue, useDownloadQueue, summarize, isActiveStatus } from './downloadQueue';

// Bundles Moddy's logs into a zip on the Deck's Desktop so testers can attach it to a
// bug report. Excludes the Nexus API key (handled backend-side).
function ExportLogsButton() {
  const [busy, setBusy] = useState(false);

  const onClick = async () => {
    setBusy(true);
    try {
      const path = await exportLogs();
      toaster.toast(
        path
          ? { title: 'Logs exported', body: path }
          : { title: 'Log export failed', body: 'See the Decky log for details.' },
      );
    } catch {
      toaster.toast({ title: 'Log export failed', body: 'See the Decky log for details.' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={onClick} disabled={busy}>
          {busy ? 'Exporting…' : 'Export logs'}
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.75em' }}>
          Saves a zip to your Desktop you can attach to a bug report. Your Nexus API key is
          not included.
        </div>
      </PanelSectionRow>
    </>
  );
}

// The Moddy mark, inlined as a component so it works as the Decky panel icon without a
// separate asset/loader. Uses currentColor so it inherits Decky's icon tint. Geometry
// mirrors assets/moddy-logo.svg.
function ModdyIcon() {
  return (
    <svg viewBox="0 0 512 512" width="1em" height="1em" fill="none" stroke="currentColor" style={{ display: 'block' }}>
      <g strokeWidth={60} strokeLinecap="butt">
        <path d="M 110 426 L 110 140 L 183 206" strokeLinejoin="miter" strokeMiterlimit={12} />
        <path d="M 402 426 L 402 140 L 329 206" strokeLinejoin="miter" strokeMiterlimit={12} />
        <path d="M 161 186 L 256 272 L 351 186" strokeLinejoin="bevel" />
        <line x1={80} y1={416} x2={432} y2={416} strokeWidth={20} />
        <line x1={175} y1={370} x2={215} y2={370} strokeWidth={12} strokeLinecap="round" />
        <circle cx={317} cy={370} r={18} fill="currentColor" stroke="none" />
      </g>
    </svg>
  );
}

// Live view of the background download queue inside the Quick Access panel — the only place
// the queue stays visible after you leave a game's ModPage. Hidden entirely when idle.
function DownloadsSection() {
  const jobs = useDownloadQueue();
  if (jobs.length === 0) return null;
  const { hasFinished } = summarize(jobs);

  const statusLine = (j: typeof jobs[number]): string => {
    switch (j.status) {
      case 'downloading': {
        const nOfM = j.items_total > 1 ? ` · ${j.items_done} of ${j.items_total}` : '';
        return `${j.sub_label || 'Downloading…'}${nOfM} · ${j.percent}%`;
      }
      case 'queued': return 'Queued';
      case 'done': return 'Done';
      case 'cancelled': return 'Cancelled';
      case 'failed': return j.error ? `Failed — ${j.error}` : 'Failed';
    }
  };

  return (
    <PanelSection title="Downloads">
      {jobs.map(j => (
        <PanelSectionRow key={j.job_id}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{j.name}</span>
              {isActiveStatus(j.status) && (
                <ButtonItem layout="inline" onClick={() => cancelDownloadJob(j.job_id)}>✕</ButtonItem>
              )}
            </div>
            <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.8em' }}>{statusLine(j)}</div>
            {j.status === 'downloading' && (
              <div style={{ width: '100%', height: '4px', background: 'var(--gpColorBgTertiary)', borderRadius: '2px' }}>
                <div style={{ width: `${j.percent}%`, height: '100%', background: 'var(--gpSystemLightBlue)', borderRadius: '2px', transition: 'width 0.2s ease' }} />
              </div>
            )}
          </div>
        </PanelSectionRow>
      ))}
      {hasFinished && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => clearFinishedDownloads()}>Clear finished</ButtonItem>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

function Content() {
  const [games, setGames] = useState<GameStatus[]>([]);

  useEffect(() => {
    getSupportedGames().then(setGames);
  }, []);

  return (
    <>
      <DownloadsSection />
      <PanelSection>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => { Navigation.CloseSideMenus(); Navigation.Navigate('/moddy-settings'); }}
          >
            Settings
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Supported Games">
        {games.map(game => (
          <PanelSectionRow key={game.appid}>
            <div style={{ color: game.installed ? 'inherit' : 'var(--gpColorTextSecondary)' }}>
              {game.name}{!game.installed ? ' (not installed)' : ''}
            </div>
          </PanelSectionRow>
        ))}
        <PanelSectionRow>
          <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em', marginTop: '8px' }}>
            Press the Start button on a supported game to manage its mods.
          </div>
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Diagnostics">
        <ExportLogsButton />
      </PanelSection>
    </>
  );
}

export default definePlugin(() => {
  routerHook.addRoute('/moddy/:appid', ModPage, { exact: true });
  routerHook.addRoute('/moddy-settings', SettingsPage, { exact: true });

  // Subscribe the shared download-queue store to backend events once, for the plugin's
  // lifetime — so the queue survives navigating between (and away from) game pages.
  initDownloadQueue();

  // contextMenuPatch reads this set live at render time, so async population is fine —
  // the "Configure Mods" menu item appears as soon as the backend responds.
  const supportedAppIds = new Set<number>();
  const menuPatch = contextMenuPatch(LibraryContextMenu, supportedAppIds);
  getSupportedAppids().then(ids => {
    for (const id of ids) supportedAppIds.add(id);
  });

  return {
    name: 'Moddy',
    titleView: <div className={staticClasses.Title}>Moddy</div>,
    content: <Content />,
    icon: <ModdyIcon />,
    onDismount() {
      routerHook.removeRoute('/moddy/:appid');
      routerHook.removeRoute('/moddy-settings');
      teardownDownloadQueue();
      menuPatch?.unpatch();
    },
  };
});
