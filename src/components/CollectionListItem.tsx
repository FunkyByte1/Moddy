import { Focusable } from '@decky/ui';
import { FC, useState } from 'react';

import { InstalledCollection } from '../lib/modSources';
import { centerInView } from './centerInView';

// One row in the Installed page's Collections section: the collection's tile icon (matching the
// Collections browse tab), its name on a single ellipsized line, and the installed-mod count below.
// Activating it opens the manage modal (show-only / uninstall). Focus highlight is tracked locally
// so the row lights up under the gamepad cursor like the mod-list rows.
const CollectionListItem: FC<{
  collection: InstalledCollection;
  disabled?: boolean;
  onFocusCollection?: () => void;  // gained gamepad focus → parent shows its detail in the right pane
  onActivate?: () => void;         // A pressed on the row (jumps focus to the detail's Uninstall button)
  innerRef?: (el: HTMLDivElement | null) => void;  // registers the row DOM so focus can return here (B from detail)
}> = ({ collection, disabled, onFocusCollection, onActivate, innerRef }) => {
  const [focused, setFocused] = useState(false);
  return (
    <Focusable
      ref={innerRef}
      // A `Focusable` is only a gamepad focus target when it's actionable — without onActivate the
      // d-pad skips right past the row. Keep it even though focus alone drives the detail panel.
      onActivate={() => onActivate?.()}
      onFocus={(e) => { setFocused(true); onFocusCollection?.(); centerInView(e.currentTarget); }}
      onBlur={() => setFocused(false)}
      style={{
        display: 'flex', alignItems: 'center', padding: '8px',
        borderRadius: '4px', marginBottom: '2px',
        background: focused ? 'var(--gpColorHighlight1)' : 'rgba(255,255,255,0.04)',
        cursor: 'pointer', outline: 'none', opacity: disabled ? 0.5 : 1,
      }}
    >
      <div style={{
        width: '36px', height: '36px', marginRight: '10px', flexShrink: 0,
        borderRadius: '4px', overflow: 'hidden', background: 'rgba(255,255,255,0.08)',
      }}>
        {collection.image && (
          <img src={collection.image} alt="" loading="lazy" style={{ width: '100%', height: '100%', display: 'block', objectFit: 'cover' }} />
        )}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 'bold', fontSize: '0.9em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {collection.name}
        </div>
        <div style={{ fontSize: '0.75em', color: 'var(--gpColorTextSecondary)' }}>
          {collection.count} mod{collection.count === 1 ? '' : 's'}
        </div>
      </div>
    </Focusable>
  );
};

export default CollectionListItem;
