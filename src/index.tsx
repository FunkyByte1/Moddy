import { PanelSection, PanelSectionRow, staticClasses } from '@decky/ui';
import { definePlugin, routerHook } from '@decky/api';
import { useState, useEffect } from 'react';
import { FaPuzzlePiece } from 'react-icons/fa';

import contextMenuPatch, { LibraryContextMenu } from './contextMenuPatch';
import ModPage from './ModPage';
import { GameStatus, getSupportedGames } from './types';

const SUPPORTED_APP_IDS = new Set<number>([
  1657630, // Slime Rancher 2
]);

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
    </PanelSection>
  );
}

export default definePlugin(() => {
  routerHook.addRoute('/decky-mod-manager/:appid', ModPage, { exact: true });
  const menuPatch = contextMenuPatch(LibraryContextMenu, SUPPORTED_APP_IDS);

  return {
    name: 'Decky Mod Manager',
    titleView: <div className={staticClasses.Title}>Decky Mod Manager</div>,
    content: <Content />,
    icon: <FaPuzzlePiece />,
    onDismount() {
      routerHook.removeRoute('/decky-mod-manager/:appid');
      menuPatch?.unpatch();
    },
  };
});