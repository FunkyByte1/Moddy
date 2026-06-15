import { PanelSection, PanelSectionRow, TextField, staticClasses } from '@decky/ui';
import { definePlugin, routerHook } from '@decky/api';
import { useState, useEffect, useRef } from 'react';
import { FaPuzzlePiece } from 'react-icons/fa';

import contextMenuPatch, { LibraryContextMenu } from './contextMenuPatch';
import ModPage from './ModPage';
import {
  GameStatus, getSupportedAppids, getSupportedGames,
  getSetting, setSetting, NEXUS_API_KEY,
} from './types';

// Account-global settings live here on the landing view, since they aren't tied to one
// game. Currently just the Nexus Mods personal API key (used by the Nexus Browse tab).
function NexusApiKeyField() {
  const [value, setValue] = useState('');
  const [loaded, setLoaded] = useState(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    getSetting(NEXUS_API_KEY).then(k => {
      setValue(typeof k === 'string' ? k : '');
      setLoaded(true);
    });
    return () => { if (saveTimer.current) clearTimeout(saveTimer.current); };
  }, []);

  const onChange = (next: string) => {
    setValue(next);
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => { setSetting(NEXUS_API_KEY, next.trim()); }, 600);
  };

  return (
    <>
      <PanelSectionRow>
        <TextField
          label="Nexus Mods API key"
          value={value}
          disabled={!loaded}
          bIsPassword
          onChange={e => onChange(e.target.value)}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.75em' }}>
          Generate a personal key at nexusmods.com → Account → API Keys. Premium accounts
          can install directly; free accounts can browse only.
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
    icon: <FaPuzzlePiece />,
    onDismount() {
      routerHook.removeRoute('/moddy/:appid');
      menuPatch?.unpatch();
    },
  };
});
