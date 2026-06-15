import { ButtonItem, Focusable, ModalRoot } from '@decky/ui';
import { FC } from 'react';
import { NexusVariant } from '../../types';

// Some RE4 mods bundle several mutually-exclusive options in one archive (e.g. the Max Stack
// Sizes mod's 0999 / x02 / Ammo-only .pak variants). The backend reports them; this lets the
// user pick exactly one to install.
const VariantModal: FC<{
  modName: string;
  variants: NexusVariant[];
  onPick: (id: string, closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ modName, variants, onPick, closeModal }) => {
  const close = closeModal ?? (() => {});

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '4px' }}>
          Choose a version
        </div>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', marginBottom: '12px' }}>
          {modName} comes in multiple variants — pick the one to install.
        </div>
        <Focusable style={{ maxHeight: '50vh', overflowY: 'auto' }}>
          {variants.map(v => (
            <div key={v.id} style={{ marginBottom: '8px' }}>
              <ButtonItem layout="below" onClick={() => onPick(v.id, close)}>
                {v.label}
              </ButtonItem>
            </div>
          ))}
        </Focusable>
      </div>
    </ModalRoot>
  );
};

export default VariantModal;
