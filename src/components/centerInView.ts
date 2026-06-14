// Keep a focused gamepad list item centered in its scroll container. Deferred a frame so
// it runs after Steam's own focus-scroll (which otherwise leaves the cursor at the edge),
// giving context above and below the current item in a long list.
export const centerInView = (el: HTMLElement | null): void => {
  if (el) requestAnimationFrame(() => el.scrollIntoView({ block: 'center', behavior: 'smooth' }));
};
