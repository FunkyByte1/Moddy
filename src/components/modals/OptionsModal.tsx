import { ButtonItem, ModalRoot } from '@decky/ui';
import { FC } from 'react';

const OptionsModal: FC<{
  onCheckUpdates: (closeModal: () => void) => void;
  onSaveProfile: (closeModal: () => void) => void;
  canSaveProfile: boolean;
  closeModal?: () => void;
}> = ({ onCheckUpdates, onSaveProfile, canSaveProfile, closeModal }) => {
  const close = closeModal ?? (() => {});
  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '16px' }}>
          Options
        </div>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => onCheckUpdates(close)}>
            Check for Mod Updates
          </ButtonItem>
        </div>
        <div style={{ marginBottom: '4px' }}>
          <ButtonItem layout="below" disabled={!canSaveProfile} onClick={() => onSaveProfile(close)}>
            Save Current Mods as Profile…
          </ButtonItem>
        </div>
        {!canSaveProfile && (
          <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.8em', marginLeft: '4px' }}>
            Install at least one mod to save a profile.
          </div>
        )}
      </div>
    </ModalRoot>
  );
};

export default OptionsModal;
