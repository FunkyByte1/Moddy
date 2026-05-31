import { ButtonItem, ModalRoot } from '@decky/ui';
import { FC } from 'react';
import { ModInfo, ModRelease } from '../../types';

const VersionPickerModal: FC<{
  mod: ModInfo;
  releases: ModRelease[];
  installedVersion?: string | null;
  backedUpVersions?: string[];
  onSelect: (version: string, closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ mod, releases, installedVersion, backedUpVersions = [], onSelect, closeModal }) => (
  <ModalRoot closeModal={closeModal}>
    <div style={{ padding: '16px' }}>
      <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '12px' }}>
        Choose version — {mod.name}
      </div>
      {releases.map(release => {
        const isCurrent = installedVersion === release.version;
        const isBackedUp = backedUpVersions.includes(release.version);
        return (
          <div key={release.version} style={{ marginBottom: '8px' }}>
            <ButtonItem layout="below" onClick={() => onSelect(release.version, closeModal ?? (() => {}))}>
              <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
                <span>
                  {release.version}
                  {release.published_at ? ` (${release.published_at.split('T')[0]})` : ''}
                </span>
                {isCurrent && (
                  <span style={{ color: 'var(--gpSystemLightBlue)', fontSize: '0.85em' }}>✓ current</span>
                )}
                {!isCurrent && isBackedUp && (
                  <span style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.85em' }}>↩ cached</span>
                )}
              </div>
            </ButtonItem>
          </div>
        );
      })}
    </div>
  </ModalRoot>
);

export default VersionPickerModal;