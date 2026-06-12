import { ButtonItem, ModalRoot } from '@decky/ui';
import { FC } from 'react';

const OptionsModal: FC<{
  onCheckUpdates: (closeModal: () => void) => void;
  onSaveProfile: (closeModal: () => void) => void;
  canSaveProfile: boolean;
  onToggleSelectionMode?: (closeModal: () => void) => void;
  selectionMode?: boolean;
  onRefreshCatalog?: (closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ onCheckUpdates, onSaveProfile, canSaveProfile, onToggleSelectionMode, selectionMode, onRefreshCatalog, closeModal }) => {
  const close = closeModal ?? (() => {});
  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '16px' }}>
          Options
        </div>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => onCheckUpdates(close)}>
            Check for Mod Updates
          </ButtonItem>
        </div>
        {onToggleSelectionMode && (
          <div style={{ marginBottom: '8px' }}>
            <ButtonItem layout="below" onClick={() => onToggleSelectionMode(close)}>
              {selectionMode ? 'Exit Selection Mode' : 'Select Multiple Mods…'}
            </ButtonItem>
          </div>
        )}
        {onRefreshCatalog && (
          <div style={{ marginBottom: '8px' }}>
            <ButtonItem layout="below" onClick={() => onRefreshCatalog(close)}>
              Refresh Mod Catalog
            </ButtonItem>
          </div>
        )}
        <div style={{ marginBottom: '4px' }}>
          <ButtonItem layout="below" disabled={!canSaveProfile} onClick={() => onSaveProfile(close)}>
            Save Current Mods as Profile…
          </ButtonItem>
        </div>
        {!canSaveProfile && (
          <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.8em', marginLeft: '4px' }}>
            Install at least one mod to save a profile.
          </div>
        )}
      </div>
    </ModalRoot>
  );
};

export default OptionsModal;
