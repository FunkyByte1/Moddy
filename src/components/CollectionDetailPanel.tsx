import { Focusable, ScrollPanelGroup, PanelSection, PanelSectionRow, ButtonItem } from '@decky/ui';
import { FC, RefObject, useState } from 'react';

import { InstalledCollection } from '../lib/modSources';
import CollectionMods from './CollectionMods';

// Steam's gamepad-scrollable container; falls back to a plain Focusable. The right stick only scrolls
// it when focus is INSIDE it — the Uninstall button below is that focus anchor, so d-pad right from
// the collection row lands on it and the stick then scrolls down through the whole mod list.
const ScrollArea = (ScrollPanelGroup ?? Focusable) as FC<any>;

// Right-pane view shown when a collection is focused on the Installed tab: its tile image, name,
// description (like the Collections browse tab), an Uninstall button (above the mod list, mirroring a
// mod's Delete button), and the mods it includes.
const CollectionDetailPanel: FC<{
  appid: number;
  collection: InstalledCollection;
  busy: boolean;
  onEnableAll: () => void;
  onDisableAll: () => void;
  onReinstall: () => void;
  onUninstall: () => void;
  panelRef?: RefObject<HTMLDivElement | null>;  // so the row's A press can jump focus into here (the first action)
  onCancelButton?: () => void;           // B pressed here → return focus to the collection row on the left
}> = ({ appid, collection, busy, onEnableAll, onDisableAll, onReinstall, onUninstall, panelRef, onCancelButton }) => {
  const [summary, setSummary] = useState('');

  return (
    <ScrollArea focusable={false} style={{ flex: 1, minHeight: 0, height: '100%' }}>
      <Focusable
        ref={panelRef}
        noFocusRing
        onCancelButton={onCancelButton}
        style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '12px 16px 60px' }}
      >
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
          <div style={{ width: 64, height: 64, flexShrink: 0, borderRadius: 4, overflow: 'hidden', background: 'rgba(255,255,255,0.08)' }}>
            {collection.image && <img src={collection.image} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: 4 }}>{collection.name}</div>
            <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em' }}>
              {collection.count} mod{collection.count === 1 ? '' : 's'} installed
            </div>
          </div>
        </div>

        {summary && (
          <div style={{ lineHeight: '1.5', color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', whiteSpace: 'pre-wrap' }}>
            {summary}
          </div>
        )}

        {/* Above the mod list, like a mod's actions — and the focus anchor that makes the panel
            reachable (d-pad right) + scrollable (right stick). Enable/Disable all act on this
            collection's installed mods (dependency-aware, same pipeline as bulk selection). */}
        <PanelSection>
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={busy} onClick={onEnableAll}>
              Enable all mods
            </ButtonItem>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={busy} onClick={onDisableAll}>
              Disable all mods
            </ButtonItem>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={busy} onClick={onReinstall}>
              Re-install / add mods
            </ButtonItem>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={busy} onClick={onUninstall}>
              Uninstall collection
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>

        <CollectionMods appid={appid} slug={collection.slug} onLoaded={d => setSummary(d.summary)} />
      </Focusable>
    </ScrollArea>
  );
};

export default CollectionDetailPanel;
