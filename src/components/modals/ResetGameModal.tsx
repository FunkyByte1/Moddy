import { ButtonItem, ModalRoot } from '@decky/ui';
import { FC, useState, useEffect } from 'react';

const LOCKOUT_SECONDS = 1;

const ResetGameModal: FC<{
  gameName: string;
  onConfirm: (closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ gameName, onConfirm, closeModal }) => {
  const close = closeModal ?? (() => {});
  // Brief lockout so the destructive button can't be hit reflexively the instant
  // the modal pops up.
  const [countdown, setCountdown] = useState(LOCKOUT_SECONDS);

  useEffect(() => {
    if (countdown <= 0) return;
    const t = setTimeout(() => setCountdown(c => c - 1), 1000);
    return () => clearTimeout(t);
  }, [countdown]);

  const locked = countdown > 0;

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '8px' }}>
          Reset {gameName}?
        </div>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', marginBottom: '16px' }}>
          This removes every installed mod and the mod loader, restoring the game to its
          original, unmodded state. Your saved profiles are kept.{' '}
          <span style={{ color: '#ff4d4d', fontWeight: 'bold' }}>
            This permanently deletes all installed mods and cannot be undone.
          </span>
        </div>
        {/* Cancel first so it takes default gamepad focus — the user must arrow down
            to the destructive Reset action (which is also locked out below). */}
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => close()}>Cancel</ButtonItem>
        </div>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" disabled={locked} onClick={() => onConfirm(close)}>
            {locked ? `Reset (${countdown})` : 'Reset'}
          </ButtonItem>
        </div>
      </div>
    </ModalRoot>
  );
};

export default ResetGameModal;
