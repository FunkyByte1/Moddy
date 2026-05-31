import { ButtonItem, ModalRoot } from '@decky/ui';
import { FC } from 'react';
import { ModInfo, ModRelease } from '../../types';

const VersionPickerModal: FC<{
  mod: ModInfo;
  releases: ModRelease[];
  onSelect: (version: string, closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ mod, releases, onSelect, closeModal }) => (
  <ModalRoot closeModal={closeModal}>
    <div style={{ padding: '16px' }}>
      <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '12px' }}>
        Choose version — {mod.name}
      </div>
      {releases.map(release => (
        <div key={release.version} style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => onSelect(release.version, closeModal ?? (() => {}))}>
            {release.version}{release.published_at ? ` (${release.published_at.split('T')[0]})` : ''}
          </ButtonItem>
        </div>
      ))}
    </div>
  </ModalRoot>
);

export default VersionPickerModal;
