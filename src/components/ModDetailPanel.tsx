import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
  Focusable,
} from '@decky/ui';
import { FC } from 'react';

import { GameStatus, ModInfo, ModUpdate } from '../types';
import { ModEntry } from './ModEntry';
import { SHOW_VERSION_OPTIONS } from '../featureFlags';

const ModDetailPanel: FC<{
  entry: ModEntry;
  game: GameStatus;
  busy: boolean;
  installing: boolean;
  progress: number;
  updates: ModUpdate[];
  onInstall: (mod: ModInfo) => void;
  onDelete: (mod: ModInfo) => void;
  onUpdate: (mod: ModInfo) => void;
  onChangeVersion: (mod: ModInfo) => void;
  onCancel: () => void;
  onMenuButton: () => void;
  onFilterButton: () => void;
}> = ({ entry, game, busy, installing, progress, updates, onInstall, onDelete, onUpdate, onChangeVersion, onCancel, onMenuButton, onFilterButton }) => {
  const update = updates.find(u => u.id === entry.id);

  return (
    <Focusable
      style={{ flex: 1, overflowY: 'auto', padding: '12px 16px', paddingBottom: '60px', display: 'flex', flexDirection: 'column' }}
      onMenuButton={onMenuButton}
      onMenuActionDescription="Options"
      onSecondaryButton={onFilterButton}
      onSecondaryActionDescription="Filter"
    >
      {installing && (
        <div style={{ marginBottom: '12px' }}>
          <div style={{ marginBottom: '4px', fontSize: '0.85em', color: 'var(--gpColorTextSecondary)' }}>
            {`Installing... ${progress}%`}
          </div>
          <div style={{ width: '100%', height: '6px', background: 'var(--gpColorBgTertiary)', borderRadius: '3px', marginBottom: '6px' }}>
            <div style={{ width: `${progress}%`, height: '100%', background: 'var(--gpSystemLightBlue)', borderRadius: '3px', transition: 'width 0.2s ease' }} />
          </div>
          <ButtonItem layout="below" onClick={onCancel}>Cancel</ButtonItem>
        </div>
      )}

      <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start', marginBottom: '8px' }}>
        {entry.info.thumbnail && (
          <div style={{ width: '64px', height: '64px', flexShrink: 0, borderRadius: '4px', overflow: 'hidden', background: 'rgba(255,255,255,0.08)' }}>
            <img src={entry.info.thumbnail} style={{ width: '100%', height: '100%', display: 'block', objectFit: 'cover' }} />
          </div>
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '4px' }}>{entry.name}</div>
          {entry.info.author && (
            <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em' }}>
              by {entry.info.author}
            </div>
          )}
        </div>
      </div>

      {entry.version && (
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em', marginBottom: '8px' }}>
          Installed: {entry.version}
          {update && <span style={{ color: 'var(--gpSystemLightBlue)', marginLeft: '8px' }}>↑ {update.latest_version} available</span>}
        </div>
      )}

      {entry.info.description && (
        <div style={{ lineHeight: '1.5', marginBottom: '12px', color: 'var(--gpColorTextSecondary)', fontSize: '0.9em' }}>
          {entry.info.description}
        </div>
      )}

      {entry.info.dependencies && entry.info.dependencies.length > 0 && (
        <div style={{ fontSize: '0.85em', marginBottom: '12px' }}>
          <div style={{ color: 'var(--gpColorTextSecondary)', marginBottom: '4px' }}>Dependencies:</div>
          {entry.info.dependencies.map(depId => {
            const depInstalled = game.installed_mods.find(m => m.id.toLowerCase() === depId.toLowerCase());
            const depEnabled = depInstalled?.enabled ?? false;
            const depName = game.mods.find(m => m.id === depId)?.name ?? depInstalled?.meta?.name ?? depId;
            return (
              <div key={depId} style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '2px' }}>
                <span style={{ color: depEnabled ? '#5ba85b' : '#f8a623' }}>
                  {depEnabled ? '✓' : depInstalled ? '⚠ disabled' : '⚠ not installed'}
                </span>
                <span style={{ color: 'var(--gpColorTextSecondary)' }}>{depName}</span>
              </div>
            );
          })}
        </div>
      )}

      <PanelSection>
        {entry.installed ? (
          <>
            {update && (
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={() => onUpdate(entry.info)} disabled={busy}>
                  {`Update to ${update.latest_version}`}
                </ButtonItem>
              </PanelSectionRow>
            )}
            {SHOW_VERSION_OPTIONS && game.modloader !== 'steamworkshop' && (
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={() => onChangeVersion(entry.info)} disabled={busy}>
                  Change Version
                </ButtonItem>
              </PanelSectionRow>
            )}
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => onDelete(entry.info)} disabled={busy}>
                Delete
              </ButtonItem>
            </PanelSectionRow>
          </>
        ) : (
          <>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => onInstall(entry.info)} disabled={busy}>
                Install Latest
              </ButtonItem>
            </PanelSectionRow>
            {SHOW_VERSION_OPTIONS && game.modloader !== 'steamworkshop' && (
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={() => onChangeVersion(entry.info)} disabled={busy}>
                  Choose Version
                </ButtonItem>
              </PanelSectionRow>
            )}
          </>
        )}
      </PanelSection>
    </Focusable>
  );
};

export default ModDetailPanel;