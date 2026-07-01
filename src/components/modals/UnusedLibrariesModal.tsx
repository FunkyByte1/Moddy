import { DialogButton, DialogCheckbox, Focusable, ModalRoot } from '@decky/ui';
import { FC, useEffect, useRef, useState } from 'react';

// On-demand cleanup for library mods nothing installed relies on anymore (opened from the Installed
// tab's "unused libraries" chip — never auto-popped after a removal). Everything is selected by
// default so the common case is one confirm; scroll the list to untick any you want to keep.
const UnusedLibrariesModal: FC<{
  libraries: { id: string; name: string }[];
  onCleanup: (removeIds: string[], closeModal: () => void) => void;
  // Mark the checked libraries as intentional deps so they stop being flagged as unused. For a
  // framework that IS required, just via an undocumented dependency the graph can't see.
  onIgnore: (ignoreIds: string[], closeModal: () => void) => void;
  closeModal?: () => void;
}> = ({ libraries, onCleanup, onIgnore, closeModal }) => {
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
      <div style={{ padding: '4px 16px 12px' }}>
        <div style={{ fontWeight: 'bold', fontSize: '1.05em', marginBottom: '6px' }}>
          Unused libraries
        </div>
        <div style={{ color: 'var(--gpColorTextSecondary)', fontSize: '0.9em', marginBottom: '8px' }}>
          Not required by anything installed. Remove them, or <b>Ignore</b> any that’s actually a needed dependency.
        </div>
        {/* DialogCheckbox (the compact checkbox row used by the filter modal) — smaller and a better
            fit for a checkable list than a ButtonItem, whose Field wrapper draws a boxed border. */}
        <Focusable style={{ maxHeight: '38vh', overflowY: 'auto', marginBottom: '8px' }}>
          {libraries.map(lib => (
            <DialogCheckbox
              key={lib.id}
              label={lib.name}
              checked={checked.has(lib.id)}
              onChange={() => toggle(lib.id)}
            />
          ))}
        </Focusable>
        {/* Actions on one row (raw DialogButtons, borderless — no Field wrapper — sized inline) to
            keep the modal short. Labels are terse; the count conveys "all vs some". The wrapper div
            carries the autofocus ref; its first button is Remove. */}
        <div ref={removeAllRef}>
          <Focusable style={{ display: 'flex', gap: '8px' }}>
            <DialogButton style={{ flex: 1, minWidth: 0 }} disabled={count === 0} onClick={() => onCleanup([...checked], close)}>
              {`Remove (${count})`}
            </DialogButton>
            <DialogButton style={{ flex: 1, minWidth: 0 }} disabled={count === 0} onClick={() => onIgnore([...checked], close)}>
              {`Ignore (${count})`}
            </DialogButton>
            <DialogButton style={{ flex: 1, minWidth: 0 }} onClick={() => close()}>
              Cancel
            </DialogButton>
          </Focusable>
        </div>
      </div>
    </ModalRoot>
  );
};

export default UnusedLibrariesModal;
