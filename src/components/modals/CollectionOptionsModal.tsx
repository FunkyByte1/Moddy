import { ButtonItem, DialogCheckbox, Focusable, ModalRoot } from '@decky/ui';
import { FC, useRef, useState } from 'react';

import { CollectionOption } from '../../types';

// A collection's curator marks some mods optional (cosmetic / mutually-exclusive variant picks).
// These default to NONE selected — opt-in — and zero is valid (install just the required mods). The
// backend offers only optionals not already on disk, so a re-install lists just the ones you could add.
const CollectionOptionsModal: FC<{
  collectionName: string;
  options: CollectionOption[];
  onConfirm: (ids: string[], closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ collectionName, options, onConfirm, closeModal }) => {
  const close = closeModal ?? (() => {});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const toggle = (id: string, on: boolean) =>
    setSelected(prev => {
      const next = new Set(prev);
      if (on) next.add(id); else next.delete(id);
      return next;
    });
  const allOn = options.length > 0 && options.every(o => selected.has(o.id));
  const toggleAll = () => setSelected(allOn ? new Set() : new Set(options.map(o => o.id)));

  // The primary "Install" button is the destination for the Select-all and the gamepad menu button,
  // so the user can confirm from anywhere in the list without scrolling down to it.
  const installRef = useRef<HTMLDivElement>(null);
  const focusInstall = () => (installRef.current?.querySelector('button') as HTMLElement | null)?.focus();

  return (
    <ModalRoot closeModal={closeModal}>
      {/* Menu/start button jumps to Install from anywhere in the modal. */}
      <Focusable onMenuButton={focusInstall} onMenuActionDescription="Install" style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '4px' }}>
          Optional mods — {collectionName}
        </div>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => { toggleAll(); focusInstall(); }}>
            {allOn ? 'Deselect all' : 'Select all'}
          </ButtonItem>
        </div>
        <Focusable onMenuButton={focusInstall} style={{ maxHeight: '30vh', overflowY: 'auto' }}>
          {options.map(o => (
            <DialogCheckbox
              key={o.id}
              label={o.name}
              checked={selected.has(o.id)}
              onChange={(on: boolean) => toggle(o.id, on)}
            />
          ))}
        </Focusable>
        <div ref={installRef} style={{ marginTop: '14px' }}>
          <ButtonItem layout="below" onClick={() => onConfirm(Array.from(selected), close)}>
            {selected.size > 0
              ? `Install with ${selected.size} optional mod${selected.size === 1 ? '' : 's'}`
              : 'Install required only'}
          </ButtonItem>
        </div>
      </Focusable>
    </ModalRoot>
  );
};

export default CollectionOptionsModal;
