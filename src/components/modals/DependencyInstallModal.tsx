import { ButtonItem, ModalRoot } from '@decky/ui';
import { FC } from 'react';

const DependencyInstallModal: FC<{
  modName: string;
  dependencyNames: string[];
  actionLabel?: string;
  onInstall: (closeModal: () => void) => void;
  // When provided, renders a middle "skip" button that installs the mod alone, leaving its
  // dependencies out — mirroring the Ignore option on the dependents (uninstall/disable) modal.
  onSkip?: (closeModal: () => void) => void;
  skipLabel?: string;
  closeModal?: () => void;
}> = ({ modName, dependencyNames, actionLabel = 'Install all & continue', onInstall, onSkip, skipLabel = 'Install without dependencies', closeModal }) => {
  const close = closeModal ?? (() => {});

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '8px' }}>
          Missing dependencies
        </div>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', marginBottom: '8px' }}>
          {modName} requires the following mods:
        </div>
        <ul style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', marginBottom: '16px', paddingLeft: '16px' }}>
          {dependencyNames.map(name => (
            <li key={name}>{name}</li>
          ))}
        </ul>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => onInstall(close)}>
            {actionLabel}
          </ButtonItem>
        </div>
        {onSkip && (
          <div style={{ marginBottom: '8px' }}>
            <ButtonItem layout="below" onClick={() => onSkip(close)}>
              {skipLabel}
            </ButtonItem>
          </div>
        )}
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => close()}>
            Cancel
          </ButtonItem>
        </div>
      </div>
    </ModalRoot>
  );
};

export default DependencyInstallModal;