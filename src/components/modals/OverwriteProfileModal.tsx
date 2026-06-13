import { ButtonItem, ModalRoot } from '@decky/ui';
import { FC } from 'react';

const OverwriteProfileModal: FC<{
  profileName: string;
  onConfirm: (closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ profileName, onConfirm, closeModal }) => {
  const close = closeModal ?? (() => {});

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '8px' }}>
          Overwrite Profile
        </div>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', marginBottom: '16px' }}>
          Are you sure you'd like to overwrite "{profileName}"? Its saved snapshot will be
          replaced with your current mods. This can't be undone.
        </div>
        {/* Cancel first so it takes default gamepad focus — the user must arrow down
            to the destructive Overwrite action. */}
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => close()}>Cancel</ButtonItem>
        </div>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => onConfirm(close)}>Overwrite</ButtonItem>
        </div>
      </div>
    </ModalRoot>
  );
};

export default OverwriteProfileModal;
