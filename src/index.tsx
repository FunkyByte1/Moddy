import { PanelSection, PanelSectionRow, staticClasses } from '@decky/ui';
import { definePlugin, routerHook } from '@decky/api';
import { useState, useEffect } from 'react';
import { FaPuzzlePiece } from 'react-icons/fa';

import contextMenuPatch, { LibraryContextMenu } from './contextMenuPatch';
import ModPage from './ModPage';
import { GameStatus, getSupportedAppids, getSupportedGames } from './types';

function Content() {
  const [games, setGames] = useState<GameStatus[]>([]);

  useEffect(() => {
    getSupportedGames().then(setGames);
  }, []);

  return (
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
          Mods downloaded from GitHub, thunderstore.io, and the community Balatro Mod Index.
        </div>
      </PanelSectionRow>
    </PanelSection>
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
