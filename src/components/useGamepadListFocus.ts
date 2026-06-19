import { useEffect, useRef, useState } from 'react';

/**
 * Gamepad focus choreography shared by the server-paginated browse tabs (Nexus, Workshop),
 * where it was previously duplicated byte-for-byte:
 *
 *  - registerRow(i): ref callback recording each rendered row element, so focus can be moved
 *    to a specific row by index.
 *  - focusRowAfterLoad(index): after a "Load more" press appends rows, return focus to the
 *    given row (the previous last row) once React has rendered the new items — otherwise focus
 *    stays on the button and "up" jumps to the bottom of the list.
 *  - focusDetail / focusSelectedRow + detailRef: pressing A on a row (or navigating right) jumps
 *    focus to the detail panel's action button; pressing B there returns to the selected row.
 *
 * `items` is the loaded list the rows render from; it drives the post-load focus effect (the new
 * rows' refs exist only after it re-renders). `selectedIndex` / `setSelectedIndex` stay owned by
 * the tab, which also uses them for selection highlighting.
 */
export function useGamepadListFocus(opts: {
  items: unknown[];
  selectedIndex: number;
  setSelectedIndex: (i: number) => void;
}) {
  const { items, selectedIndex, setSelectedIndex } = opts;
  const rowRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const detailRef = useRef<HTMLDivElement>(null);
  const [pendingFocus, setPendingFocus] = useState<number | null>(null);

  useEffect(() => {
    if (pendingFocus == null) return;
    const el = rowRefs.current.get(pendingFocus);
    const focusable = (el?.querySelector('button, [tabindex]') as HTMLElement | null) ?? el;
    focusable?.focus();
    setSelectedIndex(pendingFocus);
    setPendingFocus(null);
  }, [items, pendingFocus]);

  const registerRow = (i: number) => (el: HTMLDivElement | null) => {
    if (el) rowRefs.current.set(i, el);
    else rowRefs.current.delete(i);
  };

  const focusRowAfterLoad = (index: number) => setPendingFocus(Math.max(0, index));

  const focusDetail = () => {
    (detailRef.current?.querySelector('button, [tabindex]') as HTMLElement | null)?.focus();
  };

  const focusSelectedRow = () => {
    const el = rowRefs.current.get(selectedIndex);
    ((el?.querySelector('button, [tabindex]') as HTMLElement | null) ?? el)?.focus();
  };

  return { detailRef, registerRow, focusRowAfterLoad, focusDetail, focusSelectedRow };
}
