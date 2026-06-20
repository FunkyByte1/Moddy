import { ButtonItem, Focusable, ModalRoot } from '@decky/ui';
import { FC, useState } from 'react';

// The "Install with options…" path on the Browse tab: a per-dependency checklist so a mod that
// pins an outdated/unwanted dependency can be installed while declining that one specific dep. Plain
// Install pulls everything silently; this modal only opens when the user explicitly asks for control.
// All deps are checked by default (the version the mod wants is shown), so the common case is one
// confirm; unticking a dep installs the mod without it.
const DependencyChecklistModal: FC<{
  modName: string;
  dependencies: { id: string; name: string; version?: string }[];
  onInstall: (selectedIds: string[], closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ modName, dependencies, onInstall, closeModal }) => {
  const close = closeModal ?? (() => {});
  const [checked, setChecked] = useState<Set<string>>(() => new Set(dependencies.map(d => d.id)));
  const toggle = (id: string) =>
    setChecked(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  const count = checked.size;
  const installLabel =
    count === 0
      ? 'Install without dependencies'
      : count === dependencies.length
        ? 'Install with all dependencies'
        : `Install with ${count} dependenc${count === 1 ? 'y' : 'ies'}`;

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '8px' }}>
          Choose dependencies
        </div>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', marginBottom: '12px' }}>
          {modName} requires these mods. They’re all selected — untick any you don’t want installed
          (for example, one you already have a newer version of).
        </div>
        <Focusable style={{ maxHeight: '40vh', overflowY: 'auto', marginBottom: '12px' }}>
          {dependencies.map(dep => (
            <ButtonItem key={dep.id} layout="below" onClick={() => toggle(dep.id)}>
              {(checked.has(dep.id) ? '☑ ' : '☐ ') + dep.name + (dep.version ? `  (v${dep.version})` : '')}
            </ButtonItem>
          ))}
        </Focusable>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => onInstall([...checked], close)}>
            {installLabel}
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

export default DependencyChecklistModal;
