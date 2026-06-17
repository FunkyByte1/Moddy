import { ButtonItem, ModalRoot } from '@decky/ui';
import { FC } from 'react';

// Shown before installing when a mod declares dependencies that aren't in the catalog (so they
// can't be auto-installed). The user can install the mod anyway — it may not work without them —
// or cancel. The backend has already refreshed the catalog once, so these are genuinely missing.
const MissingDependencyModal: FC<{
  modName: string;
  missingNames: string[];
  onInstallAnyway: (closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ modName, missingNames, onInstallAnyway, closeModal }) => {
  const close = closeModal ?? (() => {});

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '8px' }}>
          Dependency not available
        </div>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', marginBottom: '8px' }}>
          {modName} depends on the following, which aren’t in the catalog and can’t be installed
          automatically:
        </div>
        <ul style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', marginBottom: '12px', paddingLeft: '16px' }}>
          {missingNames.map(name => (
            <li key={name}>{name}</li>
          ))}
        </ul>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em', marginBottom: '16px' }}>
          {modName} may not work correctly without {missingNames.length === 1 ? 'it' : 'them'}.
        </div>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => onInstallAnyway(close)}>
            Install anyway
          </ButtonItem>
        </div>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => close()}>
            Cancel
          </ButtonItem>
        </div>
      </div>
    </ModalRoot>
  );
};

export default MissingDependencyModal;
