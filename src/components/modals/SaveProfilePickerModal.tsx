import { ButtonItem, ModalRoot } from '@decky/ui';
import { FC } from 'react';

const SaveProfilePickerModal: FC<{
  existingNames: string[];
  onNewProfile: (closeModal: () => void) => void;
  onOverwrite: (name: string, closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ existingNames, onNewProfile, onOverwrite, closeModal }) => {
  const close = closeModal ?? (() => {});

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '8px' }}>
          Save Profile
        </div>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', marginBottom: '12px' }}>
          Save your current mods as a new profile, or overwrite one you've already saved.
        </div>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => onNewProfile(close)}>
            New Profile…
          </ButtonItem>
        </div>
        {existingNames.length > 0 && (
          <>
            <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.8em', margin: '12px 0 4px' }}>
              Overwrite existing
            </div>
            {existingNames.map((name) => (
              <div key={name} style={{ marginBottom: '8px' }}>
                <ButtonItem layout="below" onClick={() => onOverwrite(name, close)}>
                  {name}
                </ButtonItem>
              </div>
            ))}
          </>
        )}
      </div>
    </ModalRoot>
  );
};

export default SaveProfilePickerModal;
