import { ButtonItem, ModalRoot } from '@decky/ui';
import { useState, useEffect, FC } from 'react';

const FirstLaunchModal: FC<{ gameName: string; closeModal?: () => void }> = ({ gameName, closeModal }) => {
  const [canClose, setCanClose] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setCanClose(true), 1500);
    return () => clearTimeout(timer);
  }, []);

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontSize: '1.2em', fontWeight: 'bold', marginBottom: '12px' }}>
          ⚠️ First launch required
        </div>
        <div style={{ lineHeight: '1.6', marginBottom: '16px' }}>
          Before installing any mods, you must launch <strong>{gameName}</strong> once and let it fully load into the game.
        </div>
        <div style={{ lineHeight: '1.6', marginBottom: '16px' }}>
          The first launch may take <strong>2–3 minutes</strong> while MelonLoader sets itself up. Do not quit early — wait until you are fully in the game, then close it and return here.
        </div>
        <div style={{ lineHeight: '1.6', color: 'var(--gpColorTextSecondary)', fontSize: '0.85em', marginBottom: '16px' }}>
          Installing mods before this step may cause them to not work correctly.
        </div>
        <ButtonItem layout="below" onClick={closeModal} disabled={!canClose}>
          {canClose ? 'Got it' : 'Please read the above...'}
        </ButtonItem>
      </div>
    </ModalRoot>
  );
};

export default FirstLaunchModal;
