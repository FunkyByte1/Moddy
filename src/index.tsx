import { ButtonItem, PanelSection, PanelSectionRow, TextField, staticClasses } from '@decky/ui';
import { definePlugin, routerHook, toaster } from '@decky/api';
import { useState, useEffect, useRef } from 'react';
import { FaEye, FaEyeSlash } from 'react-icons/fa';

import contextMenuPatch, { LibraryContextMenu } from './contextMenuPatch';
import ModPage from './ModPage';
import {
  GameStatus, getSupportedAppids, getSupportedGames,
  getSetting, setSetting, NEXUS_API_KEY, exportLogs,
} from './types';

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

// Account-global settings live here on the landing view, since they aren't tied to one
// game. Currently just the Nexus Mods personal API key (used by the Nexus Browse tab).
function NexusApiKeyField() {
  const [value, setValue] = useState('');
  const [show, setShow] = useState(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // Populate from the stored key, but NEVER gate the field's enabled state on this load.
    // A previous version disabled the field until the load resolved; when get_setting threw
    // (the settings-module collision) it stayed disabled and unfocusable forever. Keep it
    // always editable, and don't clobber anything the user has already typed.
    getSetting(NEXUS_API_KEY)
      .then(k => { if (typeof k === 'string' && k) setValue(prev => (prev === '' ? k : prev)); })
      .catch(() => {});
    return () => { if (saveTimer.current) clearTimeout(saveTimer.current); };
  }, []);

  const onChange = (next: string) => {
    setValue(next);
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => { setSetting(NEXUS_API_KEY, next.trim()); }, 600);
  };

  return (
    <>
      {/* Decky's bIsPassword is a no-op on current Steam builds, so mask the input
          visually with CSS instead. The real value stays intact (editing/paste work);
          the Show/Hide toggle just flips the masking. */}
      <style>{`.moddy-apikey-mask input { -webkit-text-security: disc !important; }`}</style>
      <PanelSectionRow>
        <div className={show ? undefined : 'moddy-apikey-mask'}>
          <TextField
            label="Nexus Mods API key"
            value={value}
            onChange={e => onChange(e.target.value)}
          />
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => setShow(s => !s)}>
          {show
            ? <span><FaEyeSlash style={{ marginRight: '6px', verticalAlign: 'middle' }} />Hide key</span>
            : <span><FaEye style={{ marginRight: '6px', verticalAlign: 'middle' }} />Show key</span>}
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.75em' }}>
          Generate a personal key at nexusmods.com → Account → API Keys. Premium accounts
          can install; a key is required for browsing.
        </div>
      </PanelSectionRow>
    </>
  );
}

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

function Content() {
  const [games, setGames] = useState<GameStatus[]>([]);

  useEffect(() => {
    getSupportedGames().then(setGames);
  }, []);

  return (
    <>
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
        <PanelSectionRow>
          <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.75em', marginTop: '12px' }}>
            Mods downloaded from GitHub, thunderstore.io, Nexus Mods, and the community Balatro Mod Index.
          </div>
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Settings">
        <NexusApiKeyField />
      </PanelSection>
      <PanelSection title="Diagnostics">
        <ExportLogsButton />
      </PanelSection>
    </>
  );
}

export default definePlugin(() => {
  routerHook.addRoute('/moddy/:appid', ModPage, { exact: true });

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
      menuPatch?.unpatch();
    },
  };
});
