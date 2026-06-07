import { ButtonItem, ModalRoot } from '@decky/ui';
import { FC } from 'react';

const DependentsModal: FC<{
  dependentNames: string[];
  onDisable: (closeModal: () => void) => void;
  onIgnore: (closeModal: () => void) => void;
  onDelete: (closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ dependentNames, onDisable, onIgnore, onDelete, closeModal }) => {
  const close = closeModal ?? (() => {});

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '8px' }}>
          Dependent mods affected
        </div>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', marginBottom: '8px' }}>
          The following mods depend on this one:
        </div>
        <ul style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', marginBottom: '16px', paddingLeft: '16px' }}>
          {dependentNames.map(name => (
            <li key={name}>{name}</li>
          ))}
        </ul>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => onDisable(close)}>
            Disable dependent mods
          </ButtonItem>
        </div>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => onIgnore(close)}>
            Ignore
          </ButtonItem>
        </div>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => onDelete(close)}>
            Delete dependent mods
          </ButtonItem>
        </div>
      </div>
    </ModalRoot>
  );
};

export default DependentsModal;