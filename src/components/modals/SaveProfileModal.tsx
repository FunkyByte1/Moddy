import { ButtonItem, ModalRoot, TextField } from '@decky/ui';
import { useState, FC } from 'react';
import { useAutoKeyboard } from './useAutoKeyboard';

const SaveProfileModal: FC<{
  existingNames: string[];
  onSave: (name: string, closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ existingNames, onSave, closeModal }) => {
  const close = closeModal ?? (() => {});
  const [name, setName] = useState('');
  const trimmed = name.trim();
  const conflict = existingNames.includes(trimmed);
  const kbRef = useAutoKeyboard();

  // Pressing Enter / R2 closes the on-screen keyboard and fires the dialog's OK
  // action; wire it to Save so it does the same thing as clicking the button.
  const submit = () => {
    if (trimmed.length === 0) return;
    onSave(trimmed, close);
  };

  return (
    <ModalRoot closeModal={closeModal} onOK={submit}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '8px' }}>
          Save Profile
        </div>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', marginBottom: '12px' }}>
          A snapshot of every installed mod (and whether it is enabled) will be saved under this name.
        </div>
        <div ref={kbRef} style={{ marginBottom: '12px' }}>
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
            onClick={submit}
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
