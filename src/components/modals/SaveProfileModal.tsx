import { ButtonItem, ModalRoot, TextField } from '@decky/ui';
import { useState, FC } from 'react';

const SaveProfileModal: FC<{
  existingNames: string[];
  onSave: (name: string, closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ existingNames, onSave, closeModal }) => {
  const close = closeModal ?? (() => {});
  const [name, setName] = useState('');
  const trimmed = name.trim();
  const conflict = existingNames.includes(trimmed);

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '8px' }}>
          Save Profile
        </div>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', marginBottom: '12px' }}>
          A snapshot of every installed mod (and whether it is enabled) will be saved under this name.
        </div>
        <div style={{ marginBottom: '12px' }}>
          <TextField
            label="Profile name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            focusOnMount
          />
        </div>
        {conflict && (
          <div style={{ color: '#f8a623', fontSize: '0.85em', marginBottom: '12px' }}>
            A profile named "{trimmed}" already exists — saving will overwrite it.
          </div>
        )}
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem
            layout="below"
            disabled={trimmed.length === 0}
            onClick={() => onSave(trimmed, close)}
          >
            {conflict ? 'Overwrite' : 'Save'}
          </ButtonItem>
        </div>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => close()}>Cancel</ButtonItem>
        </div>
      </div>
    </ModalRoot>
  );
};

export default SaveProfileModal;
