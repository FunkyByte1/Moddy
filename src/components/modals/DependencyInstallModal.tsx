import { ButtonItem, ModalRoot } from '@decky/ui';
import { FC } from 'react';

const DependencyInstallModal: FC<{
  modName: string;
  dependencyNames: string[];
  onInstall: (closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ modName, dependencyNames, onInstall, closeModal }) => {
  const close = closeModal ?? (() => {});

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '8px' }}>
          Missing dependencies
        </div>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', marginBottom: '8px' }}>
          {modName} requires the following mods to be installed first:
        </div>
        <ul style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', marginBottom: '16px', paddingLeft: '16px' }}>
          {dependencyNames.map(name => (
            <li key={name}>{name}</li>
          ))}
        </ul>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => onInstall(close)}>
            Install all & continue
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

export default DependencyInstallModal;