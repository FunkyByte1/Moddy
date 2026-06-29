import { ToggleField, Focusable } from '@decky/ui';
import { FC, memo } from 'react';

import { ModEntry } from './ModEntry';
import { centerInView } from './centerInView';
import { collectionSources } from '../lib/modSources';

// memo() so a focus move (which only changes `selected`/`isChecked` on the two affected
// rows) re-renders just those rows instead of the whole list. Effective only because the
// parent passes referentially-stable callbacks and a memoized `entry`. `index` is passed
// so onFocus can report which row gained focus without a per-row closure.
const ModListItem: FC<{
  entry: ModEntry;
  index: number;
  selected: boolean;
  selectionMode?: boolean;
  isChecked?: boolean;
  showThumbnail?: boolean;
  onToggle: (id: string, enable: boolean) => void;
  onSelectToggle?: (id: string) => void;
  onFocus: (index: number) => void;
  innerRef?: (el: HTMLDivElement | null) => void;  // registers the row DOM so focus can return here (B from detail)
}> = ({ entry, index, selected, selectionMode, isChecked, showThumbnail, onToggle, onSelectToggle, onFocus, innerRef }) => (
  <Focusable
    ref={innerRef}
    onFocus={(e) => { onFocus(index); centerInView(e.currentTarget); }}
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
      {(() => {
        // Collection provenance shown as small tile images only (no name — it cluttered the row); one
        // per collection the mod came from, capped with a +N overflow.
        const cols = collectionSources(entry.sources);
        if (cols.length === 0) return null;
        const shown = cols.slice(0, 4);
        const extra = cols.length - shown.length;
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: '3px', marginTop: '2px' }}>
            {shown.map(c => (
              <div key={c.slug} title={c.name}
                style={{ width: '14px', height: '14px', borderRadius: '2px', overflow: 'hidden', background: 'rgba(255,255,255,0.08)', flexShrink: 0 }}>
                {c.image && <img src={c.image} alt={c.name} loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />}
              </div>
            ))}
            {extra > 0 && <span style={{ fontSize: '0.65em', color: 'var(--gpColorTextSecondary)' }}>+{extra}</span>}
          </div>
        );
      })()}
    </div>
    {entry.hasUpdate && (
      <div style={{ color: 'var(--gpSystemLightBlue)', fontSize: '1.1em', marginRight: '4px' }}>↑</div>
    )}
    {entry.installed && !selectionMode && (
      <ToggleField label="" checked={entry.enabled} onChange={(val) => onToggle(entry.id, val)} />
    )}
  </Focusable>
);

export default memo(ModListItem);
