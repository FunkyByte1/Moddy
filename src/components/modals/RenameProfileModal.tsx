import { ButtonItem, ModalRoot, TextField } from '@decky/ui';
import { useState, FC } from 'react';

const RenameProfileModal: FC<{
  currentName: string;
  existingNames: string[];
  onRename: (newName: string, closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ currentName, existingNames, onRename, closeModal }) => {
  const close = closeModal ?? (() => {});
  const [name, setName] = useState(currentName);
  const trimmed = name.trim();
  const conflict = trimmed !== currentName && existingNames.includes(trimmed);
  const unchanged = trimmed === currentName;

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '12px' }}>
          Rename Profile
        </div>
        <div style={{ marginBottom: '12px' }}>
          <TextField
            label="New name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            focusOnMount
          />
        </div>
        {conflict && (
          <div style={{ color: '#f8a623', fontSize: '0.85em', marginBottom: '12px' }}>
            A profile named "{trimmed}" already exists.
          </div>
        )}
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem
            layout="below"
            disabled={trimmed.length === 0 || conflict || unchanged}
            onClick={() => onRename(trimmed, close)}
          >
            Rename
          </ButtonItem>
        </div>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => close()}>Cancel</ButtonItem>
        </div>
      </div>
    </ModalRoot>
  );
};

export default RenameProfileModal;
