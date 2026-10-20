import { ButtonItem, Navigation, PanelSection, PanelSectionRow, staticClasses } from '@decky/ui';
import { definePlugin, routerHook, toaster } from '@decky/api';
import { useState, useEffect } from 'react';

import contextMenuPatch, { LibraryContextMenu } from './lib/contextMenuPatch';
import ModPage from './pages/ModPage';
import SettingsPage from './pages/SettingsPage';
import { getSupportedAppids, exportLogs, getStoreHealth, StoreHealth, checkModdyUpdate, ModdyUpdate, cancelDownloadJob, clearFinishedDownloads } from './lib/api';
import { initDownloadQueue, teardownDownloadQueue, useDownloadQueue, summarize, isActiveStatus, jobStatusText } from './lib/downloadQueue';
import { promptVariant } from './components/DownloadQueueModal';

// Bundles Moddy's logs into a zip on the Deck's Desktop so testers can attach it to a
// bug report. Excludes the Nexus sign-in token (handled backend-side).
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
          Saves a zip to your Desktop you can attach to a bug report. Your Nexus sign-in is
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

  return (
    <PanelSection title="Downloads">
      {jobs.map(j => (
        <PanelSectionRow key={j.job_id}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{j.name}</span>
              <div style={{ display: 'flex', gap: '4px', flexShrink: 0 }}>
                {/* A parked job is resolvable from here too, so it isn't stuck if you've left its page. */}
                {j.status === 'needs_input' && (
                  <ButtonItem layout="inline" onClick={() => promptVariant(j)}>Choose…</ButtonItem>
                )}
                {isActiveStatus(j.status) && (
                  <ButtonItem layout="inline" onClick={() => cancelDownloadJob(j.job_id)}>✕</ButtonItem>
                )}
              </div>
            </div>
            <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.8em' }}>{jobStatusText(j)}</div>
            {j.warning && <div style={{ color: '#f8a623', fontSize: '0.75em' }}>⚠ {j.warning}</div>}
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

// Explains store-file problems that would otherwise look like Moddy losing data. A corrupt
// file is set aside and started fresh (see json_store.py) — without this notice an empty
// library just looks like "all my mods vanished". A file saved by a newer Moddy is left
// untouched and installs are blocked until the user updates. Renders only when one happened.
function StoreHealthNotice() {
  const [health, setHealth] = useState<StoreHealth | null>(null);

  useEffect(() => {
    getStoreHealth().then(setHealth).catch(() => {});
  }, []);

  if (!health) return null;
  const library = health.quarantined.filter((e) => e.file === 'installed.json').pop();
  const settings = health.quarantined.filter((e) => e.file === 'settings.json').pop();
  const newer = health.read_only.length > 0;
  if (!library && !settings && !newer) return null;
  return (
    <PanelSection title="Mod library notice">
      {newer && (
        <PanelSectionRow>
          <div style={{ fontSize: '0.85em' }}>
            ⚠ Your mod library was saved by a newer version of Moddy than this one. Installing
            and changing mods is turned off so nothing gets lost. Update Moddy to continue.
          </div>
        </PanelSectionRow>
      )}
      {library && (
        <PanelSectionRow>
          <div style={{ fontSize: '0.85em' }}>
            ⚠ Moddy's mod library file was corrupt and has been set aside
            {library.to ? ` as ${library.to}` : ''}. Your mod files on disk are untouched, but the
            tracked list starts over and refills as you use Moddy. If this keeps happening, use
            Export Logs below and report it — the set-aside file is included.
          </div>
        </PanelSectionRow>
      )}
      {settings && (
        <PanelSectionRow>
          <div style={{ fontSize: '0.85em' }}>
            ⚠ Moddy's settings file was corrupt and has been reset. You may need to sign in to
            Nexus Mods again.
          </div>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

const REINSTALL_HINT =
  'To update, open Decky settings → Developer → Install from URL and enter get.moddy.gg. ' +
  'Your mods and settings are kept.';

// Decky doesn't update plugins installed from a URL, so Moddy checks its own release feed.
// Renders only when there's something to say: a newer build, or a notice the feed carries.
function UpdateNotice({ update }: { update: ModdyUpdate | null }) {
  if (!update || (!update.update_available && !update.notice)) return null;
  return (
    <PanelSection title={update.update_available ? 'Update available' : 'Notice'}>
      {update.notice && (
        <PanelSectionRow>
          <div style={{ color: '#f8a623', fontSize: '0.85em' }}>⚠ {update.notice}</div>
        </PanelSectionRow>
      )}
      {update.update_available && (
        <PanelSectionRow>
          <div style={{ fontSize: '0.85em' }}>
            A newer Moddy ({update.latest}) is out. {REINSTALL_HINT}
          </div>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

// The running version (handy for bug reports) and whether it's current.
function VersionRow({ update }: { update: ModdyUpdate | null }) {
  if (!update) return null;
  const status = update.dev_build ? ' (local build)'
    : update.error ? ' · update check failed'
    : update.update_available ? ' · update available'
    : ' · up to date';
  return (
    <PanelSectionRow>
      <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.75em' }}>
        Moddy {update.current}{status}
      </div>
    </PanelSectionRow>
  );
}

// Manual check: skips the backend's fetch cache so a build published moments ago shows up.
function CheckUpdatesButton({ onResult }: { onResult: (u: ModdyUpdate) => void }) {
  const [busy, setBusy] = useState(false);

  const onClick = async () => {
    setBusy(true);
    try {
      const u = await checkModdyUpdate(true);
      onResult(u);
      toaster.toast(
        u.error ? { title: 'Update check failed', body: u.error }
        : u.update_available ? { title: `Moddy ${u.latest} is available`, body: REINSTALL_HINT }
        : u.dev_build ? { title: 'Local build', body: 'This build has no release to compare against.' }
        : { title: 'Moddy is up to date', body: u.current },
      );
    } catch {
      toaster.toast({ title: 'Update check failed', body: 'See the Decky log for details.' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <PanelSectionRow>
      <ButtonItem layout="below" onClick={onClick} disabled={busy}>
        {busy ? 'Checking…' : 'Check for updates'}
      </ButtonItem>
    </PanelSectionRow>
  );
}

function Content() {
  const [update, setUpdate] = useState<ModdyUpdate | null>(null);

  useEffect(() => {
    checkModdyUpdate().then(setUpdate).catch(() => {});
  }, []);

  return (
    <>
      <StoreHealthNotice />
      <UpdateNotice update={update} />
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
        <PanelSectionRow>
          <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em', marginTop: '8px' }}>
            Press the Start button on a supported game to manage its mods.
          </div>
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Diagnostics">
        <ExportLogsButton />
        <CheckUpdatesButton onResult={setUpdate} />
        <VersionRow update={update} />
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

  // Announce a new build once per release (the backend remembers which one it toasted), so
  // people who never open this panel still hear about it.
  checkModdyUpdate().then(u => {
    if (u.notify) {
      toaster.toast({ title: `Moddy ${u.latest} is available`, body: u.notice ?? REINSTALL_HINT });
    }
  }).catch(() => {});

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
