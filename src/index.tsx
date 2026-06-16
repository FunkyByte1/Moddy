import { ButtonItem, Navigation, PanelSection, PanelSectionRow, staticClasses } from '@decky/ui';
import { definePlugin, routerHook, toaster } from '@decky/api';
import { useState, useEffect } from 'react';

import contextMenuPatch, { LibraryContextMenu } from './contextMenuPatch';
import ModPage from './ModPage';
import SettingsPage from './SettingsPage';
import { GameStatus, getSupportedAppids, getSupportedGames, exportLogs } from './types';

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

function Content() {
  const [games, setGames] = useState<GameStatus[]>([]);

  useEffect(() => {
    getSupportedGames().then(setGames);
  }, []);

  return (
    <>
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
      menuPatch?.unpatch();
    },
  };
});
