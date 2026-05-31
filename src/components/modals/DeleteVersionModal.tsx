import { ButtonItem, ConfirmModal, ModalRoot, showModal } from '@decky/ui';
import { FC } from 'react';

const DeleteVersionModal: FC<{
  modName: string;
  currentVersion: string | null;
  backedUpVersions: string[];
  onDeleteAll: (closeModal: () => void) => void;
  onDeleteVersion: (version: string, closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ modName, currentVersion, backedUpVersions, onDeleteAll, onDeleteVersion, closeModal }) => (
  <ModalRoot closeModal={closeModal}>
    <div style={{ padding: '16px' }}>
      <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '4px' }}>
        Delete — {modName}
      </div>
      <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em', marginBottom: '16px' }}>
        Choose which versions to remove from disk.
      </div>

      {/* Delete all */}
      <div style={{ marginBottom: '12px' }}>
        <ButtonItem layout="below" onClick={() =>
          showModal(
            <ConfirmModal
              strTitle={`Delete all versions of ${modName}?`}
              strDescription="This will remove the mod and all cached versions from disk."
              strOKButtonText="Cancel"
              strCancelButtonText="Delete all"
              onCancel={() => onDeleteAll(closeModal ?? (() => {}))}
            />
          )
        }>
          Delete all versions
        </ButtonItem>
      </div>

      {/* Current version */}
      {currentVersion && currentVersion !== 'latest' && (
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() =>
            showModal(
              <ConfirmModal
                strTitle={`Delete ${modName} ${currentVersion}?`}
                strDescription="This will uninstall the currently active version."
                strOKButtonText="Cancel"
                strCancelButtonText="Delete"
                onCancel={() => onDeleteVersion(currentVersion, closeModal ?? (() => {}))}
              />
            )
          }>
            <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
              <span>{currentVersion}</span>
              <span style={{ color: 'var(--gpSystemLightBlue)', fontSize: '0.85em' }}>✓ current</span>
            </div>
          </ButtonItem>
        </div>
      )}

      {/* Backed up versions */}
      {backedUpVersions.map(version => (
        <div key={version} style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() =>
            showModal(
              <ConfirmModal
                strTitle={`Delete cached ${modName} ${version}?`}
                strDescription="This backup will be removed from disk."
                strOKButtonText="Cancel"
                strCancelButtonText="Delete"
                onCancel={() => onDeleteVersion(version, closeModal ?? (() => {}))}
              />
            )
          }>
            <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
              <span>{version}</span>
              <span style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em' }}>↩ cached</span>
            </div>
          </ButtonItem>
        </div>
      ))}

      {!currentVersion && backedUpVersions.length === 0 && (
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em' }}>
          No versions found on disk.
        </div>
      )}
    </div>
  </ModalRoot>
);

export default DeleteVersionModal;