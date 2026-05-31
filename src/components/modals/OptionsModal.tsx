import { ButtonItem, ModalRoot } from '@decky/ui';
import { FC } from 'react';

const OptionsModal: FC<{
  onCheckUpdates: (closeModal: () => void) => void;
  onMelonLoaderSettings: (closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ onCheckUpdates, onMelonLoaderSettings, closeModal }) => (
  <ModalRoot closeModal={closeModal}>
    <div style={{ padding: '16px' }}>
      <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '16px' }}>
        Options
      </div>
      <div style={{ marginBottom: '8px' }}>
        <ButtonItem layout="below" onClick={() => onCheckUpdates(closeModal ?? (() => {}))}>
          Check for Updates
        </ButtonItem>
      </div>
      <div style={{ marginBottom: '8px' }}>
        <ButtonItem layout="below" onClick={() => onMelonLoaderSettings(closeModal ?? (() => {}))}>
          MelonLoader Settings
        </ButtonItem>
      </div>
    </div>
  </ModalRoot>
);

export default OptionsModal;