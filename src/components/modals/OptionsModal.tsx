import { ButtonItem, ModalRoot } from '@decky/ui';
import { FC } from 'react';

const OptionsModal: FC<{
  onCheckUpdates: (closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ onCheckUpdates, closeModal }) => (
  <ModalRoot closeModal={closeModal}>
    <div style={{ padding: '16px' }}>
      <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '16px' }}>
        Options
      </div>
      <div style={{ marginBottom: '8px' }}>
        <ButtonItem layout="below" onClick={() => onCheckUpdates(closeModal ?? (() => {}))}>
          Check for Mod Updates
        </ButtonItem>
      </div>
    </div>
  </ModalRoot>
);

export default OptionsModal;