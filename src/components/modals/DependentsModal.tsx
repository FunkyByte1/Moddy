import { ButtonItem, ModalRoot } from '@decky/ui';
import { FC } from 'react';

// Shown only when removing/disabling a mod that other installed mods depend on — i.e. exactly when
// the action would affect something the user didn't select. The cascade that matches the action in
// progress is rendered first so it's the focused default (deleting a dependency almost always means
// you want its now-broken dependents gone too), while "Keep them" is the escape hatch for pulling a
// bad/outdated dependency out from under a mod you want to keep.
const DependentsModal: FC<{
  dependentNames: string[];
  primaryAction: 'disable' | 'delete';
  onDisable: (closeModal: () => void) => void;
  onKeep: (closeModal: () => void) => void;
  onDelete: (closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ dependentNames, primaryAction, onDisable, onKeep, onDelete, closeModal }) => {
  const close = closeModal ?? (() => {});
  const cascade = primaryAction === 'delete'
    ? { label: 'Delete dependent mods too', run: onDelete }
    : { label: 'Disable dependent mods too', run: onDisable };
  const alt = primaryAction === 'delete'
    ? { label: 'Disable them instead', run: onDisable }
    : { label: 'Delete them instead', run: onDelete };
  const keepLabel = primaryAction === 'delete' ? 'Keep them' : 'Keep them enabled';

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '8px' }}>
          Dependent mods affected
        </div>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', marginBottom: '8px' }}>
          {primaryAction === 'delete'
            ? 'These installed mods depend on the one you’re removing:'
            : 'These enabled mods depend on the one you’re disabling:'}
        </div>
        <ul style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', marginBottom: '16px', paddingLeft: '16px' }}>
          {dependentNames.map(name => (
            <li key={name}>{name}</li>
          ))}
        </ul>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => cascade.run(close)}>
            {cascade.label}
          </ButtonItem>
        </div>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => alt.run(close)}>
            {alt.label}
          </ButtonItem>
        </div>
        <div style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" onClick={() => onKeep(close)}>
            {keepLabel}
          </ButtonItem>
        </div>
      </div>
    </ModalRoot>
  );
};

export default DependentsModal;
