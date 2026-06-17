import { ModalRoot } from '@decky/ui';
import { FC } from 'react';

import { GameStatus } from '../../types';
import ModLoaderTab from '../../tabs/ModLoaderTab';

// Hosts the mod-loader management controls (version, enable/disable, updates, uninstall)
// in a modal launched from the Options menu, so they no longer need a permanent tab.
// Reuses ModLoaderTab wholesale — this modal is only reachable once the loader is set
// up, so its install/first-launch branches never render here.
const ModLoaderModal: FC<{
  game: GameStatus;
  onRefresh: () => Promise<void>;
  setInstalling: (v: boolean) => void;
  onLoaderRemoved: () => void;
  closeModal?: () => void;
}> = ({ game, onRefresh, setInstalling, onLoaderRemoved, closeModal }) => (
  <ModalRoot closeModal={closeModal}>
    <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '8px' }}>
      Manage {game.modloader_name}
    </div>
    <ModLoaderTab
      game={game}
      onRefresh={onRefresh}
      onModloaderReady={() => {}}
      setInstalling={setInstalling}
      variant="modal"
      onLoaderRemoved={onLoaderRemoved}
      onClose={closeModal}
    />
  </ModalRoot>
);

export default ModLoaderModal;
