import { ButtonItem, ModalRoot } from '@decky/ui';
import { FC } from 'react';

const DeleteProfileModal: FC<{
  profileName: string;
  onDelete: (closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ profileName, onDelete, closeModal }) => {
  const close = closeModal ?? (() => {});

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '8px' }}>
          Delete Profile
        </div>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', marginBottom: '16px' }}>
          Delete "{profileName}"? Your installed mods will not be touched — only the saved snapshot is removed.
        </div>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => onDelete(close)}>Delete</ButtonItem>
        </div>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => close()}>Cancel</ButtonItem>
        </div>
      </div>
    </ModalRoot>
  );
};

export default DeleteProfileModal;
