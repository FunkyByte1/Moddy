import { useEffect, useRef } from 'react';

// On the Steam Deck the on-screen keyboard only pops up once a text <input> is
// both focused and activated by a gesture — focusOnMount highlights the field
// but leaves the keyboard closed. Grab the underlying input a frame after mount
// and synthesise a click so the keyboard opens automatically. Attach the
// returned ref to a wrapper around the TextField.
export const useAutoKeyboard = () => {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const t = setTimeout(() => {
      const input = ref.current?.querySelector('input');
      if (input) {
        input.focus();
        input.click();
      }
    }, 100);
    return () => clearTimeout(t);
  }, []);
  return ref;
};
