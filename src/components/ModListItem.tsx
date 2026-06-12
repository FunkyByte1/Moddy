import { ToggleField, Focusable } from '@decky/ui';
import { FC } from 'react';

import { ModEntry } from './ModEntry';

const ModListItem: FC<{
  entry: ModEntry;
  selected: boolean;
  selectionMode?: boolean;
  isChecked?: boolean;
  showThumbnail?: boolean;
  onToggle: (id: string, enable: boolean) => void;
  onSelectToggle?: (id: string) => void;
  onFocus: () => void;
}> = ({ entry, selected, selectionMode, isChecked, showThumbnail, onToggle, onSelectToggle, onFocus }) => (
  <Focusable
    onFocus={onFocus}
    onActivate={() => {
      if (selectionMode) {
        onSelectToggle?.(entry.id);
      } else if (entry.installed) {
        onToggle(entry.id, !entry.enabled);
      }
    }}
    style={{
      display: 'flex', alignItems: 'center', padding: '10px 8px',
      borderRadius: '4px', marginBottom: '2px',
      background: selected ? 'var(--gpColorHighlight1)' : 'transparent',
      cursor: 'pointer', outline: 'none',
    }}
  >
    {selectionMode && (
      <div style={{
        width: '20px', height: '20px', marginRight: '10px',
        border: '2px solid var(--gpColorTextSecondary)', borderRadius: '3px',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: isChecked ? 'var(--gpSystemLightBlue)' : 'transparent',
        color: 'white', fontSize: '0.9em', fontWeight: 'bold',
        flexShrink: 0,
      }}>
        {isChecked ? '✓' : ''}
      </div>
    )}
    {showThumbnail && (
      <div style={{
        width: '32px', height: '32px', marginRight: '10px', flexShrink: 0,
        borderRadius: '3px', overflow: 'hidden', background: 'rgba(255,255,255,0.08)',
      }}>
        {entry.info.thumbnail && (
          <img src={entry.info.thumbnail} alt="" loading="lazy"
            style={{ width: '100%', height: '100%', display: 'block', objectFit: 'cover' }} />
        )}
      </div>
    )}
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{ fontWeight: selected ? 'bold' : 'normal', fontSize: '0.9em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {entry.name}
      </div>
      {!entry.installed && (
        <div style={{ fontSize: '0.75em', color: 'var(--gpColorTextSecondary)' }}>Not installed</div>
      )}
      {entry.installed && !entry.dependenciesMet && (
        <div style={{ fontSize: '0.75em', color: '#f8a623' }}>⚠ Missing dependency</div>
      )}
    </div>
    {entry.hasUpdate && (
      <div style={{ color: 'var(--gpSystemLightBlue)', fontSize: '1.1em', marginRight: '4px' }}>↑</div>
    )}
    {entry.installed && !selectionMode && (
      <ToggleField label="" checked={entry.enabled} onChange={(val) => onToggle(entry.id, val)} />
    )}
  </Focusable>
);

export default ModListItem;
