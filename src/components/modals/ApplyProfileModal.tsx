import { ButtonItem, ModalRoot } from '@decky/ui';
import { FC } from 'react';

const ApplyProfileModal: FC<{
  profileName: string;
  missingNames: string[];
  versionChanges: { name: string; from: string | null; to: string | null }[];
  onInstallAndApply: (closeModal: () => void) => void;
  onSkipAndApply: (closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ profileName, missingNames, versionChanges, onInstallAndApply, onSkipAndApply, closeModal }) => {
  const close = closeModal ?? (() => {});

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '8px' }}>
          Apply "{profileName}"
        </div>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', marginBottom: '12px' }}>
          This profile contains mods that are not installed at the saved version.
        </div>

        {missingNames.length > 0 && (
          <div style={{ marginBottom: '12px' }}>
            <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em', marginBottom: '4px' }}>
              Missing mods ({missingNames.length}):
            </div>
            <ul style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', paddingLeft: '16px', margin: 0 }}>
              {missingNames.map(n => <li key={n}>{n}</li>)}
            </ul>
          </div>
        )}

        {versionChanges.length > 0 && (
          <div style={{ marginBottom: '12px' }}>
            <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em', marginBottom: '4px' }}>
              Version changes ({versionChanges.length}):
            </div>
            <ul style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', paddingLeft: '16px', margin: 0 }}>
              {versionChanges.map(v => (
                <li key={v.name}>{v.name}: {v.from ?? 'latest'} → {v.to ?? 'latest'}</li>
              ))}
            </ul>
          </div>
        )}

        <div style={{ marginTop: '16px', marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => onInstallAndApply(close)}>
            Install & Apply
          </ButtonItem>
        </div>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => onSkipAndApply(close)}>
            Skip Missing & Apply
          </ButtonItem>
        </div>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => close()}>Cancel</ButtonItem>
        </div>
      </div>
    </ModalRoot>
  );
};

export default ApplyProfileModal;
