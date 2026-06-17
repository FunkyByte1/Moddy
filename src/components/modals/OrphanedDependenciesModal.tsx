import { ButtonItem, ModalRoot } from '@decky/ui';
import { FC } from 'react';
import { RemovalMode } from '../../orphanCleanup';

// Shown after a mod is removed/disabled when that left library/API dependencies
// with nothing else relying on them. Mirrors DependentsModal, but for the reverse
// direction (the removed mod's own dependencies rather than its dependents).
const OrphanedDependenciesModal: FC<{
  names: string[];
  mode: RemovalMode;
  onUninstall: (closeModal: () => void) => void;
  onDisable: (closeModal: () => void) => void;
  onKeep: (closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ names, mode, onUninstall, onDisable, onKeep, closeModal }) => {
  const close = closeModal ?? (() => {});

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '8px' }}>
          Unused library dependencies
        </div>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', marginBottom: '8px' }}>
          {mode === 'disable'
            ? 'These library mods are no longer required by any enabled mod:'
            : 'These library mods are no longer required by any installed mod:'}
        </div>
        <ul style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', marginBottom: '16px', paddingLeft: '16px' }}>
          {names.map(name => (
            <li key={name}>{name}</li>
          ))}
        </ul>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => onDisable(close)}>
            Disable them
          </ButtonItem>
        </div>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => onUninstall(close)}>
            Uninstall them
          </ButtonItem>
        </div>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => onKeep(close)}>
            Keep them
          </ButtonItem>
        </div>
      </div>
    </ModalRoot>
  );
};

export default OrphanedDependenciesModal;
