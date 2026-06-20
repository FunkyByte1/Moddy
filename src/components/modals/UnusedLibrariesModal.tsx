import { ButtonItem, Focusable, ModalRoot } from '@decky/ui';
import { FC, useEffect, useRef, useState } from 'react';

// On-demand cleanup for library mods nothing installed relies on anymore (opened from the Installed
// tab's "unused libraries" chip — never auto-popped after a removal). Everything is selected by
// default so the common case is one confirm; scroll the list to untick any you want to keep.
const UnusedLibrariesModal: FC<{
  libraries: { id: string; name: string }[];
  onCleanup: (removeIds: string[], closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ libraries, onCleanup, closeModal }) => {
  const close = closeModal ?? (() => {});
  const [checked, setChecked] = useState<Set<string>>(() => new Set(libraries.map(l => l.id)));
  // Default gamepad focus to the primary "Remove all" action rather than the first library row, so
  // the common one-press flow doesn't make you scroll past the whole list first. rAF lets it win
  // over the modal's own initial autofocus.
  const removeAllRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const raf = requestAnimationFrame(() => {
      (removeAllRef.current?.querySelector('button, [tabindex]') as HTMLElement | null)?.focus();
    });
    return () => cancelAnimationFrame(raf);
  }, []);
  const toggle = (id: string) =>
    setChecked(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  const count = checked.size;

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ padding: '16px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.1em', marginBottom: '8px' }}>
          Unused libraries
        </div>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', marginBottom: '12px' }}>
          These library mods aren’t required by anything installed. They’re all selected for removal —
          untick any you want to keep.
        </div>
        <Focusable style={{ maxHeight: '40vh', overflowY: 'auto', marginBottom: '12px' }}>
          {libraries.map(lib => (
            <ButtonItem key={lib.id} layout="below" onClick={() => toggle(lib.id)}>
              {(checked.has(lib.id) ? '☑ ' : '☐ ') + lib.name}
            </ButtonItem>
          ))}
        </Focusable>
        <div ref={removeAllRef} style={{ marginBottom: '8px' }}>
          <ButtonItem layout="below" disabled={count === 0} onClick={() => onCleanup([...checked], close)}>
            {count === libraries.length ? `Remove all (${count})` : `Remove selected (${count})`}
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

export default UnusedLibrariesModal;
