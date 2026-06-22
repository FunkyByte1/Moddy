import { DialogButton } from '@decky/ui';
import { FC } from 'react';

// Full-page state shown while a game is in vanilla (play-unmodded) mode, in place of the normal
// mod-management tabs. It replaces them deliberately: disabling the loader flips it to "not ready",
// which would otherwise make ModPage fall back to the Mod Loader *setup* tab — confusing, since
// nothing needs setting up. This screen makes the paused state unmistakable and gives one obvious
// way back.
const VanillaView: FC<{
  gameName: string;
  modCount: number;
  onReEnable: () => void;
}> = ({ gameName, modCount, onReEnable }) => (
  <div style={{
    height: '100%', display: 'flex', flexDirection: 'column',
    alignItems: 'center', justifyContent: 'center', textAlign: 'center',
    padding: '24px', gap: '8px',
  }}>
    <div style={{ fontSize: '2.4em', lineHeight: 1 }}>⏸️</div>
    <div style={{ fontWeight: 'bold', fontSize: '1.3em' }}>Vanilla mode is on</div>
    <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', lineHeight: 1.6, maxWidth: '440px' }}>
      {gameName} is set to run <b>unmodded</b>. {modCount > 0
        ? <>Your {modCount} mod{modCount === 1 ? '' : 's'} and the mod loader are</>
        : <>The mod loader is</>} turned off — nothing was deleted. Launch the game to play
      vanilla (handy for playing with friends), then switch back whenever you want.
    </div>
    <div style={{ marginTop: '16px', minWidth: '220px' }}>
      <DialogButton onClick={onReEnable}>
        Re-enable Mods
      </DialogButton>
    </div>
  </div>
);

export default VanillaView;
