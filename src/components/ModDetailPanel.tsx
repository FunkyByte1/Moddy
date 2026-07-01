import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
  Focusable,
} from '@decky/ui';
import { FC } from 'react';

import { GameStatus, ModInfo, ModUpdate } from '../types';
import { ModEntry } from './ModEntry';
import { useQueueFooterProps } from './DownloadQueueModal';
import { SHOW_VERSION_OPTIONS } from '../lib/featureFlags';
import { collectionSources } from '../lib/modSources';
import { collectionNoun } from '../tabs/browse/collectionVenues';

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
  onCancelButton?: () => void;  // B pressed in the detail → return focus to the left list (the selected row)
  // Install ids (lowercase) that aren't real dependencies — modloaders / mod-manager apps like
  // Fluffy — so they're not listed or flagged as a missing dependency.
  denylist?: Set<string>;
}> = ({ entry, game, busy, installing, progress, updates, onInstall, onDelete, onUpdate, onChangeVersion, onCancel, onMenuButton, onFilterButton, onCancelButton, denylist }) => {
  const update = updates.find(u => u.id === entry.id);
  // A dep id may be a versioned Thunderstore full_name ("Owner-Mod-1.2.3") or a base id
  // ("nexus.<domain>.<id>"); test both forms against the denylist.
  const isDenylisted = (depId: string): boolean => {
    const lower = depId.toLowerCase();
    return !!denylist && (denylist.has(lower) || denylist.has(lower.split('-').slice(0, -1).join('-')));
  };
  const shownDeps = (entry.info.dependencies ?? []).filter(d => !isDenylisted(d));
  const fromCollections = collectionSources(entry.sources);
  const noun = collectionNoun(game.catalog_type);
  const queueFooter = useQueueFooterProps(game.appid);

  return (
    <Focusable
      style={{ flex: 1, overflowY: 'auto', padding: '12px 16px', paddingBottom: '60px', display: 'flex', flexDirection: 'column' }}
      {...queueFooter}
      onMenuButton={onMenuButton}
      onMenuActionDescription="Options"
      onSecondaryButton={onFilterButton}
      onSecondaryActionDescription="Filter"
      onCancelButton={onCancelButton}
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

      {shownDeps.length > 0 && (
        <div style={{ fontSize: '0.85em', marginBottom: '12px' }}>
          <div style={{ color: 'var(--gpColorTextSecondary)', marginBottom: '4px' }}>Dependencies:</div>
          {shownDeps.map(depId => {
            const depInstalled = game.installed_mods.find(m => m.id.toLowerCase() === depId.toLowerCase());
            const depEnabled = depInstalled?.enabled ?? false;
            const depName = depInstalled?.meta?.name ?? depId;
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

      {fromCollections.length > 0 && (
        <div style={{ fontSize: '0.85em', marginBottom: '12px' }}>
          <div style={{ color: 'var(--gpColorTextSecondary)', marginBottom: '4px' }}>
            {fromCollections.length === 1 ? `From ${noun.one}:` : `From ${noun.many.toLowerCase()}:`}
          </div>
          {fromCollections.map(c => (
            <div key={c.slug} style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
              <div style={{ width: '24px', height: '24px', flexShrink: 0, borderRadius: '3px', overflow: 'hidden', background: 'rgba(255,255,255,0.08)' }}>
                {c.image && <img src={c.image} alt="" loading="lazy" style={{ width: '100%', height: '100%', display: 'block', objectFit: 'cover' }} />}
              </div>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.name}</span>
            </div>
          ))}
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