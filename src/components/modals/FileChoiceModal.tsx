import { ButtonItem, Focusable, ModalRoot, ToggleField } from '@decky/ui';
import { FC, useState } from 'react';
import { NexusVariant } from '../../types';

// Some Nexus mod pages host several installable files — a main download plus optional add-ons
// (e.g. Stardew Valley Expanded + its alternate farms). Unlike the single-pick VariantModal (one
// archive's mutually-exclusive payloads), this lets the user check one OR MORE files; the backend
// installs them together as one library entry. The first option (the author's "primary"/recommended
// file, sorted first by the backend) is pre-selected so confirming straight away installs the mod.
const FileChoiceModal: FC<{
  modName: string;
  files: NexusVariant[];
  onConfirm: (ids: string[], closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ modName, files, onConfirm, closeModal }) => {
  const close = closeModal ?? (() => {});
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(files.length ? [files[0].id] : []),
  );
  const toggle = (id: string, on: boolean) =>
    setSelected(prev => {
      const next = new Set(prev);
      if (on) next.add(id); else next.delete(id);
      return next;
    });

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '4px' }}>
          Choose files to install
        </div>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', marginBottom: '12px' }}>
          {modName} has several downloads on its Nexus page — pick the one(s) you want. They install
          together as one entry.
        </div>
        <Focusable style={{ maxHeight: '44vh', overflowY: 'auto' }}>
          {files.map(f => (
            <ToggleField
              key={f.id}
              label={f.label}
              checked={selected.has(f.id)}
              onChange={(on: boolean) => toggle(f.id, on)}
              bottomSeparator="standard"
            />
          ))}
        </Focusable>
        <Focusable flow-children="horizontal" style={{ display: 'flex', gap: '8px', marginTop: '14px' }}>
          <ButtonItem
            layout="below"
            disabled={selected.size === 0}
            onClick={() => onConfirm(Array.from(selected), close)}
          >
            {selected.size > 1 ? `Install ${selected.size} files` : 'Install'}
          </ButtonItem>
          <ButtonItem layout="below" onClick={() => close()}>
            Close
          </ButtonItem>
        </Focusable>
      </div>
    </ModalRoot>
  );
};

export default FileChoiceModal;
